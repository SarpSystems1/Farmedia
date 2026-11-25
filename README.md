# Farmedia

Farm-weather and advisory web app: frost risk, a 7-day forecast, supplier search, cost benchmarks,
and **Sarp AI**, a farming advisor answered by Claude. Plain PHP 8.1+ on MySQL 8, served by Nginx and
PHP-FPM. The web UI is a single page in `php/public/` (vanilla JavaScript, no build step).

> **Status:** this code was written without a PHP or MySQL runtime available, so it has not been
> executed yet. Work through [Verify](#verify) before relying on it.

## Architecture

| Part | Technology |
| --- | --- |
| Web server | Nginx, document root `php/public` |
| Application | PHP 8.1+ (PHP-FPM). No framework, no Composer packages |
| Database | MySQL 8.0+ through PDO, prepared statements only |
| Sarp AI | Claude Messages API, called with PHP cURL (`php/src/SarpAi.php`) |
| Weather | Open-Meteo forecast and geocoding |
| Places | Nominatim (OpenStreetMap) for geocoding, Overpass for suppliers |
| Sessions | Bearer tokens. MySQL stores only SHA-256 hashes of the tokens |

## Layout

```
php/
  public/                  document root
    index.html, static/    the web UI
    api/                   one PHP file per endpoint (see the API table)
  src/                     classes: Accounts, Api, Database, SarpAi, Weather, Crops, Insights, ...
  db/schema_mysql.sql      MySQL schema
  .env.example             PHP and Claude settings
docker/                    nginx.conf, security headers, php.ini, start.sh
Dockerfile, Procfile       deployment
.env.example               settings template (copy to .env)
```

Only `php/public` is reachable from the web. Nginx refuses every other `.php` file and every dotfile.

## Local development

Requirements: PHP 8.1+ with the `pdo_mysql`, `curl` and `openssl` extensions, and MySQL 8.0+.

```bash
# 1. database
mysql -u root -p -e "CREATE DATABASE farmedia CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -u root -p farmedia < php/db/schema_mysql.sql
mysql -u root -p -e "CREATE USER 'farmedia_app'@'localhost' IDENTIFIED BY 'change-me';
  GRANT SELECT, INSERT, UPDATE, DELETE ON farmedia.* TO 'farmedia_app'@'localhost';"

# 2. settings: put the DB_* and CLAUDE_* keys from php/.env.example into a project-root .env

# 3. run
php -S 127.0.0.1:8000 -t php/public
```

Open http://127.0.0.1:8000. The PHP built-in server is for development only. It does not apply the
Nginx rules.

## Database setup

1. Run `php/db/schema_mysql.sql` once on an empty database. It creates `users`, `profiles`, `sessions`,
   `consent_log` and `legal_documents`.
2. Publish the legal texts. Sign-up stays disabled until the current Terms and Privacy Policy exist for
   the language:

   ```sql
   INSERT INTO legal_documents (doc_type, locale, version, url, is_current) VALUES
     ('terms',   'en', '2026-01', 'https://your-site/terms-en',   1),
     ('privacy', 'en', '2026-01', 'https://your-site/privacy-en', 1),
     ('terms',   'tr', '2026-01', 'https://your-site/terms-tr',   1),
     ('privacy', 'tr', '2026-01', 'https://your-site/privacy-tr', 1);
   ```

3. Decide on e-mail confirmation (see `AUTH_REQUIRE_EMAIL_CONFIRMATION`). **Confirmation mail is not sent
   yet.** With the default `true`, nobody can sign in until `users.email_verified_at` is set by hand.

## Configuration

Settings are environment variables. Locally they are read from the project-root `.env`. Real environment
variables take precedence. `.env` is git-ignored and must never be committed.

| Variable | Required | Purpose |
| --- | --- | --- |
| `APP_ENV` | in production | `production` turns on HSTS and the production error handling. |
| `DB_HOST`, `DB_PORT` | no | MySQL host (default `127.0.0.1`) and port (`3306`). |
| `DB_DATABASE`, `DB_USERNAME`, `DB_PASSWORD` | yes | Database, application user and its password. Not the root account. |
| `CLAUDE_API_KEY` | for Sarp AI | Without it, Sarp AI answers "not configured". |
| `CLAUDE_API_BASE_URL` | no | Default `https://api.onysoft.com/v1`. Must be HTTPS. |
| `CLAUDE_MODEL` | no | Default `claude-sonnet-5-5`. |
| `AUTH_REQUIRE_EMAIL_CONFIRMATION` | no | Default `true`. Set `false` until confirmation mail exists. |
| `PORT` | containers | Port Nginx listens on (default 8080). |

## API

Every endpoint returns JSON. Errors look like `{"error": {"code", "status", "message", "detail"}}`.
`?lang=en` gives English messages; Turkish is the default.

| Endpoint | Method | Sign-in | Purpose |
| --- | --- | --- | --- |
| `/api/health.php` | GET | no | Health check. |
| `/api/legal/requirements.php` | GET | no | Consents a country needs and the current document versions. |
| `/api/auth/register.php` | POST | no | Create an account with the required consents. |
| `/api/auth/login.php` | POST | no | E-mail and password. Returns a session. |
| `/api/auth/refresh.php` | POST | no | Rotate the refresh token. The old one stops working. |
| `/api/auth/logout.php` | POST, GET | bearer | End this device's session. |
| `/api/auth/me.php` | GET | bearer | The user and their profile. |
| `/api/profile.php` | GET, PATCH, POST | bearer | Read or partially update the profile and consents. |
| `/api/profile/export.php` | GET | bearer | Download the user's data as JSON. |
| `/api/account.php` | DELETE | bearer | Delete the account. Needs the password again. |
| `/api/account.php` | POST | bearer | `{"action": "sign_out_everywhere"}`. |
| `/api/dashboard.php` | GET, POST | bearer | Forecast, recommendations and warnings, parsed crops. |
| `/api/geocode.php` | GET | bearer | Place name to coordinates, limited to the country. |
| `/api/market.php` | GET | bearer | Nearby suppliers, map search links, cost benchmarks. |
| `/api/parse-crops.php` | POST | bearer | Free-text crop list to structured crops. |
| `/api/sarp-ai.php` | POST | bearer | Sarp AI answer from Claude. |

Send a bearer token as `Authorization: Bearer <access_token>`. Access tokens last one hour. Refresh
tokens last 30 days and rotate on every use.

Account operations take the user id from the bearer token, never from the request body.

## Deployment

### Docker (Nginx and PHP-FPM in one container)

```bash
docker build -t farmedia .
docker run --env-file .env -p 8080:8080 farmedia
```

The image runs `docker/start.sh`. It writes the Nginx configuration for `$PORT`, starts PHP-FPM, and then
runs Nginx in the foreground. The image does not contain `.env`.

### Procfile platforms

`Procfile`: `web: sh docker/start.sh`. The host must provide `nginx` and `php-fpm`, with PHP 8.1+ and the
`pdo_mysql` and `curl` extensions. Serve the app behind the platform's HTTPS, and redirect HTTP to HTTPS.

## Production checklist

- [ ] `APP_ENV=production`.
- [ ] HTTPS on the public domain, with HTTP redirected. Nginx sends HSTS.
- [ ] `DB_USERNAME` is an application user with SELECT, INSERT, UPDATE and DELETE only.
- [ ] `schema_mysql.sql` applied, and the current legal documents published in both languages.
- [ ] `AUTH_REQUIRE_EMAIL_CONFIRMATION` decided (`false` until confirmation mail exists).
- [ ] `CLAUDE_API_KEY` set if Sarp AI should answer. Never commit it.
- [ ] Retention period for deleted accounts' consent records confirmed with counsel (placeholder: 3 years; the purge job is not built).
- [ ] Legal texts and the consent rules in `php/src/Compliance.php` reviewed by a lawyer.

## Known gaps

- **Not verified by execution.** No PHP or MySQL runtime was available when this was written. Run `php -l`
  on each file under `php/`, apply the schema, and exercise every endpoint.
- **No automated tests.** The earlier Python test suite was removed along with the Python code.
- **Confirmation mail is not sent** (see Database setup).
- **No rate limiting** on sign-in or registration.
- **No caching** for Nominatim and Overpass. Nominatim allows at most one request per second, so add a
  shared cache table before running this at scale.
- **Claude gateway.** The default base URL and the Messages request format are assumed, not checked. If
  the gateway differs, change only `php/src/SarpAi.php`.
- **Frost in Sarp AI's context** is a simplified check (`php/src/Weather.php`). The dashboard uses the full
  model in `php/src/Frost.php`.
- **Refresh-token reuse** is refused, but it does not revoke the session.

## Legal notice

The compliance mapping in `php/src/Compliance.php` (KVKK, GDPR, CCPA) is an engineering reading of public
rules. It is not legal advice. Counsel must approve the wording of the documents and the final consent set.
