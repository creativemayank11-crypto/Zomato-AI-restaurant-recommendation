# Deployment Plan — Backend on Railway, Frontend on Vercel

This plan deploys the AI restaurant recommender in two pieces:

| Piece | What it is | Where it goes |
|---|---|---|
| **Backend** | FastAPI app (`app.py`): `/health`, `/api/v1/meta/options`, `/api/v1/recommend`, plus the Parquet dataset and the Groq LLM client | **Railway** |
| **Frontend** | Static files in `frontend/` (`index.html`, `app.js`, `style.css`) | **Vercel** |

---

## 1. Target architecture

```
Browser ──► https://<app>.vercel.app            (static: index.html, app.js, style.css)
              │
              │  Vercel rewrites (server-side proxy, same origin for the browser)
              │    /api/*   ──►  https://<api>.up.railway.app/api/*
              │    /health  ──►  https://<api>.up.railway.app/health
              ▼
         Railway: uvicorn app:app  ──►  Groq API
                      │
                      └── data/processed/zomato_clean.parquet (loaded into memory at startup)
```

**Why proxy through Vercel rewrites instead of calling Railway directly from the browser?**

- `frontend/app.js` calls **relative** URLs (`/health`, `/api/v1/...`). With rewrites, those keep working unchanged, so the frontend needs no code change and no build step.
- The browser only ever talks to the Vercel domain, so there are **no CORS issues**.
- The Railway URL can change (e.g. a custom domain later) by editing a single file (`frontend/vercel.json`).

---

## 2. Pre-deployment code changes (do these first, in the repo)

Each of these is required unless marked *optional*. All of them are small.

> **Status (2026-11-14):** §2.1–2.7 are **applied and committed** (commit `78d69ae`) and verified locally (79 tests pass; the app boots from a fresh runtime-only install with Railway's start command; CORS accepts only `ALLOWED_ORIGINS`). §2.9 is **done**: the commit is on `main` of `creativemayank11-crypto/Zomato-AI-restaurant-recommendation` (local remote name: `recommender`). §2.8 (optional polish) is now **applied** too (Tailwind precompiled, branding renamed, rate limiting added; 86 tests pass). The only remaining code edit is replacing the placeholder `RAILWAY_DOMAIN_HERE` in `frontend/vercel.json` once the Railway domain exists (§3.4).

### 2.1 Ship the dataset with the backend — **required**

The app loads `data/processed/zomato_clean.parquet` at startup and **crashes if it is missing** (`load_processed_data` raises `FileNotFoundError`). That file is currently git-ignored, so Railway would never receive it.

The processed file is only **~366 KB**, so commit it. (The 574 MB raw CSV must stay ignored.)

In `.gitignore`, under the "Large Data Files" block, add the exception line:

```gitignore
data/processed/*.parquet
!data/processed/zomato_clean.parquet
```

Then:

```bash
git add -f data/processed/zomato_clean.parquet
```

> Alternative (not recommended): run `python scripts/run_etl.py` during the Railway build. It downloads the full raw dataset from Hugging Face on every deploy — slow, and it adds the heavy `datasets` dependency to the image.

### 2.2 Split runtime vs. dev dependencies — **strongly recommended**

`requirements.txt` currently includes `streamlit`, `datasets`, `pytest`, `google-generativeai`, `duckdb` (unused), etc. Railway installs everything in `requirements.txt`, which makes builds slow and the image large. The backend only imports: `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `python-dotenv`, `pandas`, `numpy`, `pyarrow`, `tenacity`, `groq` (and `openai` / `google-genai` only if you switch provider).

Recommended layout:

**`requirements.txt`** (what Railway installs):

```text
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
pydantic>=2.0.0
pydantic-settings>=2.0.0
python-dotenv>=1.0.0
pandas>=2.0.0
numpy>=1.26.0
pyarrow>=14.0.0
tenacity>=8.2.0
groq>=0.9.0
# Only needed if DEFAULT_LLM_PROVIDER is switched away from groq:
# openai>=1.12.0
# google-genai>=0.1.0
```

**`requirements-dev.txt`** (local development, tests, ETL, Streamlit):

```text
-r requirements.txt
openai>=1.12.0
google-genai>=0.1.0
google-generativeai>=0.5.0
datasets>=2.18.0
duckdb>=0.9.0
streamlit>=1.32.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
httpx>=0.27.0
```

Local setup then becomes `pip install -r requirements-dev.txt`. Run the test suite afterwards to confirm nothing is missing.

### 2.3 Pin the Python version — **required**

Create `.python-version` in the repo root containing:

```text
3.12
```

(Local development uses Python 3.12.10; Railway's builder reads this file.)

### 2.4 Railway start command and health check — **required**

Create `railway.json` in the repo root:

```json
{
  "$schema": "https://railway.com/railway.schema.json",
  "deploy": {
    "startCommand": "uvicorn app:app --host 0.0.0.0 --port $PORT",
    "healthcheckPath": "/health",
    "healthcheckTimeout": 60,
    "restartPolicyType": "ON_FAILURE"
  }
}
```

Notes:
- Railway injects `PORT`; the app must bind to it. The `API_HOST` / `API_PORT` settings in `config/settings.py` are **not** used by the uvicorn CLI, so no change is needed there.
- `/health` returns `"status": "healthy"` once the dataset is loaded, so it is a good readiness check.

### 2.5 Lock down CORS — **recommended**

`app.py` currently allows every origin (`allow_origins=["*"]`). With the Vercel proxy, the browser never calls Railway directly, so CORS can be restricted.

1. In `config/settings.py`, add:

   ```python
   # Comma-separated list of allowed browser origins, e.g. "https://my-app.vercel.app"
   ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "*")
   ```

2. In `app.py`, replace `allow_origins=["*"]` with:

   ```python
   allow_origins=[o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()],
   ```

3. Set `ALLOWED_ORIGINS` on Railway to the Vercel production domain (see §3.3). Local development keeps the `*` default.

### 2.6 Vercel config for the frontend — **required**

`index.html` loads `/static/style.css` and `/static/app.js` (the FastAPI backend serves the `frontend/` folder under `/static`). On Vercel those files live at the site root, so add a rewrite for `/static/*`, plus the API proxy rules.

Create `frontend/vercel.json`:

```json
{
  "rewrites": [
    { "source": "/static/:path*", "destination": "/:path*" },
    { "source": "/api/:path*", "destination": "https://<RAILWAY_DOMAIN>/api/:path*" },
    { "source": "/health", "destination": "https://<RAILWAY_DOMAIN>/health" }
  ],
  "headers": [
    {
      "source": "/(.*)",
      "headers": [
        { "key": "X-Content-Type-Options", "value": "nosniff" },
        { "key": "Referrer-Policy", "value": "strict-origin-when-cross-origin" }
      ]
    }
  ]
}
```

Replace `<RAILWAY_DOMAIN>` (in the committed file: `RAILWAY_DOMAIN_HERE`) with the domain from §3.4 (e.g. `zomato-api-production.up.railway.app`) — so the backend must be deployed first.

With this setup the same `index.html` works both locally (served by FastAPI) and on Vercel.

### 2.7 Keep non-web files out of the Vercel deploy — **required**

`frontend/` also contains `streamlit_app.py` (a separate Python app) and `legacy/` (backup of the old UI). Neither should be published.

Create `frontend/.vercelignore`:

```text
streamlit_app.py
legacy/
__pycache__/
```

(Or delete `frontend/legacy/` once the new UI is confirmed.)

### 2.8 Pre-launch polish — *optional* (applied)

- **Tailwind precompiled:** the CDN script is gone. Utilities are compiled into `frontend/tailwind.css` (~27 KB, committed) by the tooling in `tools/tailwind/`. Vercel needs no build step. **After changing Tailwind classes in `index.html` or `app.js`, rebuild:**

  ```bash
  cd tools/tailwind && npm install && npm run build
  ```

  The tooling lives in `tools/tailwind/` (not the repo root) so Railway doesn't detect a `package.json` and build the backend as a Node app.
- **Branding:** "Doom" / "Latveria" renamed to **Sovereign AI Concierge**; CSS tokens are now `--brand-*`.
- **Rate limiting:** `/api/v1/recommend` is limited per client IP with an in-memory sliding window (`src/api/rate_limit.py`, no extra dependency). Over the limit it returns HTTP 429 with a `Retry-After` header, and the UI shows the message. Configure with `RATE_LIMIT_PER_MINUTE` (default 20, `0` disables). Caveats: limits are per Railway replica, and the client IP comes from `X-Forwarded-For`, so this is cost protection rather than a security boundary — also set a spend limit in the Groq console.

### 2.9 Commit and push

The working tree currently has many uncommitted changes (bug fixes, the new UI, and the changes above). Before deploying:

```bash
python -m pytest -q
```

```bash
git add -A
```

```bash
git commit -m "Prepare for Railway + Vercel deployment"
```

```bash
git push recommender deploy-railway-vercel:main
```

(`recommender` is the remote for `https://github.com/creativemayank11-crypto/Zomato-AI-restaurant-recommendation.git`, the repo Railway and Vercel deploy from.)

Confirm `.env` is **not** in the commit (`git status` should not list it — it is git-ignored). The Groq key must only ever live in Railway's variables.

---

## 3. Deploy the backend to Railway

### 3.1 Create the service

1. Railway dashboard → **New Project** → **Deploy from GitHub repo** → select the project repository.
2. Root directory: the repo root (the folder containing `app.py`).
3. Railway detects Python from `requirements.txt` + `.python-version` and uses `railway.json` for the start command and health check.

### 3.2 Set environment variables

Service → **Variables**. Use `.env.example` as the reference; values below match the current working local config.

| Variable | Value | Notes |
|---|---|---|
| `DEFAULT_LLM_PROVIDER` | `groq` | |
| `GROQ_API_KEY` | *(your key)* | Secret. Paste directly into Railway, never commit. |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | |
| `GROQ_REASONING_FORMAT` | `hidden` | |
| `GROQ_REASONING_EFFORT` | `low` | |
| `TEMPERATURE` | `0.2` | |
| `MAX_OUTPUT_TOKENS` | `1024` | Lower values truncate the AI reply (see earlier fix). |
| `LOG_LEVEL` | `INFO` | |
| `DEBUG` | `False` | |
| `ALLOWED_ORIGINS` | `https://<your-app>.vercel.app` | Only if §2.5 was applied. Fill in after the Vercel deploy. |
| `RATE_LIMIT_PER_MINUTE` | `20` | Per-IP limit on `/api/v1/recommend`; `0` disables. |

Do **not** set `PORT` (Railway provides it). `RAW_DATA_PATH` / `PROCESSED_DATA_PATH` can stay at their defaults.

If `GROQ_API_KEY` is missing, the app still starts but runs in deterministic (no-AI) mode — check the startup log for `Groq client initialised`.

### 3.3 Region and sizing

- Pick a region close to your users.
- The dataset is small (~12k rows in memory), so the smallest instance size is enough to start.

### 3.4 Expose it

Service → **Settings → Networking → Generate Domain**. Note the domain (e.g. `xxxx.up.railway.app`) — it goes into `frontend/vercel.json`.

### 3.5 Verify the backend

```bash
curl https://<RAILWAY_DOMAIN>/health
```

Expected: `"status":"healthy"`, `"dataset_loaded":true`, `"total_restaurants":12137`, `"llm_provider":"groq"`.

```bash
curl -X POST https://<RAILWAY_DOMAIN>/api/v1/recommend -H "Content-Type: application/json" -d "{\"location\":\"Indiranagar\",\"max_recommendations\":3,\"additional_notes\":\"cozy date night\"}"
```

Expected: HTTP 200 with 3 recommendations whose reasons are AI-written (not the generic "is a top-rated choice (4.7★, N votes)" fallback text). Also check the Railway logs for `Groq token usage` lines.

---

## 4. Deploy the frontend to Vercel

1. Put the real Railway domain into `frontend/vercel.json` (§2.6), commit, push.
2. Vercel dashboard → **Add New → Project** → import the same GitHub repo.
3. Project settings:
   - **Root Directory:** `frontend`
   - **Framework Preset:** `Other`
   - **Build Command:** *(leave empty)*
   - **Output Directory:** `.` (or leave default)
   - **Install Command:** *(leave empty)*
4. Deploy. Vercel serves `index.html` at `/` and applies the rewrites.
5. If §2.5 was applied, copy the production Vercel URL into Railway's `ALLOWED_ORIGINS` and redeploy the backend.

---

## 5. End-to-end verification checklist

On the Vercel URL, in a normal browser:

- [ ] Page loads with styles (no unstyled HTML) — confirms `/static/*` rewrite and Tailwind.
- [ ] Header shows **12,137** venues and the provider badge — confirms `/health` proxy.
- [ ] Locality dropdown lists ~94 localities and cuisine chips appear — confirms `/api/v1/meta/options` proxy.
- [ ] Click each of the 3 presets → 5 result cards with AI rationales.
- [ ] Manual search with "Top 3" works.
- [ ] A strict search (e.g. Kengeri, rating 4.8+, high budget) shows the amber "Search criteria relaxed" banner.
- [ ] Phone width (DevTools device mode, 375px): no sideways scroll, button reachable.
- [ ] Browser DevTools → Network: all requests go to the Vercel domain, no CORS errors in Console.
- [ ] Railway logs show the requests and `Groq token usage` lines.

---

## 6. Operations

| Task | How |
|---|---|
| Redeploy after code changes | Push to `main` — both Railway and Vercel auto-deploy from GitHub. |
| Roll back the backend | Railway → Deployments → pick a previous deployment → Redeploy. |
| Roll back the frontend | Vercel → Deployments → previous deployment → Promote / Instant Rollback. |
| Logs | Railway service → Deployments → Logs (look for `Recommend:` and `Groq token usage`). |
| Rotate the Groq key | Create a new key in the Groq console → update `GROQ_API_KEY` on Railway → redeploy → revoke the old key. |
| Update the dataset | Run `python scripts/run_etl.py` locally, run tests, commit the new `zomato_clean.parquet`, push. |
| Change frontend styling | Edit classes in `frontend/index.html` / `app.js`, run `npm run build` in `tools/tailwind/`, commit `frontend/tailwind.css`. |
| Custom domain | Add it in Vercel (frontend). The backend can keep its Railway domain since the browser never sees it. |

### Things to watch

- **Cold starts / restarts:** startup loads the dataset and initialises the Groq client (~2–4 s locally). The health check covers this.
- **LLM latency:** a recommendation normally takes ~1–2 s. If Groq fails, the backend retries up to 3 times and then falls back to deterministic picks (still HTTP 200), so slow requests can take longer. If you see proxy timeouts on Vercel, check Vercel's limits for external rewrites on your plan.
- **Groq usage/costs:** each recommendation is one Groq call (~700 prompt + ~450 completion tokens at 5 picks). Watch usage in the Groq console, especially once the URL is public.

---

## 7. Summary of new / changed files

| File | Change |
|---|---|
| `.gitignore` | Un-ignore `data/processed/zomato_clean.parquet` |
| `data/processed/zomato_clean.parquet` | Committed (~366 KB) |
| `requirements.txt` | Runtime-only dependencies |
| `requirements-dev.txt` | New — dev, test, ETL and Streamlit dependencies |
| `.python-version` | New — `3.12` |
| `railway.json` | New — start command + health check |
| `config/settings.py`, `app.py` | `ALLOWED_ORIGINS` for CORS (recommended) |
| `frontend/vercel.json` | New — `/static`, `/api`, `/health` rewrites |
| `frontend/.vercelignore` | New — exclude `streamlit_app.py`, `legacy/` |
| `frontend/tailwind.css`, `tools/tailwind/*` | New — precompiled Tailwind + build tooling (§2.8) |
| `frontend/index.html`, `app.js`, `style.css` | Branding renamed; CDN script replaced by `tailwind.css` (§2.8) |
| `src/api/rate_limit.py`, `src/api/routes.py`, `config/settings.py` | Per-IP rate limit on `/api/v1/recommend` (§2.8) |
| `tests/conftest.py`, `tests/test_rate_limit.py` | New — limiter reset fixture + rate-limit tests |
