import os
import time
from datetime import datetime
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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


def classify_player(player_data):
    """
    Classify a player into skill tiers (highest priority first):
    1. top_1k - PoL rank <= 1000
    2. top_10k - PoL rank <= 10000
    3. top_50k - PoL rank <= 50000
    4. ever_ranked - Has any PoL rank
    5. final_league - PoL trophies > 0 (no rank)
    6. reached_12k - Base trophies >= 12000
    7. trophy_10k_12k - Base trophies 10000-11999
    8. casual - Base trophies 8000-9999
    9. beginner - Base trophies < 8000
    
    Note: Seasonal trophies removed in Dec 2024 update, now using base trophies only.
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
            return {"tier": "ever_ranked", "label": "Classé", "rank": best_rank, "priority": 4}
    
    # Check if reached final league (has trophies but no rank)
    if has_pol_trophies(player_data):
        return {"tier": "final_league", "label": "Ligue Ultime", "priority": 5}
    
    # Classify by base trophies (no more seasonal trophies since Dec 2024)
    if base_trophies >= 12000:
        return {"tier": "reached_12k", "label": "12K+", "trophies": base_trophies, "priority": 6}
    elif base_trophies >= 10000:
        return {"tier": "trophy_10k_12k", "label": "10K-12K", "trophies": base_trophies, "priority": 7}
    elif base_trophies >= 8000:
        return {"tier": "casual", "label": "Casual (8K-10K)", "trophies": base_trophies, "priority": 8}
    else:
        return {"tier": "beginner", "label": "Débutant (<8K)", "trophies": base_trophies, "priority": 9}


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
    
    # Initialize summary counters (updated for Dec 2024 trophy changes)
    tier_counts = {
        "top_1k": 0,
        "top_10k": 0,
        "top_50k": 0,
        "ever_ranked": 0,
        "final_league": 0,
        "reached_12k": 0,
        "trophy_10k_12k": 0,
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


@app.get("/api/tournament/{tag:path}")
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


@app.get("/api/tournament/{tag:path}/full")
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


@app.get("/api/player/{tag:path}")
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


@app.get("/api/tournament/{tag:path}/analyze")
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


@app.get("/api/player/{tag:path}/classify")
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
        "_cached": False
    }


# ============================================================
# Static file serving (for local development only)
# On Vercel, static files are served directly from the root folder
# ============================================================
import os
import pathlib
from fastapi.responses import HTMLResponse, FileResponse

# Only enable static file serving when running locally (not on Vercel)
if not os.environ.get("VERCEL"):
    PUBLIC_DIR = pathlib.Path(__file__).parent.parent / "public"

    @app.get("/", response_class=HTMLResponse)
    async def serve_homepage():
        index_path = PUBLIC_DIR / "index.html"
        if index_path.exists():
            return HTMLResponse(content=index_path.read_text())
        raise HTTPException(status_code=404, detail="index.html not found")

    @app.get("/dashboard.html", response_class=HTMLResponse)
    async def serve_dashboard():
        dashboard_path = PUBLIC_DIR / "dashboard.html"
        if dashboard_path.exists():
            return HTMLResponse(content=dashboard_path.read_text())
        raise HTTPException(status_code=404, detail="dashboard.html not found")

    @app.get("/public.css")
    async def serve_public_css():
        css_path = PUBLIC_DIR / "public.css"
        if css_path.exists():
            return FileResponse(css_path, media_type="text/css")
        raise HTTPException(status_code=404, detail="public.css not found")

    @app.get("/public.js")
    async def serve_public_js():
        js_path = PUBLIC_DIR / "public.js"
        if js_path.exists():
            return FileResponse(js_path, media_type="application/javascript")
        raise HTTPException(status_code=404, detail="public.js not found")

    @app.get("/style.css")
    async def serve_style_css():
        css_path = PUBLIC_DIR / "style.css"
        if css_path.exists():
            return FileResponse(css_path, media_type="text/css")
        raise HTTPException(status_code=404, detail="style.css not found")

    @app.get("/script.js")
    async def serve_script_js():
        js_path = PUBLIC_DIR / "script.js"
        if js_path.exists():
            return FileResponse(js_path, media_type="application/javascript")
        raise HTTPException(status_code=404, detail="script.js not found")

    @app.get("/assets/{path:path}")
    async def serve_assets(path: str):
        asset_path = PUBLIC_DIR / "assets" / path
        if asset_path.exists() and asset_path.is_file():
            suffix = asset_path.suffix.lower()
            content_types = {
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".svg": "image/svg+xml", ".ico": "image/x-icon",
                ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
            }
            return FileResponse(asset_path, media_type=content_types.get(suffix, "application/octet-stream"))
        raise HTTPException(status_code=404, detail=f"Asset not found: {path}")