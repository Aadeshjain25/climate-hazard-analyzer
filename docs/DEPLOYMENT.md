# Deployment (all free tiers)

```
Vercel (React static)  ──HTTPS──▶  Render (FastAPI Docker)  ──▶  MongoDB Atlas (M0 free)
                                            │
                                            └──▶ Open-Meteo / Nominatim
```

## 1. MongoDB Atlas (database)
1. Create a free **M0** cluster at https://cloud.mongodb.com.
2. Database Access → add a user with a strong password (role: *readWrite* on `climate_hazards`).
3. Network Access → add `0.0.0.0/0`. Render's free tier has no static IP; the strong password and TLS protect access.
4. Connect → Drivers → copy the `mongodb+srv://…` string. That is your `MONGODB_URI`.

## 2. Render (backend API)
1. Push the repo to GitHub.
2. Render → **New → Blueprint** → pick the repo. It reads `render.yaml` (Docker, `rootDir: backend`, health check `/api/health`).
3. Set the secret env vars when prompted:
   - `MONGODB_URI` = the Atlas string
   - `CORS_ORIGINS` = your Vercel URL, e.g. `https://climate-hazard-analyzer.vercel.app` (no trailing slash)
   - `CONTACT_EMAIL` = your email (sent in the User-Agent, as Nominatim requires)
   - `TRUSTED_PROXY_HOPS=1` is already set (Render sits one proxy in front of the app)
4. Deploy, then open `https://<service>.onrender.com/api/health`. It should return `{"status":"ok","db":true,...}`.

> The free plan sleeps after inactivity, and the first request takes about 30–50 s to wake it. Hit `/api/health` before a demo.

## 3. Vercel (frontend)
1. Vercel → **Add New Project** → import the repo → **Root Directory: `frontend`** (framework auto-detected as Vite).
2. Environment variable: `VITE_API_URL=https://<service>.onrender.com`
3. Deploy. `vercel.json` adds SPA rewrites and security headers.
4. If the Vercel URL differs from what you put in `CORS_ORIGINS`, update it on Render and redeploy.

(Netlify works the same way: base dir `frontend`, build `npm run build`, publish `dist`, plus a `_redirects` file with `/* /index.html 200`.)

## 4. Verify
- Open the site and wait for the default Bengaluru analysis to load. The first run downloads data (10–30 s); a reload is instant (`served from cache`).
- Try a state search ("Karnataka"), a drawn box, the heavy-rainfall hazard, and the PDF/CSV downloads.
- `curl -I "https://<api>/api/analyze?lat=12.97&lon=77.59&start_year=1990&end_year=2020"` should show `x-ratelimit-*` headers.

## Alternative: Google Cloud Run
`gcloud run deploy climate-hazard-api --source backend --allow-unauthenticated --set-env-vars MONGODB_URI=...,CORS_ORIGINS=...,TRUSTED_PROXY_HOPS=1`
