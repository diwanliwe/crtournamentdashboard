# CR Tournament Dashboard

A real-time Clash Royale tournament monitoring dashboard built with Flask. Track multiple qualifier tournaments simultaneously with live player counts and status updates.

## Features

- Monitor up to 3 tournaments at once
- Real-time player count tracking
- Visual progress bars showing tournament capacity
- Auto-refresh every 3 seconds
- Tournament status indicators (in preparation, in progress, ended)

## Setup

### 1. Install Dependencies

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # macOS/Linux
# or
venv\Scripts\activate     # Windows

# Install requirements
pip install -r requirements.txt
```

### 2. Get Your API Key

Since your local machine doesn't have a static public IP, you'll need to use the **RoyaleAPI Proxy**:

1. Go to [https://developer.clashroyale.com](https://developer.clashroyale.com)
2. Create a new API key
3. When asked for the IP address to whitelist, enter:
   ```
   45.79.218.79
   ```
   (This is the RoyaleAPI proxy IP address)

### 3. Configure Environment

Create a `.env` file in the project root:

```bash
touch .env
```

Then add your API key to the `.env` file:

```
CR_API_KEY=your_api_key_here
```

> **Note:** The `.env` file is used to store your API key securely without committing it to version control.

### 4. Run the Dashboard

```bash
source venv/bin/activate  # Make sure venv is activated
python app.py
```

Open your browser at: **http://localhost:8080**

## Usage

1. Enter tournament tags in the input fields (e.g., `#2JYLU8YQ`)
2. Click **Start Monitoring**
3. The dashboard will auto-refresh every 3 seconds

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Dashboard UI |
| `GET /api/tournament/<tag>` | Get tournament summary (for dashboard) |
| `GET /api/tournament/<tag>/full` | Get full tournament data with all members |
| `GET /api/player/<tag>` | Get player profile (cached) |
| `GET /api/cache/stats` | View cache statistics |
| `POST /api/cache/clear` | Clear the player cache |

### Player Cache

The app automatically caches player profiles to `data/player_cache.json` to avoid redundant API calls. When you fetch a player:
- First request: Fetches from API and stores in cache
- Subsequent requests: Returns cached data instantly

Cached responses include `_cached: true` to indicate cache hit.

## How the Proxy Works

This app uses the [RoyaleAPI Proxy](https://docs.royaleapi.com/#/proxy) to access the official Clash Royale API:

- Official API: `https://api.clashroyale.com/v1`
- Proxy URL: `https://proxy.royaleapi.dev/v1`

The proxy forwards your authenticated requests while using a static IP (`45.79.218.79`) that you can whitelist in your API key settings.

## Example Data

See the `data/` folder for example API responses:
- `tournament_enzypel.json` - Tournament response example
- `player_example.json` - Player profile response example
- `top_player_example.json` - Top player profile response example

## Tech Stack

- **Backend**: Flask, Python
- **Frontend**: Vanilla JS, CSS
- **API**: Clash Royale Official API via RoyaleAPI Proxy

## Community Support

Join the [RoyaleAPI Developer Discord](https://discord.gg/royaleapi) for help!

