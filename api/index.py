import os
import time
import json
from datetime import datetime
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# ============================================================
# Upstash KV Cache Setup
# ============================================================
from upstash_redis import Redis

# Initialize Upstash Redis client (uses KV_REST_API_URL and KV_REST_API_TOKEN)
kv_url = os.getenv("KV_REST_API_URL")
kv_token = os.getenv("KV_REST_API_TOKEN")

if kv_url and kv_token:
    kv = Redis(url=kv_url, token=kv_token)
    KV_ENABLED = True
    print("[KV Cache] Upstash Redis connected")
else:
    kv = None
    KV_ENABLED = False
    print("[KV Cache] Not configured - missing KV_REST_API_URL or KV_REST_API_TOKEN")

# Cache TTL for player data (12 hours in seconds)
PLAYER_KV_TTL = 12 * 60 * 60


def get_player_cache_key(tag: str) -> str:
    """Generate cache key for a player tag."""
    # Normalize tag (ensure it starts with #)
    if not tag.startswith("#"):
        tag = "#" + tag
    return f"player:{tag}"


async def get_cached_players(tags: list[str]) -> dict:
    """
    Get multiple players from KV cache.
    Returns dict of {tag: classification_data} for found players.
    """
    if not KV_ENABLED or not tags:
        return {}
    
    try:
        # Build cache keys
        keys = [get_player_cache_key(tag) for tag in tags]
        
        # MGET all keys at once (1 command for many keys)
        results = kv.mget(*keys)
        
        cached = {}
        for i, result in enumerate(results):
            if result is not None:
                # Parse JSON if it's a string
                if isinstance(result, str):
                    cached[tags[i]] = json.loads(result)
                else:
                    cached[tags[i]] = result
        
        return cached
    except Exception as e:
        print(f"[KV Cache] Error getting players: {e}")
        return {}


async def cache_players(players_data: list[dict]):
    """
    Cache multiple players to KV.
    Each player_data should have 'tag' and 'classification' keys.
    """
    if not KV_ENABLED or not players_data:
        return
    
    try:
        # Use pipeline for batch set with TTL
        pipe = kv.pipeline()
        
        for player in players_data:
            tag = player.get("tag", "")
            if tag:
                key = get_player_cache_key(tag)
                # Store classification + metadata
                data = {
                    "name": player.get("name", ""),
                    "classification": player.get("classification", {}),
                    "cached_at": datetime.now().isoformat()
                }
                pipe.setex(key, PLAYER_KV_TTL, json.dumps(data))
        
        pipe.exec()
    except Exception as e:
        print(f"[KV Cache] Error caching players: {e}")


async def add_recent_tournament(tag: str, name: str, player_count: int, status: str):
    """
    Add a tournament to the recent tournaments list.
    Uses a Redis list with LPUSH + LTRIM to keep only the last N tournaments.
    Deduplicates by tag.
    """
    if not KV_ENABLED:
        return
    
    try:
        # Create tournament entry
        entry = json.dumps({
            "tag": tag,
            "name": name,
            "playerCount": player_count,
            "status": status,
            "searchedAt": datetime.now().isoformat()
        })
        
        # Get current list to check for duplicates
        current = kv.lrange(RECENT_TOURNAMENTS_KEY, 0, RECENT_TOURNAMENTS_MAX * 2)
        
        # Filter out any existing entry with the same tag
        filtered = []
        for item in current:
            try:
                parsed = json.loads(item) if isinstance(item, str) else item
                if parsed.get("tag") != tag:
                    filtered.append(item)
            except:
                continue
        
        # Use pipeline to rebuild the list atomically
        pipe = kv.pipeline()
        pipe.delete(RECENT_TOURNAMENTS_KEY)
        
        # Add new entry first (most recent), then existing ones
        pipe.lpush(RECENT_TOURNAMENTS_KEY, entry)
        for item in filtered[:RECENT_TOURNAMENTS_MAX - 1]:
            if isinstance(item, str):
                pipe.rpush(RECENT_TOURNAMENTS_KEY, item)
            else:
                pipe.rpush(RECENT_TOURNAMENTS_KEY, json.dumps(item))
        
        # Set TTL on the list
        pipe.expire(RECENT_TOURNAMENTS_KEY, RECENT_TOURNAMENTS_TTL)
        pipe.exec()
        
        print(f"[Recent] Added tournament: {name} ({tag})")
    except Exception as e:
        print(f"[Recent] Error adding tournament: {e}")


async def get_recent_tournaments() -> list[dict]:
    """Get the list of recent tournaments."""
    if not KV_ENABLED:
        return []
    
    try:
        items = kv.lrange(RECENT_TOURNAMENTS_KEY, 0, RECENT_TOURNAMENTS_MAX - 1)
        result = []
        for item in items:
            try:
                parsed = json.loads(item) if isinstance(item, str) else item
                result.append(parsed)
            except:
                continue
        return result
    except Exception as e:
        print(f"[Recent] Error getting tournaments: {e}")
        return []

# PostHog server-side tracking
POSTHOG_API_KEY = os.getenv("POSTHOG_KEY", "")
POSTHOG_HOST = "https://us.i.posthog.com"


async def capture_event(event_name: str, distinct_id: str = "anonymous", properties: dict = None):
    """Send event to PostHog server-side (bypasses ad blockers)."""
    if not POSTHOG_API_KEY:
        return
    
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{POSTHOG_HOST}/capture/",
                json={
                    "api_key": POSTHOG_API_KEY,
                    "event": event_name,
                    "distinct_id": distinct_id,
                    "properties": properties or {}
                },
                timeout=5.0
            )
    except Exception as e:
        print(f"[PostHog] Failed to capture event: {e}")

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

# Cache duration for player profiles (12 hours = 43200 seconds)
PLAYER_CACHE_DURATION = 12 * 60 * 60  # 12 hours in seconds
PLAYER_CACHE_STALE = 24 * 60 * 60  # Allow stale for 24 hours while revalidating

# Cache duration for tournament analysis (shorter - tournaments are dynamic)
ANALYSIS_CACHE_DURATION = 5 * 60  # 5 minutes for active tournaments
ANALYSIS_CACHE_STALE = 10 * 60  # 10 minutes stale-while-revalidate
ANALYSIS_ENDED_CACHE_DURATION = 12 * 60 * 60  # 12 hours for ended tournaments

# Recent tournaments settings
RECENT_TOURNAMENTS_KEY = "recent_tournaments"
RECENT_TOURNAMENTS_MAX = 5
RECENT_TOURNAMENTS_TTL = 7 * 24 * 60 * 60  # 7 days


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


async def fetch_player_from_api(client: httpx.AsyncClient, tag: str, base_url: str = None):
    """
    Fetch a single player from API. Returns (tag, data, error, was_cached).
    If base_url is provided, fetches through our cached endpoint.
    Otherwise, fetches directly from CR API.
    """
    if not tag.startswith("#"):
        tag = "#" + tag
    
    encoded_tag = quote(tag, safe="")
    try:
        if base_url:
            # Fetch through our cached endpoint (hits Vercel edge cache)
            response = await client.get(
                f"{base_url}/api/player/{encoded_tag}",
                timeout=15.0
            )
        else:
            # Direct API call (no caching)
            response = await client.get(
                f"{CR_API_BASE}/players/{encoded_tag}",
                headers=get_headers(),
                timeout=15.0
            )
        
        if response.status_code == 200:
            data = response.json()
            # Check if response came from cache (Vercel adds x-vercel-cache header)
            was_cached = response.headers.get("x-vercel-cache") == "HIT"
            if "_cachedAt" not in data:
                data["_cachedAt"] = datetime.now().isoformat()
            return (tag, data, None, was_cached)
        elif response.status_code == 404:
            return (tag, None, "Player not found", False)
        elif response.status_code == 429:
            # Rate limited - wait and retry once
            await asyncio.sleep(2)
            return await fetch_player_from_api(client, tag, base_url)
        else:
            return (tag, None, f"API error: {response.status_code}", False)
    except httpx.TimeoutException:
        return (tag, None, "Timeout", False)
    except Exception as e:
        return (tag, None, str(e), False)


import asyncio

# Get the base URL for internal API calls (for caching)
def get_vercel_url():
    """Get the Vercel deployment URL for internal cached API calls."""
    # Vercel sets these environment variables
    vercel_url = os.environ.get("VERCEL_URL")
    if vercel_url:
        return f"https://{vercel_url}"
    # Fallback for production domain
    vercel_project_url = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL")
    if vercel_project_url:
        return f"https://{vercel_project_url}"
    return None


async def analyze_tournament_players(members_list):
    """
    Analyze all players in a tournament using KV cache + async fetching.
    
    Flow:
    1. Get all player tags from tournament
    2. Check KV cache for existing player data
    3. Only fetch NEW players from Clash Royale API
    4. Cache the new players
    5. Return merged results
    
    This dramatically reduces API calls when:
    - Same tournament is analyzed multiple times
    - Same players appear in different tournaments
    """
    total = len(members_list)
    results = []
    errors = []
    cache_hits = 0
    api_fetches = 0
    
    # Initialize summary counters
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
    
    # Step 1: Extract all player tags
    all_tags = []
    tag_to_member = {}
    for member in members_list:
        tag = member.get("tag", "")
        if tag:
            if not tag.startswith("#"):
                tag = "#" + tag
            all_tags.append(tag)
            tag_to_member[tag] = member
    
    # Step 2: Check KV cache for all players
    cached_players = await get_cached_players(all_tags)
    cache_hits = len(cached_players)
    
    # Process cached players and track oldest cache time
    oldest_cache_time = None
    
    for tag, cached_data in cached_players.items():
        member = tag_to_member.get(tag, {})
        classification = cached_data.get("classification", {})
        
        # Track oldest cache time
        cached_at = cached_data.get("cached_at")
        if cached_at:
            if oldest_cache_time is None or cached_at < oldest_cache_time:
                oldest_cache_time = cached_at
        
        if classification and classification.get("tier"):
            tier_counts[classification["tier"]] += 1
            results.append({
                "tag": tag,
                "name": cached_data.get("name", member.get("name", "Unknown")),
                "tournamentRank": member.get("rank"),
                "tournamentScore": member.get("score"),
                "classification": classification,
                "_fromCache": True,
            })
    
    # Step 3: Find players NOT in cache
    tags_to_fetch = [tag for tag in all_tags if tag not in cached_players]
    
    # Step 4: Fetch missing players from API
    new_players_to_cache = []
    
    if tags_to_fetch:
        async with httpx.AsyncClient() as client:
            semaphore = asyncio.Semaphore(30)
            
            async def fetch_with_semaphore(tag):
                async with semaphore:
                    return await fetch_player_from_api(client, tag, None)
            
            tasks = [fetch_with_semaphore(tag) for tag in tags_to_fetch]
            
            for coro in asyncio.as_completed(tasks):
                tag, player_data, error, _ = await coro
                
                if error:
                    errors.append({"tag": tag, "error": error})
                elif player_data:
                    api_fetches += 1
                    classification = classify_player(player_data)
                    tier_counts[classification["tier"]] += 1
                    
                    member = tag_to_member.get(tag, {})
                    player_result = {
                        "tag": tag,
                        "name": player_data.get("name", member.get("name", "Unknown")),
                        "tournamentRank": member.get("rank"),
                        "tournamentScore": member.get("score"),
                        "classification": classification,
                        "_fromCache": False,
                    }
                    results.append(player_result)
                    
                    # Prepare for caching
                    new_players_to_cache.append({
                        "tag": tag,
                        "name": player_data.get("name", ""),
                        "classification": classification,
                    })
    
    # Step 5: Cache new players
    if new_players_to_cache:
        await cache_players(new_players_to_cache)
    
    elapsed = time.time() - start_time
    
    # Calculate percentages
    successful = len(results)
    summary = {}
    for tier, count in tier_counts.items():
        summary[tier] = {
            "count": count,
            "percent": round(count / successful * 100, 1) if successful > 0 else 0
        }
    
    # Calculate cache expiry time if we have cached data
    cache_info = {}
    if oldest_cache_time and cache_hits > 0:
        try:
            from datetime import datetime, timedelta
            cached_dt = datetime.fromisoformat(oldest_cache_time.replace('Z', '+00:00'))
            expires_dt = cached_dt + timedelta(seconds=PLAYER_KV_TTL)
            cache_info = {
                "oldest_cached_at": oldest_cache_time,
                "expires_at": expires_dt.isoformat(),
                "ttl_hours": PLAYER_KV_TTL / 3600,
            }
        except:
            pass
    
    return {
        "players": results,
        "summary": summary,
        "stats": {
            "total": total,
            "successful": successful,
            "errors": len(errors),
            "from_cache": cache_hits,
            "from_api": api_fetches,
            "cache_enabled": KV_ENABLED,
            "cache_info": cache_info,
        },
        "errors": errors[:10],
    }


@app.get("/api/tournament/{tag:path}/analyze")
async def analyze_tournament(tag: str, response: Response):
    """
    Analyze all players in a tournament.
    This fetches each player's profile and classifies them.
    
    Cached at Vercel's edge:
    - Ended tournaments: 12 hours
    - Active/prep tournaments: 5 minutes
    """
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API key not configured")

    if not tag.startswith("#"):
        tag = "#" + tag
    encoded_tag = quote(tag, safe="")

    # First, fetch the tournament to get members list
    async with httpx.AsyncClient() as client:
        try:
            api_response = await client.get(
                f"{CR_API_BASE}/tournaments/{encoded_tag}",
                headers=get_headers(),
                timeout=10.0
            )
            
            if api_response.status_code != 200:
                raise HTTPException(status_code=api_response.status_code, detail=f"Tournament API error: {api_response.status_code}")
            
            tournament_data = api_response.json()
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch tournament: {e}")

    members_list = tournament_data.get("membersList", [])
    tournament_status = tournament_data.get("status", "")
    tournament_name = tournament_data.get("name", "Unknown")
    
    # Analyze all players
    start_time = time.time()
    analysis = await analyze_tournament_players(members_list)
    elapsed = time.time() - start_time
    
    # Add to recent tournaments list (non-blocking)
    await add_recent_tournament(
        tag=tag,
        name=tournament_name,
        player_count=len(members_list),
        status=tournament_status
    )
    
    # Set cache duration based on tournament status
    if tournament_status == "ended":
        # Ended tournaments can be cached for 12 hours
        cache_duration = ANALYSIS_ENDED_CACHE_DURATION
        stale_duration = ANALYSIS_ENDED_CACHE_DURATION
    else:
        # Active/prep tournaments cached for 5 minutes
        cache_duration = ANALYSIS_CACHE_DURATION
        stale_duration = ANALYSIS_CACHE_STALE
    
    # Set Vercel edge cache headers
    response.headers["Cache-Control"] = f"public, s-maxage={cache_duration}, stale-while-revalidate={stale_duration}"
    response.headers["CDN-Cache-Control"] = f"public, max-age={cache_duration}"
    response.headers["Vercel-CDN-Cache-Control"] = f"public, max-age={cache_duration}"

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
        "_cached_at": datetime.now().isoformat(),
        "_cache_duration_seconds": cache_duration,
    }


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
            
            # Track tournament search event (server-side)
            await capture_event("tournament_searched", properties={
                "tournament_tag": data.get("tag", ""),
                "tournament_name": data.get("name", ""),
                "player_count": len(data.get("membersList", [])),
            })
            
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


@app.get("/api/player/{tag:path}/classify")
async def classify_player_endpoint(tag: str, response: Response):
    """
    Fetch player profile and return their classification.
    Cached for 12 hours at Vercel's edge.
    """
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API key not configured")

    if not tag.startswith("#"):
        tag = "#" + tag

    encoded_tag = quote(tag, safe="")
    
    async with httpx.AsyncClient() as client:
        try:
            api_response = await client.get(
                f"{CR_API_BASE}/players/{encoded_tag}",
                headers=get_headers(),
                timeout=10.0
            )
            if api_response.status_code != 200:
                raise HTTPException(status_code=api_response.status_code, detail=f"API error: {api_response.status_code}")
            
            player_data = api_response.json()
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=str(e))

    # Classify the player
    classification = classify_player(player_data)
    
    # Set Vercel edge cache headers
    response.headers["Cache-Control"] = f"public, s-maxage={PLAYER_CACHE_DURATION}, stale-while-revalidate={PLAYER_CACHE_STALE}"
    response.headers["CDN-Cache-Control"] = f"public, max-age={PLAYER_CACHE_DURATION}"
    response.headers["Vercel-CDN-Cache-Control"] = f"public, max-age={PLAYER_CACHE_DURATION}"
    
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
        "_cachedAt": datetime.now().isoformat()
    }


@app.get("/api/player/{tag:path}")
async def get_player(tag: str, response: Response):
    """
    Get player profile with Vercel edge caching.
    Cached for 12 hours, serves stale while revalidating for up to 24 hours.
    """
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API key not configured")

    if not tag.startswith("#"):
        tag = "#" + tag

    encoded_tag = quote(tag, safe="")

    async with httpx.AsyncClient() as client:
        try:
            api_response = await client.get(
                f"{CR_API_BASE}/players/{encoded_tag}",
                headers=get_headers(),
                timeout=10.0
            )

            if api_response.status_code == 200:
                data = api_response.json()
                data["_cachedAt"] = datetime.now().isoformat()
                
                # Set Vercel edge cache headers (12 hours cache, 24 hours stale-while-revalidate)
                response.headers["Cache-Control"] = f"public, s-maxage={PLAYER_CACHE_DURATION}, stale-while-revalidate={PLAYER_CACHE_STALE}"
                response.headers["CDN-Cache-Control"] = f"public, max-age={PLAYER_CACHE_DURATION}"
                response.headers["Vercel-CDN-Cache-Control"] = f"public, max-age={PLAYER_CACHE_DURATION}"
                
                return data
            elif api_response.status_code == 404:
                raise HTTPException(status_code=404, detail="Player not found")
            else:
                raise HTTPException(status_code=api_response.status_code, detail=f"API error: {api_response.status_code}")

        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Request timeout")
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tournaments/recent")
async def get_recent_tournaments_endpoint(response: Response):
    """
    Get the list of recently searched tournaments.
    Returns the last 5 tournaments searched by any user.
    """
    tournaments = await get_recent_tournaments()
    
    # Short cache for this endpoint (1 minute)
    response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=120"
    
    return {
        "tournaments": tournaments,
        "count": len(tournaments)
    }


@app.get("/api/cache/stats")
async def cache_stats():
    """Get cache configuration info."""
    stats = {
        "kv_cache": {
            "enabled": KV_ENABLED,
            "type": "upstash_redis",
            "ttl_hours": PLAYER_KV_TTL / 3600,
        },
        "edge_cache": {
            "player_cache_hours": PLAYER_CACHE_DURATION / 3600,
            "stale_while_revalidate_hours": PLAYER_CACHE_STALE / 3600,
        },
        "message": "Player classifications are cached in Upstash KV for 12 hours. Tournament analysis checks cache first, only fetches new players from API."
    }
    
    # Try to get some cache info from KV
    if KV_ENABLED:
        try:
            info = kv.dbsize()
            stats["kv_cache"]["total_keys"] = info
        except:
            pass
    
    return stats


@app.post("/api/cache/clear")
async def clear_cache():
    """Clear the player cache (Vercel edge cache cannot be cleared via API)."""
    return {
        "message": "Vercel edge cache automatically expires after 12 hours. To force refresh a specific player, wait for cache expiry or redeploy.",
        "cache_duration_hours": PLAYER_CACHE_DURATION / 3600
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