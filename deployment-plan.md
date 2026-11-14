# Deployment Plan — Vercel (frontend + backend)

**Status (2026-11-14): live** at **https://zomato-ai-restaurant-recommendation-bay.vercel.app/**

The whole app — FastAPI backend and the static frontend — runs on **Vercel** from the GitHub repo
`creativemayank11-crypto/Zomato-AI-restaurant-recommendation` (branch `main`).

> **What changed from the original plan:** the plan was *backend on Railway, frontend on Vercel*. The Railway deploy failed before building, and when the repo was imported into Vercel with the **repo root** as the root directory, Vercel detected the FastAPI app (`app.py`) and runs it as a Python function. That serves the API *and* the frontend (FastAPI already serves `frontend/` under `/static` and `index.html` at `/`), so Railway is not needed. The Railway-specific files are kept for reference — see §7.

---

## 1. Architecture (as deployed)

```
Browser ──► https://zomato-ai-restaurant-recommendation-bay.vercel.app
              │
              ▼
         Vercel Python function: FastAPI app (app.py)
              ├── GET  /                      → frontend/index.html
              ├── GET  /static/*              → frontend/ (tailwind.css, style.css, app.js)
              ├── GET  /health                → health + dataset status
              ├── GET  /api/v1/meta/options   → localities, cuisines
              ├── POST /api/v1/recommend      → filter → Groq LLM → grounding check
              └── GET  /docs                  → Swagger UI
                       │
                       ├── data/processed/zomato_clean.parquet (committed, loaded at cold start)
                       └── Groq API (GROQ_API_KEY from Vercel env vars)
```

- Single origin: the browser only talks to the Vercel domain, so there are no CORS issues and `frontend/app.js` keeps using relative URLs.
- `requirements.txt` holds only runtime dependencies, which keeps the function bundle small.

---

## 2. Verified on the live site (2026-11-14)

| Check | Result |
|---|---|
| `/` page loads with the Sovereign AI Concierge design | ✅ |
| `/static/tailwind.css`, `style.css`, `app.js` | ✅ 200 |
| `/health` | ✅ `healthy`, `dataset_loaded: true`, 12,137 restaurants, provider `groq` |
| `/api/v1/meta/options` | ✅ 94 localities, cuisines load in the UI |
| `POST /api/v1/recommend` (Indiranagar, 3 picks) | ✅ HTTP 200 in ~2.5 s, AI-written reasons (Groq key works) |
| "Romantic Date Night" preset in the browser | ✅ 5 cards, ~1 s, no console errors |
| `/.env` | ✅ 404 (not exposed) |

---

## 3. Vercel project settings

| Setting | Value |
|---|---|
| Git repository | `creativemayank11-crypto/Zomato-AI-restaurant-recommendation`, branch `main` |
| Root Directory | repo root (`./`) — **not** `frontend` |
| Framework | detected automatically (FastAPI / Python) |
| Build / Install / Output commands | defaults |

### Environment variables (Vercel → Project → Settings → Environment Variables)

| Variable | Value | Notes |
|---|---|---|
| `GROQ_API_KEY` | *(your key)* | **Set.** Secret — only ever in Vercel, never committed. |
| `DEFAULT_LLM_PROVIDER` | `groq` | Optional; this is the code default. |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Optional; code default. |
| `MAX_OUTPUT_TOKENS` | `1024` | Optional; code default. Lower values truncate the AI reply. |
| `RATE_LIMIT_PER_MINUTE` | `20` | Optional; code default. See caveat in §5. |
| `LOG_LEVEL` | `INFO` | Optional. |
| `ALLOWED_ORIGINS` | *(leave unset)* | Not needed: frontend and API share one origin. |

After changing a variable, redeploy (Vercel → Deployments → ⋯ → Redeploy) for it to take effect.

---

## 4. Day-to-day operations

| Task | How |
|---|---|
| Deploy a change | Push to `main` on the GitHub repo — Vercel redeploys automatically. From this machine: `git push recommender deploy-railway-vercel:main` |
| Preview a change | Push any other branch — Vercel builds a preview URL for it. |
| Roll back | Vercel → Deployments → previous deployment → **Promote** / Instant Rollback. |
| Logs | Vercel → Project → **Logs** (look for `Recommend:` and `Groq token usage` lines). |
| Rotate the Groq key | New key in the Groq console → update `GROQ_API_KEY` in Vercel → redeploy → revoke the old key. |
| Update the dataset | `python scripts/run_etl.py` locally → run tests → commit `data/processed/zomato_clean.parquet` → push. |
| Change frontend styling | Edit classes in `frontend/index.html` / `app.js` → `cd tools/tailwind && npm install && npm run build` → commit `frontend/tailwind.css` → push. |
| Run locally | `.venv/Scripts/python -m uvicorn app:app --port 8000` → http://localhost:8000 |
| Custom domain | Vercel → Project → Settings → Domains. |

---

## 5. Caveats of running on Vercel (serverless)

- **Rate limiting is per function instance.** The limiter in `src/api/rate_limit.py` keeps counts in memory; Vercel may run several instances and recycle them at any time, each with its own counter. Treat it as a speed bump. **Set a monthly spend limit in the Groq console** as the real cost guard.
- **Cold starts.** After a quiet period the first request starts the function, imports pandas/pyarrow and loads the dataset — expect a few extra seconds on that request.
- **Function duration.** A recommendation normally takes ~1–3 s. If Groq is slow or failing, the backend retries up to 3 times before falling back to deterministic picks, which can take longer. If you see timeouts, raise the function's max duration in the Vercel project settings (limits depend on your plan).
- **Bundle size.** pandas + numpy + pyarrow are large. Keep dev-only packages in `requirements-dev.txt`, not `requirements.txt`, or the function may exceed Vercel's size limit.

---

## 6. Optional clean-ups

1. ~~**Extra files served under `/static`.**~~ **Done.** `app.py` now serves only `app.js`, `style.css` and `tailwind.css` under `/static`; everything else (e.g. `streamlit_app.py`, `vercel.json`) returns 404, covered by a test. The old-UI backup `frontend/legacy/` was deleted (still in git history, commit `78d69ae`).
2. **Unused Railway / split-deploy files.** `railway.json`, `frontend/vercel.json` (still contains the placeholder `RAILWAY_DOMAIN_HERE`) and `frontend/.vercelignore` are not used by this setup. Delete them, or keep them if you might switch to Railway later (§7).
3. **Failed Railway project.** Delete it in the Railway dashboard if you won't use it, so it doesn't retry builds.
4. **Groq spend limit.** Set one in the Groq console (see §5).

---

## 7. Alternative: backend on Railway, frontend-only on Vercel

Kept for reference; this was the original plan and the repo still contains its config.

- **Railway** (backend): deploy the repo root; `railway.json` sets `uvicorn app:app --host 0.0.0.0 --port $PORT` and the `/health` check; `.python-version` pins 3.12. Set the same environment variables as §3, plus `ALLOWED_ORIGINS=https://<your-vercel-domain>`. Generate a domain under Settings → Networking.
- **Vercel** (frontend only): set **Root Directory = `frontend`**, framework *Other*, no build. Replace `RAILWAY_DOMAIN_HERE` in `frontend/vercel.json` with the Railway domain — it rewrites `/static/*` to the site root and proxies `/api/*` and `/health` to Railway. `frontend/.vercelignore` keeps `streamlit_app.py` out of that deploy.
- Why you might switch: a long-running server keeps the dataset warm (no cold starts) and makes the in-memory rate limit meaningful.
- Status of the attempt on 2026-11-14: the Railway deployment failed before building (empty build log); the cause was not diagnosed. The CLI login (`railway login`, including `--browserless`) also never completed on this machine.

---

## 8. Pre-deployment changes already made (for the record)

| Change | Files |
|---|---|
| Processed dataset committed (~366 KB) so the app can start in the cloud | `.gitignore`, `data/processed/zomato_clean.parquet` |
| Runtime vs dev dependencies split | `requirements.txt`, `requirements-dev.txt` |
| Python pinned to 3.12 | `.python-version` |
| Configurable CORS | `ALLOWED_ORIGINS` in `config/settings.py`, `app.py` |
| Precompiled Tailwind (no CDN) + build tooling | `frontend/tailwind.css`, `tools/tailwind/` |
| Branding renamed to "Sovereign AI Concierge" | `frontend/index.html`, `app.js`, `style.css` |
| Per-IP rate limit on `/api/v1/recommend` | `src/api/rate_limit.py`, `src/api/routes.py`, `RATE_LIMIT_PER_MINUTE` |
| Railway / split-Vercel config (see §7) | `railway.json`, `frontend/vercel.json`, `frontend/.vercelignore` |
