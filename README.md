# CR Tournament Dashboard

A real-time Clash Royale tournament monitoring dashboard built with FastAPI. Track multiple qualifier tournaments simultaneously with live player counts, status updates, and player skill analysis.

## Features

- Monitor up to 3 tournaments at once
- Real-time player count tracking
- Visual progress bars showing tournament capacity
- Auto-refresh every 5 seconds
- Tournament status indicators (in preparation, in progress, ended)
- **Player Analysis**: Classify all players by skill tier (Top 1K, Top 10K, etc.)

## Setup

### 1. Install Dependencies

```bash
# Create virtual environment
python3 -m venv venv-fastapi

# Activate virtual environment
source venv-fastapi/bin/activate  # macOS/Linux
# or
venv-fastapi\Scripts\activate     # Windows

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
```

### 4. Run the Dashboard

```bash
source venv-fastapi/bin/activate  # Make sure venv is activated
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

1. Enter tournament tags in the input fields (e.g., `#2JYLU8YQ`)
2. Click **Start Monitoring**
3. The dashboard will auto-refresh every 5 seconds
4. Click **Analyze Players** to classify all players by skill tier

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/tournament/{tag}` | Get tournament summary |
| GET | `/api/tournament/{tag}/full` | Get full tournament data with all members |
| GET | `/api/tournament/{tag}/analyze` | Analyze and classify all players |
| GET | `/api/player/{tag}` | Get player profile |
| GET | `/api/player/{tag}/classify` | Get player classification |
| GET | `/api/cache/stats` | Cache stats (disabled in serverless) |
| POST | `/api/cache/clear` | Clear cache (no-op in serverless) |

## Player Classification Tiers

Players are classified into skill tiers based on their Path of Legends performance:

| Tier | Criteria |
|------|----------|
| Top 1K | PoL rank ≤ 1,000 |
| Top 10K | PoL rank ≤ 10,000 |
| Top 50K | PoL rank ≤ 50,000 |
| Ever Ranked | Has any PoL rank |
| Final League | Has PoL trophies but no rank |
| Reached 15K | Seasonal trophies ≥ 15,000 |
| Seasonal 10K-15K | Seasonal trophies 10,000-14,999 |
| Casual | Base trophies 8,000-9,999 |
| Beginner | Base trophies < 8,000 |

## How the Proxy Works

This app uses the [RoyaleAPI Proxy](https://docs.royaleapi.com/#/proxy) to access the official Clash Royale API:

- Official API: `https://api.clashroyale.com/v1`
- Proxy URL: `https://proxy.royaleapi.dev/v1`

The proxy forwards your authenticated requests while using a static IP (`45.79.218.79`) that you can whitelist in your API key settings.

## Tech Stack

- **Backend**: FastAPI, Python, httpx (async HTTP)
- **Frontend**: Vanilla JS, CSS
- **Deployment**: Vercel Serverless
- **API**: Clash Royale Official API via RoyaleAPI Proxy

## Project Structure

```
/
├── api/
│   └── index.py          # FastAPI application
├── public/
│   ├── index.html        # Dashboard UI
│   ├── style.css         # Styles
│   └── script.js         # Frontend logic
├── data/
│   └── *.json            # Example API responses
├── vercel.json           # Vercel configuration
└── requirements.txt      # Python dependencies
```

## Community Support

Join the [RoyaleAPI Developer Discord](https://discord.gg/royaleapi) for help!
