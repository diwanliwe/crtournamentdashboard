import os
import time
from datetime import datetime
from urllib.parse import quote
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CR_API_BASE = "https://proxy.royaleapi.dev/v1"
API_KEY = os.getenv("CR_API_KEY", "")


def get_headers():
    return {"Authorization": f"Bearer {API_KEY}"}


def get_best_pol_rank(player_data):
    """Get the best (lowest) Path of Legends rank from current, last, or best season."""
    ranks = []
    for key in ["currentPathOfLegendSeasonResult", "lastPathOfLegendSeasonResult", "bestPathOfLegendSeasonResult"]:
        result = player_data.get(key, {})
        if result and result.get("rank") is not None:
            ranks.append(result["rank"])
    return min(ranks) if ranks else None


def has_pol_trophies(player_data):
    """Check if player has Path of Legends trophies (reached final league)."""
    for key in ["currentPathOfLegendSeasonResult", "lastPathOfLegendSeasonResult", "bestPathOfLegendSeasonResult"]:
        result = player_data.get(key, {})
        if result and result.get("trophies") and result["trophies"] > 0:
            return True
    return False


def get_seasonal_trophies(player_data):
    """Get current seasonal trophy road trophies."""
    progress = player_data.get("progress", {})
    for key, value in progress.items():
        if key.startswith("seasonal-trophy-road-"):
            return value.get("trophies", 0)
    return 0


def classify_player(player_data):
    """
    Classify a player into skill tiers (highest priority first):
    1. top_1k - PoL rank <= 1000
    2. top_10k - PoL rank <= 10000
    3. top_50k - PoL rank <= 50000
    4. ever_ranked - Has any PoL rank
    5. final_league - PoL trophies > 0 (no rank)
    6. reached_15k - Seasonal trophies = 15000 (only if base trophies = 10000)
    7. seasonal_10k_15k - Seasonal trophies 10000-14999 (only if base trophies = 10000)
    8. casual - Base trophies 8000-9999
    9. beginner - Base trophies < 8000
    """
    base_trophies = player_data.get("trophies", 0)
    
    # Check Path of Legends rank first
    best_rank = get_best_pol_rank(player_data)
    
    if best_rank is not None:
        if best_rank <= 1000:
            return {"tier": "top_1k", "label": "Top 1K", "rank": best_rank, "priority": 1}
        elif best_rank <= 10000:
            return {"tier": "top_10k", "label": "Top 10K", "rank": best_rank, "priority": 2}
        elif best_rank <= 50000:
            return {"tier": "top_50k", "label": "Top 50K", "rank": best_rank, "priority": 3}
        else:
            return {"tier": "ever_ranked", "label": "Ever Ranked", "rank": best_rank, "priority": 4}
    
    # Check if reached final league (has trophies but no rank)
    if has_pol_trophies(player_data):
        return {"tier": "final_league", "label": "Final League", "priority": 5}
    
    # Check seasonal trophy road - ONLY if player reached 10K base trophies
    if base_trophies >= 10000:
        seasonal = get_seasonal_trophies(player_data)
        if seasonal >= 15000:
            return {"tier": "reached_15k", "label": "Reached 15K", "seasonal_trophies": seasonal, "priority": 6}
        elif seasonal >= 10000:
            return {"tier": "seasonal_10k_15k", "label": "Seasonal 10K-15K", "seasonal_trophies": seasonal, "priority": 7}
    
    # Fall back to base trophies
    if base_trophies >= 8000:
        return {"tier": "casual", "label": "Casual (8K-10K)", "trophies": base_trophies, "priority": 8}
    else:
        return {"tier": "beginner", "label": "Beginner (<8K)", "trophies": base_trophies, "priority": 9}


async def fetch_player_from_api(client: httpx.AsyncClient, tag: str):
    """Fetch a single player from API. Returns (tag, data, error)."""
    if not tag.startswith("#"):
        tag = "#" + tag
    
    encoded_tag = quote(tag, safe="")
    try:
        response = await client.get(
            f"{CR_API_BASE}/players/{encoded_tag}",
            headers=get_headers(),
            timeout=15.0
        )
        
        if response.status_code == 200:
            data = response.json()
            data["_cachedAt"] = datetime.now().isoformat()
            return (tag, data, None)
        elif response.status_code == 404:
            return (tag, None, "Player not found")
        elif response.status_code == 429:
            # Rate limited - wait and retry once
            await asyncio.sleep(2)
            return await fetch_player_from_api(client, tag)
        else:
            return (tag, None, f"API error: {response.status_code}")
    except httpx.TimeoutException:
        return (tag, None, "Timeout")
    except Exception as e:
        return (tag, None, str(e))


import asyncio


async def analyze_tournament_players(members_list):
    """
    Analyze all players in a tournament using async fetching.
    Returns dict with players list and summary stats.
    """
    total = len(members_list)
    results = []
    errors = []
    
    # Initialize summary counters
    tier_counts = {
        "top_1k": 0,
        "top_10k": 0,
        "top_50k": 0,
        "ever_ranked": 0,
        "final_league": 0,
        "reached_15k": 0,
        "seasonal_10k_15k": 0,
        "casual": 0,
        "beginner": 0,
    }
    
    start_time = time.time()
    
    # Use async client with connection pooling
    async with httpx.AsyncClient() as client:
        # Create tasks for all players (with semaphore to limit concurrency)
        semaphore = asyncio.Semaphore(30)  # Limit concurrent requests
        
        async def fetch_with_semaphore(member):
            async with semaphore:
                player_tag = member.get("tag", "")
                tag, player_data, error = await fetch_player_from_api(client, player_tag)
                return (member, tag, player_data, error)
        
        tasks = [fetch_with_semaphore(member) for member in members_list]
        
        for coro in asyncio.as_completed(tasks):
            member, tag, player_data, error = await coro
            
            if error:
                errors.append({"tag": tag, "error": error})
            elif player_data:
                classification = classify_player(player_data)
                tier_counts[classification["tier"]] += 1
                
                results.append({
                    "tag": tag,
                    "name": player_data.get("name", member.get("name", "Unknown")),
                    "tournamentRank": member.get("rank"),
                    "tournamentScore": member.get("score"),
                    "classification": classification,
                })
    
    elapsed = time.time() - start_time
    
    # Calculate percentages
    successful = len(results)
    summary = {}
    for tier, count in tier_counts.items():
        summary[tier] = {
            "count": count,
            "percent": round(count / successful * 100, 1) if successful > 0 else 0
        }
    
    return {
        "players": results,
        "summary": summary,
        "stats": {
            "total": total,
            "successful": successful,
            "errors": len(errors),
            "cached": 0,  # No caching in serverless
            "fetched": successful,
        },
        "errors": errors[:10],  # First 10 errors
    }


@app.get("/api/cache/stats")
async def cache_stats():
    """Get cache statistics (no-op in serverless)."""
    return {
        "totalPlayers": 0,
        "players": [],
        "message": "Caching disabled in serverless mode"
    }


@app.post("/api/cache/clear")
async def clear_cache():
    """Clear the player cache (no-op in serverless)."""
    return {"message": "Cache clearing not applicable in serverless mode"}


# IMPORTANT: More specific routes must come BEFORE less specific ones
# /api/tournament/{tag}/analyze BEFORE /api/tournament/{tag}
# /api/tournament/{tag}/full BEFORE /api/tournament/{tag}
# /api/player/{tag}/classify BEFORE /api/player/{tag}

@app.get("/api/tournament/{tag}/analyze")
async def analyze_tournament(tag: str):
    """
    Analyze all players in a tournament.
    This fetches each player's profile and classifies them.
    """
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API key not configured")

    if not tag.startswith("#"):
        tag = "#" + tag
    encoded_tag = quote(tag, safe="")

    # First, fetch the tournament to get members list
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{CR_API_BASE}/tournaments/{encoded_tag}",
                headers=get_headers(),
                timeout=10.0
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=f"Tournament API error: {response.status_code}")
            
            tournament_data = response.json()
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch tournament: {e}")

    members_list = tournament_data.get("membersList", [])
    
    # Analyze all players
    start_time = time.time()
    analysis = await analyze_tournament_players(members_list)
    elapsed = time.time() - start_time

    return {
        "tournament": {
            "tag": tournament_data.get("tag"),
            "name": tournament_data.get("name"),
            "status": tournament_data.get("status"),
            "capacity": tournament_data.get("capacity"),
            "maxCapacity": tournament_data.get("maxCapacity"),
        },
        "analysis": analysis,
        "elapsed_seconds": round(elapsed, 1),
    }


@app.get("/api/tournament/{tag}/full")
async def get_tournament_full(tag: str):
    """Get full tournament data including all members."""
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API key not configured")

    if not tag.startswith("#"):
        tag = "#" + tag
    encoded_tag = quote(tag, safe="")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{CR_API_BASE}/tournaments/{encoded_tag}",
                headers=get_headers(),
                timeout=10.0
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                raise HTTPException(status_code=404, detail="Tournament not found")
            else:
                raise HTTPException(status_code=response.status_code, detail=f"API error: {response.status_code}")

        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Request timeout")
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tournament/{tag}")
async def get_tournament(tag: str):
    """Get tournament summary for dashboard display."""
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API key not configured. Check your .env file.")

    # Ensure tag starts with # and encode it
    if not tag.startswith("#"):
        tag = "#" + tag
    encoded_tag = quote(tag, safe="")

    url = f"{CR_API_BASE}/tournaments/{encoded_tag}"

    # Retry up to 3 times with increasing timeout
    max_retries = 3
    async with httpx.AsyncClient() as client:
        for attempt in range(max_retries):
            try:
                timeout = 15 + (attempt * 10)  # 15s, 25s, 35s
                response = await client.get(url, headers=get_headers(), timeout=float(timeout))
                break  # Success, exit retry loop
            except httpx.TimeoutException:
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                else:
                    raise HTTPException(status_code=504, detail="Request timeout - API proxy is slow")
            except httpx.RequestError as e:
                raise HTTPException(status_code=500, detail=str(e))

        if response.status_code == 200:
            data = response.json()
            return {
                "tag": data.get("tag", ""),
                "name": data.get("name", "Unknown"),
                "status": data.get("status", "unknown"),
                "capacity": data.get("capacity", 0),
                "maxCapacity": data.get("maxCapacity", 1000),
                "membersList": len(data.get("membersList", [])),
            }
        elif response.status_code == 404:
            raise HTTPException(status_code=404, detail="Tournament not found")
        elif response.status_code == 403:
            raise HTTPException(status_code=403, detail="API access forbidden. Check your API key has IP 45.79.218.79 whitelisted.")
        else:
            raise HTTPException(status_code=response.status_code, detail=f"API error: {response.status_code}")


@app.get("/api/player/{tag}/classify")
async def classify_player_endpoint(tag: str):
    """Fetch player profile and return their classification."""
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API key not configured")

    if not tag.startswith("#"):
        tag = "#" + tag

    encoded_tag = quote(tag, safe="")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{CR_API_BASE}/players/{encoded_tag}",
                headers=get_headers(),
                timeout=10.0
            )
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=f"API error: {response.status_code}")
            
            player_data = response.json()
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=str(e))

    # Classify the player
    classification = classify_player(player_data)
    
    return {
        "tag": player_data.get("tag"),
        "name": player_data.get("name"),
        "trophies": player_data.get("trophies"),
        "classification": classification,
        "pathOfLegend": {
            "current": player_data.get("currentPathOfLegendSeasonResult"),
            "last": player_data.get("lastPathOfLegendSeasonResult"),
            "best": player_data.get("bestPathOfLegendSeasonResult"),
        },
        "seasonalTrophies": get_seasonal_trophies(player_data),
        "_cached": False
    }


@app.get("/api/player/{tag}")
async def get_player(tag: str):
    """Get player profile."""
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API key not configured")

    if not tag.startswith("#"):
        tag = "#" + tag

    encoded_tag = quote(tag, safe="")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{CR_API_BASE}/players/{encoded_tag}",
                headers=get_headers(),
                timeout=10.0
            )

            if response.status_code == 200:
                data = response.json()
                data["_cached"] = False
                return data
            elif response.status_code == 404:
                raise HTTPException(status_code=404, detail="Player not found")
            else:
                raise HTTPException(status_code=response.status_code, detail=f"API error: {response.status_code}")

        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Request timeout")
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=str(e))


# --- Static file serving for LOCAL DEVELOPMENT only ---
# Must be at the END so API routes are matched first
# In production (Vercel), static files are served directly from public/
PUBLIC_DIR = Path(__file__).parent.parent / "public"

@app.get("/")
async def serve_index():
    if PUBLIC_DIR.exists():
        return FileResponse(PUBLIC_DIR / "index.html")
    raise HTTPException(status_code=404, detail="Not found")

@app.get("/{filename:path}")
async def serve_static(filename: str):
    # Skip API routes (they should be matched above)
    if filename.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    
    file_path = PUBLIC_DIR / filename
    if PUBLIC_DIR.exists() and file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="File not found")

