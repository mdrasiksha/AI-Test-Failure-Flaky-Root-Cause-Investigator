# Deployment

## Render deployment

The repository includes a Render Blueprint at `../render.yaml`. Connect the
repository in Render and apply that Blueprint, or create a **Web Service** with
these exact settings:

| Render setting | Value |
| --- | --- |
| Runtime | `Python` |
| Root Directory | `flaky-test-analyzer` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/health` |

The start command intentionally uses Render's `PORT` environment variable; do
not replace it with a hard-coded port. `.python-version` selects Python 3.12.9.
After deployment, `GET /health` should return only the basic service status.

### Render environment variables

Set secrets through the Render dashboard, never in `render.yaml` or source
control.

| Variable | Required? | Recommended Render value | Purpose |
| --- | --- | --- | --- |
| `APP_ENV` | Required | `production` | Enables production behavior, including `Secure` anonymous-session cookies. |
| `ANALYTICS_ENABLED` | Required | `true` | Enables privacy-first, aggregate product analytics and anonymous feedback. Set `false` if analytics must be disabled. |
| `ANALYTICS_RETENTION_DAYS` | Required when analytics is enabled | `30` | Retention window for analytics and feedback. |
| `ANONYMOUS_SESSION_DAYS` | Required when analytics is enabled | `30` | Anonymous cookie lifetime. |
| `ADMIN_METRICS_TOKEN` | Optional | Generate a long random secret in Render | Enables `/internal/metrics`; when unset, that endpoint returns 404. Supply it only in the `X-Admin-Token` header. |
| `OPENAI_API_KEY` | Optional | Add as a Render secret | Enables optional OpenAI analysis. Deterministic analysis works without it. |
| `OPENAI_MODEL` | Optional | `gpt-5-mini` | Model used for optional OpenAI analysis. |

Render supplies `PORT`; it should not be configured manually. Additional
optional tuning variables are `MAX_UPLOAD_MB` (default `10`),
`MAX_TRACE_UPLOAD_MB` (default `50`), `MAX_AI_TESTS_PER_REQUEST` (default `5`),
and `AI_MAX_TEXT_CHARS` (default `12000`). Invalid numeric settings fall back
to safe defaults.

### SQLite durability for this MVP

Analytics use SQLite at `data/analytics.db` by default. **Render's default
filesystem is ephemeral, so this analytics database is temporary and can be
lost on a restart, redeploy, or instance replacement.** This initial deployment
does not claim durable analytics and does not migrate to Postgres.

Database creation, event recording, cleanup, and metrics failures are isolated
from test analysis. If the database path is unavailable or its data disappears,
the service still starts and JUnit/Playwright analysis continues; analytics and
feedback may be unavailable until writable storage is available.

JUnit XML and Playwright `trace.zip` uploads are bounded and processed through
in-memory bytes (framework upload spools are always closed). They are not
intentionally saved after analysis and do not rely on Render storage.

## Security checks

- Production anonymous-session cookies are `Secure`, `HttpOnly`, and
  `SameSite=Lax`.
- `GET /health` reports only `status` and the public service name; it does not
  expose environment values, API keys, tokens, or database details.
- `GET /internal/metrics` is unavailable unless `ADMIN_METRICS_TOKEN` is set and
  requires the matching value in the `X-Admin-Token` request header.
- `.env` files are excluded from Git and the Docker build context.

## Local production-equivalent start

From `flaky-test-analyzer/`:

```bash
python -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
export APP_ENV=production PORT=8000
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

For local development, copy `.env.example` to `.env`. Do not commit that file.

## Docker (optional)

```bash
docker build -t flaky-test-analyzer .
docker run --rm -p 8000:8000 \
  -e APP_ENV=production -e PORT=8000 \
  flaky-test-analyzer
```

Pass optional secrets at runtime through a secret manager or environment
variables; never bake them into the image.
