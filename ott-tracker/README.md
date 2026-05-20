# OTT Tracker

Social listening and sentiment analysis dashboard for JioHotstar, Netflix, and Prime Video in India. Pulls Reddit posts, scores them with Claude, tracks Google Trends, and visualises everything in a Streamlit dashboard.

## Install

```bash
pip install -r requirements.txt
```

## Configure environment variables

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
REDDIT_CLIENT_ID=your_client_id_here
REDDIT_CLIENT_SECRET=your_client_secret_here
REDDIT_USER_AGENT=ott-tracker/1.0 by u/your_reddit_username
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

**Reddit credentials** — register a script app at <https://www.reddit.com/prefs/apps>.  
**Anthropic API key** — available at <https://console.anthropic.com/>.

## Initialise the database

Creates `data/tracker.db` with all required tables:

```bash
python database.py
```

## Run the dashboard

```bash
streamlit run app.py
```

Open <http://localhost:8501> in your browser.

Use the sidebar to pull Reddit data, refresh Google Trends, or add manual entries. All four tabs update automatically after each pull.

## Deploy to Streamlit Cloud

### 1 — Push the repo to GitHub

The `.streamlit/config.toml` file is already committed. Do **not** commit `secrets.toml`.

### 2 — Create a new app on Streamlit Cloud

Go to <https://share.streamlit.io> → **New app** → point it at your repo and set the main file to `ott-tracker/app.py`.

### 3 — Add secrets

In the Streamlit Cloud dashboard open **Settings → Secrets** and paste:

```toml
REDDIT_CLIENT_ID = "your_client_id_here"
REDDIT_CLIENT_SECRET = "your_client_secret_here"
REDDIT_USER_AGENT = "ott-tracker/1.0 by u/your_reddit_username"
ANTHROPIC_API_KEY = "your_anthropic_api_key_here"
```

Streamlit Cloud exposes these as environment variables, so the existing `os.environ` calls in the code work without any changes.

### 4 — Set a writable database path

Streamlit Cloud's filesystem is read-only except for `/tmp`. Add this to your secrets:

```toml
DB_PATH = "/tmp/tracker.db"
```

The app reads `DB_PATH` at startup and writes the SQLite database there.

> **Note:** `/tmp` is ephemeral — the database resets on each container restart. For persistent storage, replace SQLite with a hosted database (e.g. Supabase, PlanetScale) and update `database.py` accordingly.

### 5 — Deploy

Click **Deploy**. The app will install `requirements.txt` automatically and be live within a minute.

## Project layout

```
ott-tracker/
├── app.py            # Streamlit dashboard
├── reddit_pull.py    # Reddit data collector (PRAW)
├── trends_pull.py    # Google Trends collector (pytrends)
├── analyzer.py       # Claude API sentiment analysis
├── database.py       # SQLite database layer
├── scheduler.py      # Recurring job scheduler
├── requirements.txt
├── .env.example
└── data/             # SQLite database (gitignored)
```
