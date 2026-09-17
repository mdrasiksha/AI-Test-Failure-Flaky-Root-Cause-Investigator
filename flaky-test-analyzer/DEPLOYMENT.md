# Deployment

The application is stateless: JUnit XML and trace ZIP uploads are bounded, parsed
in memory, and closed after success or failure. It does not require a database.

## Configuration

Copy `.env.example` to `.env` for local development. `.env` is Git-ignored and
Docker-ignored. Set secrets through the deployment platform rather than baking
them into an image.

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `development` | Deployment environment label. |
| `PORT` | `8000` | Production HTTP listen port. |
| `OPENAI_API_KEY` | unset | Optional OpenAI credential; deterministic analysis works without it. |
| `OPENAI_MODEL` | `gpt-5-mini` | Model used for optional AI analysis. |
| `MAX_UPLOAD_MB` | `10` | Maximum size of each JUnit XML upload. |
| `MAX_TRACE_UPLOAD_MB` | `50` | Maximum compressed trace ZIP upload size. |
| `MAX_AI_TESTS_PER_REQUEST` | `5` | Maximum failed tests sent to AI per request. All failures still get deterministic analysis. |
| `AI_MAX_TEXT_CHARS` | `12000` | Per-field AI evidence sanitization limit. |

Invalid numeric settings fall back to safe defaults. The health check is
`GET /health`; it exposes no configuration or secrets.

## Start locally

```bash
python -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
uvicorn backend.main:app --reload
```

## Start in production

The production entry point binds to all interfaces and reads `PORT`:

```bash
APP_ENV=production PORT=8000 python -m backend.production
```

Run behind a managed HTTPS reverse proxy or load balancer in public deployments.
Do not expose plain HTTP to the internet. Configure request-body limits at that
edge as defense in depth, in addition to the application's upload limits.

## Docker

```bash
docker build -t flaky-test-analyzer .
docker run --rm -p 8000:8000 \
  -e APP_ENV=production -e PORT=8000 \
  flaky-test-analyzer
```

To enable optional AI analysis, pass the key at runtime (prefer your platform's
secret manager), never in the Dockerfile or build context:

```bash
docker run --rm -p 8000:8000 \
  -e APP_ENV=production -e PORT=8000 \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  flaky-test-analyzer
```
