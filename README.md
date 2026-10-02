**Live demo:** https://contentcreatorsapp.onrender.com
# Vago — AI Content Studio for Brands & Creators

Flask + SQLite + vanilla JS web app with Gemini integration. No Streamlit. Ships with sample data (brand *Aaraa Millets*, 3 campaigns, 7 pieces).

## Windows + VS Code setup
1. Install **Python 3.10+** (tick *Add Python to PATH*) and VS Code (Python extension).
2. Open the `vago` folder in VS Code → **Terminal → New Terminal** (PowerShell/CMD) and run:
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```
   (PowerShell blocks activation? run `Set-ExecutionPolicy -Scope Process Bypass` first. Or just double-click `run.bat`.)
3. Open **http://127.0.0.1:5000**. The SQLite DB and sample data are created automatically on first start (`data/vago.db`; delete it to reset).

## Enabling live AI
Get a key at https://aistudio.google.com/apikey → put it in `.env`: `GEMINI_API_KEY=...` → restart. The badge in the top bar changes from **Demo mode** to **Live · model**.
Image generation (optional): set `ENABLE_IMAGE_GEN=true` (uses `IMAGE_MODEL`, default `gemini-2.5-flash-image`). Without it, Visual Studio still writes detailed prompts.

## Demo mode (no key) — what is real vs. not
Demo output is **template/heuristic**, labelled *Demo template* everywhere, and never presented as AI. Live-Gemini failures show an error; they never fall back silently.

| # | Feature | Where | No key | Needs Gemini |
|---|---|---|---|---|
|1|Brief Intelligence|Brief & Generate|keyword heuristics|full analysis|
|2|Multi-format generator|Brief & Generate|templates|real copy|
|3|Brand Voice Memory|Brand Voice|✅ stored & applied|—|
|4|Platform adaptation|Content → Adapt|rule-based reshaping|smart adaptation|
|5|Refinement|Content → Refine|shorter/punchier/CTA/emoji|any instruction|
|6|Quality analyzer|Content → Insights|✅ 7 explainable metrics|+ AI critique|
|7|Campaign ideas|Idea Lab|templates|original ideas|
|8|Multilingual|Content → Adapt|❌|✅ translation|
|9|Content calendar|Calendar|scheduling of existing pieces; editable|AI story-arc plan|
|10|Visual generator|Visual Studio|prompt templates|AI prompts (+ images with `ENABLE_IMAGE_GEN`)|
|11|Audience personas|Audiences|templates|grounded personas|
|12|SEO assistant|Content → Insights|✅ checks & keyword density|+ title/meta suggestions|
|13|Duplicate checker|Content → Insights|✅ shingle + cosine similarity|—|
|14|Campaign comparison|Compare|✅ metrics & winners|—|
|15|Feedback learning|Feedback / Brand Voice|✅ tags → learned rules injected into prompts|—|
|16|AI chat editor|Content → AI chat|simple commands|free-form|
|17|Content history|Library|✅ search, filter, versions, restore, export|—|
|18|Approval workflow|Approval tab / board|✅ draft→review→approved→ready, audit log|—|

Workflow rules: reviewer name required; notes required for reject/changes; only *approved* items can be marked ready and only above a quality threshold; editing an approved item resets it to Draft.

## Project layout
`app.py` routes & validation · `ai.py` Gemini client + demo fallbacks · `services.py` scoring, duplicates, SEO, compare, workflow · `db.py` SQLite · `seed.py` sample data · `templates/`, `static/` UI · `tests/` (`python -m unittest discover tests`).

## Security notes
API key only via environment (`.env` is git-ignored, never sent to the browser). All user text is HTML-escaped in the UI, SQL is parameterised, request size and field lengths are capped. Run locally (binds to 127.0.0.1); use a production WSGI server before exposing publicly.
