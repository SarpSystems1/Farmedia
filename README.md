# Farmedia

Farm-weather and advisory web app: frost risk, a 7-day forecast, supplier search, cost benchmarks
and Sarp AI, a farming advisor. FastAPI backend, Supabase for accounts and data, and a
single-page web UI in `static/`.

## Run it locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then fill in the values (see below)
uvicorn app:app --reload --port 8000
```

Open http://127.0.0.1:8000. The API docs are at `/docs` in development.

Tests (no network, Supabase and Groq are replaced by fakes):

```bash
python -m unittest discover -s tests -t . -v
```

## Configuration

All settings come from environment variables. `.env` is read for local runs; on a hosting platform,
set them in the platform's dashboard. `.env` is git-ignored and must never be committed.

| Variable | Required | Purpose |
| --- | --- | --- |
| `APP_ENV` | yes in production | `production` hides the API docs and adds HSTS. |
| `PORT` | no (default 8000) | Port to listen on. Platforms usually set it. |
| `FORWARDED_ALLOW_IPS` | behind a proxy | Trusted proxy addresses, comma-separated. Needed so the app sees the real client scheme and address. |
| `SUPABASE_URL` | yes | Your project URL, `https://<ref>.supabase.co`. |
| `SUPABASE_ANON_KEY` | yes | The **public** anon key only. The service-role key must never be set here. |
| `GROQ_API_KEY` | for Sarp AI | Without it, Sarp AI answers "not configured" and the rest of the app works. |

## Database (Supabase)

1. In the Supabase SQL editor, run `db/schema.sql`. It is safe to re-run. It creates the tables,
   row-level security policies, the sign-up trigger and the SQL functions, and grants the table
   privileges the app needs.
2. Publish the legal texts. Insert the current Terms and Privacy Policy versions into
   `legal_documents`, one row per document and language, with `is_current = true`:

   ```sql
   insert into public.legal_documents (doc_type, locale, version, url, is_current)
   values ('terms', 'en', '2026-01', 'https://your-site/terms-en', true),
          ('privacy', 'en', '2026-01', 'https://your-site/privacy-en', true);
   ```

   Until these rows exist, the sign-up form is disabled and says so. This is deliberate: nobody
   can accept a document that has not been published.
3. In Authentication > Providers > Email, decide whether email confirmation is required. The app
   handles both: with confirmation on, users are asked to confirm before they sign in.
4. In Authentication > Policies, turn on the leaked-password check. The app's own minimum is 6
   characters.

## Deploy

### Docker

```bash
docker build -t farmedia .
docker run --env-file .env -p 8000:8000 farmedia
```

The image runs as a non-root user, has a health check on `/api/health`, and does not contain
`.env`, tests or git history (see `.dockerignore`).

### Procfile platforms (Heroku-style, Render, Railway)

The `Procfile` starts `uvicorn app:app` on `$PORT`. Set `APP_ENV=production` and the variables
above in the platform dashboard. Put the app behind the platform's HTTPS and let it pass the
forwarded headers through.

## Production checklist

- [ ] `APP_ENV=production` (no `/docs`, HSTS on).
- [ ] HTTPS on the public domain. Redirect HTTP to HTTPS at the proxy.
- [ ] `FORWARDED_ALLOW_IPS` set to the proxy's address, so client addresses are logged correctly.
- [ ] `SUPABASE_ANON_KEY` is the anon key, not the service-role key.
- [ ] `db/schema.sql` run, legal documents published, email confirmation and leaked-password check decided.
- [ ] `GROQ_API_KEY` set if Sarp AI should answer.
- [ ] The retention period for deleted accounts' consent records confirmed with counsel (placeholder: 3 years; the purge job is not built yet).
- [ ] Legal texts in the app (KVKK notice, privacy policy, cookie policy) reviewed by a lawyer and matched to the company details.

## Notes for the hosting team

- The app is stateless except for in-memory caches (supplier and geocoding results). Running several
  instances is safe, but each keeps its own cache.
- Outbound calls: Open-Meteo (weather, geocoding), Nominatim (location lookup), Overpass mirrors
  (supplier search), Groq (Sarp AI), Supabase (accounts and data), cdnjs (Chart.js, loaded in the
  browser only when a chart is shown). Allow outbound HTTPS to these.
- Security headers (Content-Security-Policy, X-Frame-Options, and others) are set by the app.
  If the proxy adds its own CSP, make sure cdnjs is still allowed for scripts.
- Data sent to Groq is subject to a KVKK transfer consent that the user gives at sign-up or in the
  privacy banner. Keep that consent flow intact when changing the Sarp AI integration.

## Layout

```
app.py              FastAPI app: routes, security headers, static files
services/           business logic (weather, suppliers, costs, accounts, Sarp AI, compliance)
static/             web UI (index.html, app.js, i18n.js, style.css)
db/schema.sql       Supabase schema, RLS policies, SQL functions, grants
tests/              offline unit tests
Dockerfile, Procfile, requirements.txt, .env.example
```
