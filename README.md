# RemoteConnect – Backend

The backend for **RemoteConnect**: a FastAPI service providing authentication/RBAC, a device-identity WebSocket handshake for the desktop client (persistent, AnyDesk-style numeric device IDs), Celery + APScheduler-driven background task/analysis job orchestration, and a separate Task Monitor dashboard app. Redis backs both the Celery task queue and response caching; PostgreSQL is the primary datastore.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Local Development Setup](#local-development-setup)
3. [CLI Commands](#cli-commands)
4. [Environment Variables](#environment-variables)
5. [Testing](#testing)
6. [Cloud Deployment](#cloud-deployment)
7. [Project Structure](#project-structure)
8. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

Each domain module lives under `apps/app/modules/<name>/` and follows roughly the same shape (not every module has every folder — a module without a REST surface just skips `controller/`, etc.):

```
apps/app/modules/<name>/
├── controller/          # FastAPI routers (*_controller.py)
├── service/ or services/  # Business logic, called from controllers
├── repositories/        # DB queries
├── entities/             # SQLAlchemy models, decorated with @Entity()
├── analysis/             # Scheduled analysis jobs, decorated with @analysis(...)
└── websocket/            # WebSocket routers, where applicable
```

Modules today, and what each one owns:

| Module | Purpose |
| --- | --- |
| `app` | RBAC permission-group registry (`GET /app/groups`), app-wide key/value config, API request-log archival/cleanup |
| `auth` | Login/session lifecycle (`/auth`, `/auth/verify`, `/auth/logout`) backing the JWT cookie used by the main app and the `/ws` gateway |
| `device` | Device-identity WebSocket handshake (`/ws/device`) — mints/resolves a persistent 10-digit device ID + secret install key per desktop client install |
| `impersonation` | Admin "log in as another user" feature (marked a temporary POC) — must run through the dedicated `impersonation-worker` process |
| `miscellaneous` | User-submitted feature requests/feedback, with S3 file attachments |
| `monitor` | Services backing the separate Task Monitor app (`apps/monitor/`) — session redemption, access-key gating, task run history/trend, worker status |
| `okta` | Okta SAML SSO (`/okta/login`, `/okta/callback`), with a local-dev bypass via `DEFAULT_USER_EMAIL` |
| `role` | RBAC role management (`/roles` CRUD, default role, group hierarchy) |
| `task` | Celery task-run tracking/observability, watchdog + analysis-log export jobs |
| `user` | User accounts, self-service endpoints, role assignments, usage/reporting endpoints |

Two auto-discovery mechanisms walk this convention at startup instead of manual registration:

- **Controllers** — [`core/controllers_discovery.py`](apps/app/core/controllers_discovery.py) imports every `*_controller.py` under each module's `controller/` folder and mounts its `router`.
- **Analysis jobs** — [`core/analysis_discovery.py`](apps/app/core/analysis_discovery.py) imports `*_analysis.py` files under each module's `analysis/` folder and collects functions decorated `@analysis(cron=... | interval=...)`.

Entities are discovered separately by Alembic/[`core/entities_discovery.py`](apps/app/core/entities_discovery.py), per the glob roots in `infra/alembic.ini`'s `model_globs` (`database/entities`, `apps/app/**/entities`). In practice almost every entity lives under `apps/app/modules/<module>/entities/` — `database/entities` only holds `BaseModel` and a couple of shared entities.

**WebSocket gateways** — there are three `@router.websocket(...)` routes in the codebase:

- [`apps/app/websocket/gateway.py`](apps/app/websocket/gateway.py) — `/ws`, the main app's gateway. Requires a bearer JWT, re-checks auth periodically, and listens for Redis pub/sub cache-invalidation messages to push live updates / force-close sessions.
- [`apps/app/modules/device/websocket/device_gateway.py`](apps/app/modules/device/websocket/device_gateway.py) — `/ws/device`, unauthenticated. The desktop client connects here on launch; the server mints a persistent 10-digit `device_id` (and a secret `install_key`) on first connect, or resolves the existing one on reconnect.
- [`apps/monitor/websocket/gateway.py`](apps/monitor/websocket/gateway.py) — `/ws`, in the separate Task Monitor app, gated by a short-lived monitor access token (bypassed when `ENVIRONMENT=local`).

**Auth & rate limiting** — cookie-based JWT (`core/auth/`), with Okta SAML SSO (`modules/okta`). Request pipeline, as wired in [`main.py`](apps/app/main.py): GZip → TrustedHost → CORS → auto-discovered controllers + both `/ws` gateways → role authorization → user rate limiting → request logging → JWT auth middleware (routes marked `@public` are exempted) → path rate limiting → request-id/cache-decode-error middleware → cache-control/security headers.

**Background jobs** — Celery (`apps/app/celery_app.py`) handles async task execution; APScheduler (wired up in `core/lifespan.py`) drives the cron/interval scheduling for analysis jobs.

**Separate apps** — `python -m run start` actually launches *three* independent FastAPI processes sharing the same codebase (see [Local Development Setup](#local-development-setup)): the main API, the standalone Task Monitor app (`apps/monitor/`), and a dedicated single-process instance of the main app for the impersonation feature.

---

## Local Development Setup

### 1. Requirements

- Python 3.11 (matches the Docker image)
- PostgreSQL
- pip
- Docker (for Redis)
- `pg_dump` on your `PATH`, or `PG_DUMP_PATH` set in `.env` — required by the migration validator (see [Migrations](#migrations) below), not just for backups

---

### 2. Setup virtual environment

**Quick Setup (Recommended):**
```bash
setup_venv.bat
```

**Manual Setup:**

**Windows:**
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**Mac / Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

### 3. Redis Setup (Required for Celery)

Run Redis in Docker:
```bash
docker run --name redis-server -p 6379:6379 -d redis:7
```

---

### 4. Running the Application (Development)

**For development, Docker Compose is NOT required.** You only need Docker to run Redis locally — the rest (FastAPI, Celery, migrations) runs natively against your Python environment and local PostgreSQL. Use Docker Compose only for cloud/production deployments (see [Cloud Deployment](#cloud-deployment)).

#### Step-by-step Local Development Workflow

1. **Set up the virtual environment** — `setup_venv.bat`, or the manual steps above.

2. **Configure environment variables**
   - Copy `.env.example` to `.env` in the project root and fill in your local setup (database, Redis, etc.). See [Environment Variables](#environment-variables) below.
   - `JWT_SECRET`, `SECRET_ENCRYPTION_KEY`, and `FILE_REFERENCE_ENCRYPTION_KEY` are **required** — the app refuses to boot with an empty value or the placeholder default. Generate a Fernet key for the latter two with:
     ```bash
     python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
     ```

3. **Start Redis in Docker**
   ```bash
   docker run --name redis-server -p 6379:6379 -d redis:7
   ```
   Confirm with `docker ps` — you should see `redis-server` with `0.0.0.0:6379->6379/tcp`.

4. **Run database migrations**
   ```bash
   python -m run.migration upgrade head
   ```

5. **Start the application**
   ```bash
   python -m run start
   ```
   With no arguments this starts *everything*: the main API (`:8000`), the Task Monitor app (`:8001`), a dedicated impersonation-worker instance of the main app (`:8010`), and a Celery worker + beat scheduler pair — all in one command, with `--reload` on the main/monitor apps.

   Only need one piece? `python -m run start main|monitor|impersonation` runs just that process (still alongside a shared Celery worker/beat). Add `--no-reload` to disable autoreload, or `-f`/`--force` to bypass the running-instance conflict check.

6. **(Optional) Seed some data**
   - `python -m run.seed fake_dev_data` seeds fake users/roles for local testing (see [CLI Commands](#cli-commands)).

---

## CLI Commands

All commands below are run from the project root with the virtual environment activated. Most are invoked as `python -m run.<name> ...`; only `start` (a [taskipy](https://github.com/illBeRoy/taskipy) task) is `python -m run start`.

### App

| Command | Description |
| --- | --- |
| `python -m run start [main\|monitor\|impersonation] [--no-reload] [-f\|--force]` | Starts the Celery worker + beat, and one or all three FastAPI apps (main, Task Monitor, impersonation-worker). |

### Migrations

Migrations are managed with a custom Alembic runner (`run/migration.py`, config in `infra/alembic.ini`) that supports dynamic model discovery and auto-formats migration files with black.

```bash
# Create a new migration (blank upgrade()/downgrade() to fill in by hand)
python -m run.migration create "<name of migration>"

# Create a new migration, auto-populated from model/DB drift
python -m run.migration create "<name of migration>" --autogenerate

# Regenerate the latest migration file in place (e.g. after tweaking a model
# before it's been applied anywhere else)
python -m run.migration update current ["<message>"] [--force]

# Apply migrations (upgrade to target, e.g., head)
python -m run.migration upgrade <target>

# Downgrade to a target revision
python -m run.migration downgrade <target>

# Validate upgrade()/downgrade() reversibility without touching the real DB
python -m run.migration test [target]

# Show current / head revision(s)
python -m run.migration current
python -m run.migration heads [-v|--verbose]

# Merge multiple heads into a single new revision
python -m run.migration merge "<message>"

# Stamp the DB to a revision without running migrations
python -m run.migration stamp <target>
```

**Note:** `upgrade` runs the migration against a temporary cloned database first to validate it before touching the real one (this is what requires `pg_dump`), and aborts if validation fails. Pass `--force`/`-f` to skip validation and run directly against the real database.

### Seed

Data seeds are independent, named scripts under `database/seed/`, run via `run/seed.py`'s own CLI. There's no ordering and no tracking of what's already run:

```bash
python -m run.seed generate "<service name>"   # scaffold a new seed file

python -m run.seed "<service name>"
python -m run.seed "<service name>_seed"
```

Seeds shipped today:
```bash
python -m run.seed app_configurations
python -m run.seed fake_dev_data
```

### Analysis

Run/inspect analysis jobs (`run/analysis.py`), i.e. functions decorated `@analysis(...)` under any module's `analysis/` folder:

```bash
# Run a specific job in-process
python -m run.analysis <job_id>

# Dispatch through Redis lock + Celery instead
python -m run.analysis <job_id> --task [-f|--force]

# Run every registered job
python -m run.analysis all

# Print schedule/source info for one job, or all
python -m run.analysis explain [job_id]

# Show global concurrency-slot status
python -m run.analysis pool
```

### Cron

Inspect currently registered APScheduler cron/interval jobs:
```bash
python -m run.cron list
```

### Admin

Mint a one-time Task Monitor access link (emailed to `MAIL_DEFAULT_TO`; requires `MONITOR_ENABLED=true`):
```bash
python -m run.admin generate
```

### Logs

Delete (or truncate, if still open) the local `logs/api-*.log` files:
```bash
python -m run.log delete [-f|--force]
```

### Tests

Run the pytest suite for a given service via `run/test.py` (thin wrapper around `pytest`, passes extra args straight through):

```bash
python -m run.test cron [pytest_args...]
# e.g. python -m run.test cron -k concurrency -s

python -m run.test all   # everything under tests/, except tests/impersonation
```

`cron` and `scheduler` are both valid service names and point at the same `tests/cron` suite.

---

## Environment Variables

Copy `.env.example` to `.env` and fill these in. `.env.example` is kept as a 1:1
mirror of every field in `apps/app/core/settings.py`'s `Settings` class —
`tests/core/test_env_example_sync.py` enforces that automatically. The table
below covers the ones you're most likely to need for local setup — for
anything else, `.env.example` has an inline comment on any var whose purpose
isn't obvious from its name.

| Variable | Default | Notes |
| --- | --- | --- |
| `PG_DB_NAME`, `PG_DB_USER`, `PG_DB_PASSWORD`, `PG_DB_HOST`, `PG_DB_PORT` | — | PostgreSQL connection. Ignored under Docker Compose, where host/port are hardcoded to `db`/`5432`. |
| `PG_DUMP_PATH` | *(empty, falls back to `PATH`)* | Only needed if `pg_dump` isn't on `PATH` — used by the migration validator. |
| `ENVIRONMENT` | `local` | Gates the local Okta bypass (`DEFAULT_USER_EMAIL`) — keep as `local` only on your own machine. |
| `PORT`, `HOST` | `8000`, `0.0.0.0` | Where the main API listens. |
| `MONITOR_PORT` | `8001` | Where the local (non-Docker) Task Monitor app listens. |
| `JWT_SECRET` | — (**required**) | The app refuses to start with an empty value or the placeholder default. |
| `SECRET_ENCRYPTION_KEY`, `FILE_REFERENCE_ENCRYPTION_KEY` | — (**required**) | Two distinct Fernet keys — deliberately separate so the two security domains can't be reused/confused. App refuses to start if either is empty. |
| `BASE_URL`, `WEB_URL`, `API_PREFIX` | `http://127.0.0.1:8000/`, `http://127.0.0.1:3000/`, `/api` | Self-referencing base URL, frontend URL, API route prefix. |
| `MONITOR_BASE_URL`, `MONITOR_ENABLED` | —, `true` | `MONITOR_ENABLED=false` is a kill switch — blocks new access-token generation and rejects every Task Monitor endpoint. |
| `SSO_LOGIN_URL`, `OKTA_CERT`, `OKTA_REDIRECT_TO`, `OKTA_IDP` | — | Okta SAML SSO configuration. |
| `DEFAULT_USER_EMAIL` | *(empty)* | **Local-only auth bypass.** When set and `ENVIRONMENT=local`, `GET /api/okta/login` logs you in as this email (creating the user if needed) instead of doing real Okta SAML. Never set outside local dev. |
| `AUTH_COOKIE_NAME`, `AUTH_COOKIE_SECURE`, `AUTH_COOKIE_SAMESITE`, `AUTH_COOKIE_DOMAIN` | `access_token`, `false`, `lax`, *(empty)* | The access token is delivered as an HttpOnly cookie. `AUTH_COOKIE_SECURE` **must** be `true` on any real https deployment. Only set `AUTH_COOKIE_DOMAIN` if the frontend and API share a parent domain. |
| `MAIL_HOST`, `MAIL_USER`, `MAIL_PASS`, `MAIL_PORT`, `MAIL_DEFAULT_TO` | — | SMTP for outbound email (e.g. `run.admin generate`). |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | `redis://localhost:6379/0` | Redis connection for Celery. Ignored under Docker Compose. |
| `CACHE_EXPIRE_SECONDS`, `CACHE_DISABLE` | `600`, `false` | Redis response-cache TTL and kill switch. |

Everything else in `.env.example` (CORS, JWT/token tuning, impersonation TTLs, S3, log/task/analysis retention windows, monitor internals, rate limiting, request log settings, log redaction, etc.) has a sensible default and only needs overriding for specific tuning — see the inline comments in `.env.example` itself.

Deploying to staging instead of running locally? `.env.staging.example` mirrors the same field set with staging-appropriate values and `<placeholder>` markers for anything that needs a real staging credential.

---

## Testing

Test suites live under `tests/`: `tests/core/` (env-sync check, rate-limit fail-open behavior), `tests/cron/` (concurrency/scheduling), `tests/impersonation/`, `tests/task/` (Celery liveness, watchdog, redelivery fencing).

```bash
python -m run.test cron
python -m run.test all   # everything except tests/impersonation
```

This is a thin wrapper around `pytest`, so any pytest flags work: `python -m run.test cron -k concurrency -s`.

Migration reversibility has its own separate validation path — see `python -m run.migration test` under [Migrations](#migrations).

---

## Cloud Deployment

### Cloud Setup Steps

1. **Configure environment variables** — copy `.env.example` to `.env`, update all values for production.

2. **Build Docker images**
   ```bash
   docker compose build --no-cache
   ```

3. **Apply database migrations**
   ```bash
   docker compose run migrate
   ```

4. **Start all services**
   ```bash
   docker compose up
   # or, detached:
   docker compose up -d
   ```

`docker-compose.yml` defines seven services, all sharing the same image built from the repo's `Dockerfile`:

| Service | Role |
| --- | --- |
| `api` | Main app (gunicorn + uvicorn workers, `-w 10`), port 8000 |
| `impersonation-worker` | Same app, single-process (`-w 1`), port 8010 — the impersonation feature requires requests to land on this dedicated process |
| `monitor` | Task Monitor app, single-process (`-w 1`), port 8001 |
| `worker` | Celery worker |
| `beat` | Celery beat scheduler |
| `redis` | Broker + cache |
| `db` | PostgreSQL |

Plus a `migrate` one-off service (behind the `migrate` compose profile) for step 3.

---

## Project Structure

```
backend/
├── apps/
│   ├── app/                         # main FastAPI app
│   │   ├── main.py                  # create_app(), mounts controllers + both /ws gateways
│   │   ├── celery_app.py, celery_worker.py
│   │   ├── core/                    # settings, auth, middleware, rate limiting, discovery, db
│   │   │   ├── auth/, rate_limiting/, request_logging/
│   │   │   ├── controllers_discovery.py, analysis_discovery.py, entities_discovery.py
│   │   │   └── settings.py, db.py, lifespan.py, logging.py, errors.py
│   │   ├── modules/                 # domain modules (see Architecture Overview)
│   │   │   ├── app/, auth/, device/, impersonation/, miscellaneous/
│   │   │   └── monitor/, okta/, role/, task/, user/
│   │   ├── utils/                   # decorators, email templates, redis/s3/cache helpers
│   │   └── websocket/               # gateway.py (/ws), emitter.py
│   └── monitor/                     # separate FastAPI app (Task Monitor), port 8001
│       ├── main.py, controller.py, decorators.py, rate_limit.py
│       └── websocket/                # gateway.py (/ws)
├── database/
│   ├── entities/                    # BaseModel + a couple of shared entities
│   ├── migrations/                  # Alembic migration scripts
│   ├── seed/                        # seed scripts, run via python -m run.seed
│   └── session_factory.py
├── infra/
│   ├── alembic.ini, alembic/env.py  # model discovery + migration config
│   ├── groups.py                    # RBAC permission-group tree
│   └── redis_keys.py
├── run/                             # CLI entry points (see CLI Commands)
│   ├── migration.py, seed.py, analysis.py, cron.py, test.py, admin.py, log.py
│   └── scripts/start.py             # the python -m run start orchestrator
├── tests/                           # core/, cron/, impersonation/, task/
├── Dockerfile, docker-compose.yml, entrypoint.sh
├── requirements.txt, pyproject.toml
├── .env.example
└── README.md
```

---

## Troubleshooting

### Issue: App fails to start with a JWT/encryption key error

`Settings` refuses to boot if `JWT_SECRET`, `SECRET_ENCRYPTION_KEY`, or `FILE_REFERENCE_ENCRYPTION_KEY` is empty or left as a placeholder default — set real values in `.env` (see [Environment Variables](#environment-variables) for how to generate the encryption keys).

### Issue: Migration `upgrade` fails during validation, or complains about `pg_dump`

`upgrade` clones your schema into a temporary database to validate the migration before touching the real one, which requires `pg_dump`. Either install it and ensure it's on `PATH`, set `PG_DUMP_PATH` in `.env`, or pass `--force`/`-f` to skip validation entirely (only do this if you're confident the migration is safe).

### Issue: Celery tasks aren't running

- Confirm Redis is up: `docker ps` should show `redis-server` with `0.0.0.0:6379->6379/tcp`.
- `python -m run start` launches the worker and beat scheduler itself — if you started a FastAPI app another way (e.g. directly via `uvicorn`), Celery won't be running.
- `python -m run.cron list` shows what APScheduler currently has registered.

### Issue: Port already in use

The main API, Task Monitor app, and impersonation-worker use ports 8000, 8001, and 8010 respectively:

```bash
# Windows
netstat -ano | findstr :8000
taskkill /PID <PID> /F

# Mac/Linux
lsof -i :8000
kill -9 <PID>
```

Or override via `PORT`, `MONITOR_PORT`, or `IMPERSONATION_PORT` in `.env`.

---
