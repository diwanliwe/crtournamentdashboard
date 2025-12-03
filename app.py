import os
import json
import time
from datetime import datetime
from flask import Flask, jsonify, render_template
from flask_cors import CORS
import requests
from dotenv import load_dotenv
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()

app = Flask(__name__)
CORS(app)

CR_API_BASE = "https://proxy.royaleapi.dev/v1"
API_KEY = os.getenv("CR_API_KEY", "")

# Player cache - persisted to disk
CACHE_FILE = "data/player_cache.json"
player_cache = {}

# Analysis progress tracking
analysis_progress = {}


def load_cache():
    """Load player cache from disk."""
    global player_cache
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                player_cache = json.load(f)
            print(f"  Loaded {len(player_cache)} players from cache")
    except Exception as e:
        print(f"  Warning: Could not load cache: {e}")
        player_cache = {}


def save_cache():
    """Save player cache to disk."""
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(player_cache, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save cache: {e}")


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
    # Find the seasonal-trophy-road key (format: seasonal-trophy-road-YYYYMM)
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
    # (seasonal trophies default to 10000 for everyone, but only count if they actually reached 10K)
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


# Rate limiting for API calls
RATE_LIMIT = 40  # requests per second (staying under 50 limit)
import threading
rate_limit_lock = threading.Lock()
request_timestamps = []


def fetch_player_from_api(tag):
    """Fetch a single player from API with rate limiting. Returns (tag, data, error)."""
    global request_timestamps
    
    if not tag.startswith("#"):
        tag = "#" + tag
    
    # Rate limiting with lock for thread safety
    with rate_limit_lock:
        now = time.time()
        # Remove timestamps older than 1 second
        request_timestamps = [t for t in request_timestamps if now - t < 1.0]
        
        # Wait if we've hit rate limit
        while len(request_timestamps) >= RATE_LIMIT:
            time.sleep(0.05)  # Small wait, then check again
            now = time.time()
            request_timestamps = [t for t in request_timestamps if now - t < 1.0]
        
        request_timestamps.append(time.time())
    
    # Fetch from API
    encoded_tag = quote(tag, safe="")
    try:
        response = requests.get(
            f"{CR_API_BASE}/players/{encoded_tag}", 
            headers=get_headers(), 
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            data["_cachedAt"] = datetime.now().isoformat()
            return (tag, data, None)
        elif response.status_code == 404:
            return (tag, None, "Player not found")
        elif response.status_code == 429:
            # Rate limited - wait and retry
            time.sleep(2)
            return fetch_player_from_api(tag)
        else:
            return (tag, None, f"API error: {response.status_code}")
    except requests.exceptions.Timeout:
        return (tag, None, "Timeout")
    except Exception as e:
        return (tag, None, str(e))


def analyze_tournament_players(members_list, tournament_tag=None):
    """
    Analyze all players in a tournament using parallel fetching.
    Returns dict with players list and summary stats.
    """
    global analysis_progress
    
    total = len(members_list)
    results = []
    errors = []
    cached_count = 0
    fetched_count = 0
    
    # Initialize progress tracking
    if tournament_tag:
        analysis_progress[tournament_tag] = {
            "status": "running",
            "total": total,
            "processed": 0,
            "cached": 0,
            "fetched": 0,
            "errors": 0,
            "started_at": datetime.now().isoformat()
        }
    
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
    
    print(f"  Starting analysis of {total} players...")
    start_time = time.time()
    
    # Separate cached and uncached players
    cached_members = []
    uncached_members = []
    
    for member in members_list:
        player_tag = member.get("tag", "")
        if not player_tag.startswith("#"):
            player_tag = "#" + player_tag
        
        if player_tag in player_cache:
            cached_members.append((member, player_tag, player_cache[player_tag]))
        else:
            uncached_members.append((member, player_tag))
    
    print(f"  📦 {len(cached_members)} cached, {len(uncached_members)} need fetching")
    
    # Process cached players first (instant)
    for member, tag, player_data in cached_members:
        cached_count += 1
        classification = classify_player(player_data)
        tier_counts[classification["tier"]] += 1
        
        results.append({
            "tag": tag,
            "name": player_data.get("name", member.get("name", "Unknown")),
            "tournamentRank": member.get("rank"),
            "tournamentScore": member.get("score"),
            "classification": classification,
        })
    
    # Update progress after cached
    if tournament_tag:
        analysis_progress[tournament_tag].update({
            "processed": cached_count,
            "cached": cached_count,
            "fetched": 0,
        })
    
    print(f"  ✅ Processed {cached_count} cached players instantly")
    
    # Fetch uncached players in parallel
    if uncached_members:
        print(f"  🚀 Fetching {len(uncached_members)} players in parallel (up to {RATE_LIMIT}/sec)...")
        
        processed_count = cached_count
        
        with ThreadPoolExecutor(max_workers=RATE_LIMIT) as executor:
            # Submit all fetch tasks
            future_to_member = {
                executor.submit(fetch_player_from_api, tag): (member, tag) 
                for member, tag in uncached_members
            }
            
            # Process results as they complete
            for future in as_completed(future_to_member):
                member, original_tag = future_to_member[future]
                
                try:
                    tag, player_data, error = future.result()
                    
                    if error:
                        errors.append({"tag": tag, "error": error})
                    else:
                        # Cache the player data
                        player_cache[tag] = player_data
                        fetched_count += 1
                        
                        # Classify
                        classification = classify_player(player_data)
                        tier_counts[classification["tier"]] += 1
                        
                        results.append({
                            "tag": tag,
                            "name": player_data.get("name", member.get("name", "Unknown")),
                            "tournamentRank": member.get("rank"),
                            "tournamentScore": member.get("score"),
                            "classification": classification,
                        })
                    
                except Exception as e:
                    errors.append({"tag": original_tag, "error": str(e)})
                
                # Always increment processed count (success or error)
                processed_count += 1
                
                # Update progress on every fetch (for responsive UI)
                if tournament_tag:
                    analysis_progress[tournament_tag].update({
                        "processed": processed_count,
                        "cached": cached_count,
                        "fetched": fetched_count,
                        "errors": len(errors),
                    })
                
                # Progress logging every 50 players
                if processed_count % 50 == 0 or processed_count == total:
                    elapsed = time.time() - start_time
                    rate = processed_count / elapsed if elapsed > 0 else 0
                    eta = (total - processed_count) / rate if rate > 0 else 0
                    print(f"  [{processed_count}/{total}] {cached_count} cached, {fetched_count} fetched | "
                          f"{rate:.1f} players/s | ETA: {eta:.0f}s")
        
        # Save cache after parallel fetching
        save_cache()
        print(f"  💾 Cache saved ({len(player_cache)} players total)")
    
    elapsed = time.time() - start_time
    
    # Calculate percentages
    successful = len(results)
    summary = {}
    for tier, count in tier_counts.items():
        summary[tier] = {
            "count": count,
            "percent": round(count / successful * 100, 1) if successful > 0 else 0
        }
    
    # Print summary
    print(f"\n  📊 Classification Summary ({elapsed:.1f}s):")
    for tier, data in sorted(summary.items(), key=lambda x: x[1]["count"], reverse=True):
        if data["count"] > 0:
            print(f"     {tier}: {data['count']} ({data['percent']}%)")
    
    # Update progress to complete
    if tournament_tag:
        analysis_progress[tournament_tag]["status"] = "complete"
    
    return {
        "players": results,
        "summary": summary,
        "stats": {
            "total": total,
            "successful": successful,
            "errors": len(errors),
            "cached": cached_count,
            "fetched": fetched_count,
        },
        "errors": errors[:10],  # First 10 errors
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/tournament/<path:tag>")
def get_tournament(tag):
    """Get tournament summary for dashboard display."""
    if not API_KEY:
        print("ERROR: API key not configured!")
        return jsonify({"error": "API key not configured. Check your .env file."}), 500

    # Ensure tag starts with # and encode it
    if not tag.startswith("#"):
        tag = "#" + tag
    encoded_tag = quote(tag, safe="")

    url = f"{CR_API_BASE}/tournaments/{encoded_tag}"
    print(f"Fetching: {url}")

    # Retry up to 3 times with increasing timeout
    max_retries = 3
    for attempt in range(max_retries):
        try:
            timeout = 15 + (attempt * 10)  # 15s, 25s, 35s
            response = requests.get(url, headers=get_headers(), timeout=timeout)
            print(f"Response status: {response.status_code}")
            break  # Success, exit retry loop
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                print(f"Timeout on attempt {attempt + 1}, retrying...")
                time.sleep(1)
                continue
            else:
                print("Request timeout after all retries!")
                return jsonify({"error": "Request timeout - API proxy is slow"}), 504
        except requests.exceptions.RequestException as e:
            print(f"Request exception: {e}")
            return jsonify({"error": str(e)}), 500

    try:

        if response.status_code == 200:
            data = response.json()
            return jsonify(
                {
                    "tag": data.get("tag", ""),
                    "name": data.get("name", "Unknown"),
                    "status": data.get("status", "unknown"),
                    "capacity": data.get("capacity", 0),
                    "maxCapacity": data.get("maxCapacity", 1000),
                    "membersList": len(data.get("membersList", [])),
                }
            )
        elif response.status_code == 404:
            return jsonify({"error": "Tournament not found"}), 404
        elif response.status_code == 403:
            print(f"403 Forbidden - Check API key and IP whitelist")
            return jsonify({"error": "API access forbidden. Check your API key has IP 45.79.218.79 whitelisted."}), 403
        else:
            print(f"API error: {response.status_code} - {response.text[:200]}")
            return jsonify({"error": f"API error: {response.status_code}"}), response.status_code
    except Exception as e:
        print(f"Unexpected error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/tournament/<path:tag>/full")
def get_tournament_full(tag):
    """Get full tournament data including all members."""
    if not API_KEY:
        return jsonify({"error": "API key not configured"}), 500

    if not tag.startswith("#"):
        tag = "#" + tag
    encoded_tag = quote(tag, safe="")

    try:
        response = requests.get(
            f"{CR_API_BASE}/tournaments/{encoded_tag}", headers=get_headers(), timeout=10
        )

        if response.status_code == 200:
            return jsonify(response.json())
        elif response.status_code == 404:
            return jsonify({"error": "Tournament not found"}), 404
        else:
            return jsonify({"error": f"API error: {response.status_code}"}), response.status_code

    except requests.exceptions.Timeout:
        return jsonify({"error": "Request timeout"}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/player/<path:tag>")
def get_player(tag):
    """Get player profile - uses cache if available."""
    if not API_KEY:
        return jsonify({"error": "API key not configured"}), 500

    if not tag.startswith("#"):
        tag = "#" + tag

    # Check cache first
    if tag in player_cache:
        cached = player_cache[tag]
        cached["_cached"] = True
        return jsonify(cached)

    encoded_tag = quote(tag, safe="")

    try:
        response = requests.get(
            f"{CR_API_BASE}/players/{encoded_tag}", headers=get_headers(), timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            # Store in cache
            data["_cachedAt"] = datetime.now().isoformat()
            player_cache[tag] = data
            save_cache()
            data["_cached"] = False
            return jsonify(data)
        elif response.status_code == 404:
            return jsonify({"error": "Player not found"}), 404
        else:
            return jsonify({"error": f"API error: {response.status_code}"}), response.status_code

    except requests.exceptions.Timeout:
        return jsonify({"error": "Request timeout"}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cache/stats")
def cache_stats():
    """Get cache statistics."""
    return jsonify({
        "totalPlayers": len(player_cache),
        "players": list(player_cache.keys())[:20],  # First 20 for preview
    })


@app.route("/api/analysis/progress/<path:tag>")
def get_analysis_progress(tag):
    """Get the progress of an ongoing analysis."""
    if not tag.startswith("#"):
        tag = "#" + tag
    
    if tag in analysis_progress:
        return jsonify(analysis_progress[tag])
    else:
        return jsonify({"status": "not_found"}), 404


@app.route("/api/cache/clear", methods=["POST"])
def clear_cache():
    """Clear the player cache."""
    global player_cache
    player_cache = {}
    save_cache()
    return jsonify({"message": "Cache cleared"})


@app.route("/api/tournament/<path:tag>/analyze")
def analyze_tournament(tag):
    """
    Analyze all players in a tournament.
    This fetches each player's profile and classifies them.
    May take 20-30 seconds for 1000 players (with empty cache).
    """
    if not API_KEY:
        return jsonify({"error": "API key not configured"}), 500

    if not tag.startswith("#"):
        tag = "#" + tag
    encoded_tag = quote(tag, safe="")

    print(f"\n{'='*50}")
    print(f"  Analyzing tournament: {tag}")
    print(f"{'='*50}")

    # First, fetch the tournament to get members list
    try:
        response = requests.get(
            f"{CR_API_BASE}/tournaments/{encoded_tag}", 
            headers=get_headers(), 
            timeout=10
        )
        
        if response.status_code != 200:
            return jsonify({"error": f"Tournament API error: {response.status_code}"}), response.status_code
        
        tournament_data = response.json()
    except Exception as e:
        return jsonify({"error": f"Failed to fetch tournament: {e}"}), 500

    members_list = tournament_data.get("membersList", [])
    print(f"  Found {len(members_list)} players to analyze")
    
    # Analyze all players
    start_time = time.time()
    analysis = analyze_tournament_players(members_list, tournament_tag=tag)
    elapsed = time.time() - start_time
    
    print(f"  Analysis complete in {elapsed:.1f}s")
    print(f"  Summary: {analysis['stats']}")
    print(f"{'='*50}\n")

    return jsonify({
        "tournament": {
            "tag": tournament_data.get("tag"),
            "name": tournament_data.get("name"),
            "status": tournament_data.get("status"),
            "capacity": tournament_data.get("capacity"),
            "maxCapacity": tournament_data.get("maxCapacity"),
        },
        "analysis": analysis,
        "elapsed_seconds": round(elapsed, 1),
    })


@app.route("/api/player/<path:tag>/classify")
def classify_player_endpoint(tag):
    """Fetch player profile and return their classification."""
    if not API_KEY:
        return jsonify({"error": "API key not configured"}), 500

    if not tag.startswith("#"):
        tag = "#" + tag

    # Check cache first
    if tag in player_cache:
        player_data = player_cache[tag]
        cached = True
    else:
        # Fetch from API
        encoded_tag = quote(tag, safe="")
        try:
            response = requests.get(
                f"{CR_API_BASE}/players/{encoded_tag}", headers=get_headers(), timeout=10
            )
            if response.status_code != 200:
                return jsonify({"error": f"API error: {response.status_code}"}), response.status_code
            
            player_data = response.json()
            # Cache it
            player_data["_cachedAt"] = datetime.now().isoformat()
            player_cache[tag] = player_data
            save_cache()
            cached = False
        except requests.exceptions.RequestException as e:
            return jsonify({"error": str(e)}), 500

    # Classify the player
    classification = classify_player(player_data)
    
    return jsonify({
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
        "_cached": cached
    })


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  CR TOURNAMENT DASHBOARD")
    print("=" * 50)
    print("\n  Using RoyaleAPI Proxy")
    print("  Whitelist this IP in your API key: 45.79.218.79")
    print("  https://developer.clashroyale.com")
    print(f"\n  Dashboard URL: http://localhost:8080")
    print("=" * 50)
    load_cache()
    print("=" * 50 + "\n")
    app.run(debug=True, port=8080)
