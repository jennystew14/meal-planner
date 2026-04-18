# Macro Meal Planner

AI-powered meal planner that syncs with Airtable. Add recipes from URLs, text, or Instagram captions — Claude parses them, matches them to your macros, and generates a weekly plan with a grocery list.

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Add your API keys
Copy `.env.example` to `.env` and fill in your keys:
```bash
cp .env.example .env
```

Open `.env` and add:
```
ANTHROPIC_API_KEY=your_anthropic_key_here
AIRTABLE_TOKEN=your_airtable_token_here
AIRTABLE_BASE_ID=app8eWcW7BHJ4EGxv
JINA_API_KEY=your_jina_key_here
```

> ⚠️ Never share your .env file or commit it to GitHub.

### 3. Make sure your Airtable tables are named exactly:
- `Recipes`
- `Profiles`
- `Weekly Plans`
- `Grocery Lists`

### 4. Run the app
```bash
streamlit run app.py
```

## Features
- **Recipe Library** — Add recipes via URL (Jina scraping), pasted text, or Instagram captions
- **My Profile** — Set daily macro targets, weekly budget, meal prep preferences
- **Weekly Plan** — AI generates a 7-day plan, saves to Airtable automatically
- **Grocery List** — Auto-generated, organized by category with budget tracking

## Deploying to Streamlit Cloud
1. Push to a GitHub repo (make sure `.env` is in `.gitignore`)
2. Go to share.streamlit.io
3. Connect your repo
4. Add your API keys under Settings → Secrets (same format as .env)
