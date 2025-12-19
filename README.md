# C'est Quoi Ce Niveau ?

A Clash Royale tournament player analyzer built with FastAPI. Analyze the skill distribution of players in any tournament - find out how many Top 1K, Top 10K, and other ranked players are participating.

## Features

- **Player Distribution Analysis**: See the skill breakdown of all tournament participants
- **Tier Classification**: Top 1K, Top 10K, Top 50K, Champion Suprême, and more
- **Tournament Progress**: Live progress bar for ongoing tournaments
- **Recent Searches**: Quick access to recently analyzed tournaments with names
- **Player Caching**: Fast re-analysis with 12-hour player data cache (Upstash Redis)
- **Mobile-First Design**: Beautiful Clash Royale-themed UI that works on all devices

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
CR_API_KEY=your_api_key_here

# Optional: Upstash Redis for caching (speeds up repeated analyses)
UPSTASH_REDIS_URL=your_upstash_redis_url
UPSTASH_REDIS_TOKEN=your_upstash_redis_token
```

### 4. Run the App

```bash
source venv/bin/activate  # Make sure venv is activated
uvicorn api.index:app --reload --port 8080
```

Open your browser at: **http://localhost:8080**

## Vercel Deployment

This app is configured for Vercel serverless deployment:

```bash
# Install Vercel CLI
npm i -g vercel

# Add environment variable
vercel env add CR_API_KEY

# Deploy
vercel
```

## Usage

1. Enter a tournament tag in the search field (e.g., `#2JYLU8YQ`)
2. Click the search button or press Enter
3. Wait for the analysis to complete (may take up to 30 seconds for large tournaments)
4. View the player distribution breakdown by skill tier
5. Use recent searches to quickly re-analyze previous tournaments

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/tournament/{tag}` | Get tournament summary |
| GET | `/api/tournament/{tag}/full` | Get full tournament data with all members |
| GET | `/api/tournament/{tag}/analyze` | Analyze and classify all players |
| GET | `/api/tournaments/recent` | Get list of recently analyzed tournaments |
| GET | `/api/player/{tag}` | Get player profile |
| GET | `/api/player/{tag}/classify` | Get player classification |

## Player Classification Tiers

Players are classified into skill tiers based on their Path of Legends and trophy performance:

| Tier | French Label | Criteria |
|------|--------------|----------|
| Top 1K | Top 1K | Path of Legends rank ≤ 1,000 |
| Top 10K | Top 10K | Path of Legends rank ≤ 10,000 |
| Top 50K | Top 50K | Path of Legends rank ≤ 50,000 |
| Ever Ranked | Classé | Has any Path of Legends rank |
| Final League | Champion Suprême | Has reached Ultimate Champion league |
| Reached 12K+ | 12K+ | Trophies ≥ 12,000 |
| Trophy 10K-12K | 10K-12K | Trophies 10,000-11,999 |
| Casual | Casual (8K-10K) | Trophies 8,000-9,999 |
| Beginner | Débutant (<8K) | Trophies < 8,000 |

## How the Proxy Works

This app uses the [RoyaleAPI Proxy](https://docs.royaleapi.com/#/proxy) to access the official Clash Royale API:

- Official API: `https://api.clashroyale.com/v1`
- Proxy URL: `https://proxy.royaleapi.dev/v1`

The proxy forwards your authenticated requests while using a static IP (`45.79.218.79`) that you can whitelist in your API key settings.

## Tech Stack

- **Backend**: FastAPI, Python, httpx (async HTTP)
- **Frontend**: Vanilla JS, CSS (Clash Royale themed)
- **Caching**: Upstash Redis (12-hour player cache)
- **Analytics**: PostHog
- **Deployment**: Vercel Serverless
- **API**: Clash Royale Official API via RoyaleAPI Proxy

## Project Structure

```
/
├── api/
│   └── index.py          # FastAPI application
├── public/
│   ├── index.html        # Main UI
│   ├── public.css        # Styles (Clash Royale theme)
│   └── public.js         # Frontend logic
├── assets/
│   ├── fonts/            # Clash font
│   └── images/           # Icons and backgrounds
├── data/
│   └── *.json            # Example API responses
├── vercel.json           # Vercel configuration
└── requirements.txt      # Python dependencies
```

## Community Support

Join the [RoyaleAPI Developer Discord](https://discord.gg/royaleapi) for help!

---

**Code Ashtax** dans le magasin pour soutenir les projets ! 🎮
