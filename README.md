# CodeJudge — Online Coding Judge Platform

A LeetCode-style judge: users register, browse problems, submit code in
Python/C++/Java, and get graded against hidden test cases by workers that
execute the code inside locked-down, ephemeral Docker containers.

## Architecture

```
┌───────────┐      HTTPS       ┌──────────────┐      SQL       ┌────────────┐
│  React    │ ───────────────► │  FastAPI     │ ──────────────► │ PostgreSQL │
│  (Vite)   │ ◄─────────────── │  API server  │ ◄────────────── │            │
└───────────┘                  └──────┬───────┘                 └────────────┘
                                       │ enqueue(submission_id)
                                       ▼
                                ┌──────────────┐
                                │  Redis queue │  (rq)
                                └──────┬───────┘
                     ┌─────────────────┼─────────────────┐
                     ▼                 ▼                 ▼
              ┌────────────┐   ┌────────────┐    ┌────────────┐
              │ Worker #1  │   │ Worker #2  │ …  │ Worker #N  │
              └─────┬──────┘   └─────┬──────┘    └─────┬──────┘
                    │ docker run --rm --network none …  │
                    ▼                                    ▼
           ┌─────────────────┐                 ┌─────────────────┐
           │ ephemeral sandbox│                │ ephemeral sandbox│
           │ container (1 per │                │ container (1 per │
           │ test case)       │                │ test case)       │
           └─────────────────┘                 └─────────────────┘
```

- **API layer** (`backend/app`): FastAPI + SQLAlchemy + JWT auth. Handles
  users, problems, and submissions. Submitting code never runs anything
  synchronously — it writes a row with status `QUEUED` and pushes a job
  onto Redis, so the request returns instantly regardless of load.
- **Queue** (Redis + `rq`): decouples "accept a submission" from
  "judge a submission." Workers are horizontally scalable —
  `docker compose up --scale worker=8` adds judging throughput without
  touching the API.
- **Judge workers** (`app/judge/worker.py` + `executor.py`): pull a job,
  fetch the submission + problem's test cases, and run the code inside a
  fresh Docker container per test case (Docker-outside-of-Docker via the
  mounted host socket).
- **Frontend** (`frontend/`): React + Monaco editor (the engine behind
  VS Code) for the code editor, polling the submission status endpoint
  until a verdict comes back.

## Why a queue instead of running code inline?

Direct request→execute would tie an API worker up for the full
compile+run+test cycle (seconds) and cap throughput at the web server's
concurrency. The queue lets the API stay fast and lets judging scale
independently — the classic pattern LeetCode/Codeforces-style systems use.

## Security model (the part that actually matters)

Untrusted, arbitrary code execution is the core risk of this whole
system. Defense in depth, applied per test-case container:

| Layer | Mechanism |
|---|---|
| Isolation | Fresh container per run, destroyed with `--rm` immediately after |
| Network | `--network none` — no outbound access, can't exfiltrate or call out |
| Filesystem | `--read-only` root + small `tmpfs` scratch — nothing persists, no disk-fill attacks |
| Memory | `--memory` + `--memory-swap` set equal (no swap escape hatch) → OOM-killed at the cap |
| CPU | `--cpus` share cap so one submission can't starve the host |
| Fork bombs | `--pids-limit` caps the process count inside the container |
| Privilege | `--cap-drop ALL` + `--security-opt no-new-privileges` + non-root UID |
| Timeout | Enforced both inside the container (`timeout --signal=KILL`) and outside via the subprocess call, so a bypass of one layer is still caught |
| Resource ulimits | `nproc`/`nofile` ulimits as a second layer under the Docker flags |

The API/worker containers mount the host's Docker socket to launch these
sandboxes as **siblings**, not children — the socket itself is never
exposed inside the sandbox, so submitted code has no path to it.

## Data model highlights

- `Problem` has both sample test cases (shown to the user) and hidden
  ones (used only for judging) — mirrors how real judges stop people
  hardcoding against visible tests.
- `Submission.result_detail` stores a per-test-case breakdown as JSON,
  so the UI can eventually show "3/5 passed, failed on case 4" detail.
- First `ACCEPTED` submission per user+problem bumps `User.rating` —
  simple placeholder for a real ELO/Codeforces-style rating system.

## Recent fixes & improvements (2026-08-27)

- **Config-driven sandbox images**: Docker images now configurable via `JUDGE_DOCKER_IMAGES` in settings (no hardcoded values)
- **Actual memory tracking**: Reports peak memory usage per test case via `docker inspect` (was always 0)
- **Docker availability check**: Validates Docker daemon access on executor startup; fails fast with clear error
- **Secure temp directories**: Replaced insecure `chmod 0o777` with dedicated sandbox subdirectory
- **Worker retry logic**: Transient failures (network, Docker) auto-retry up to 3× with backoff
- **Rating bump race fix**: Atomic check-and-update prevents double-credit on concurrent AC submissions
- **Structured logging**: Worker and API log at INFO/DEBUG levels with consistent format
- **Configurable job timeout**: `JOB_TIMEOUT` setting (default 120s) controls RQ job TTL
- **Pagination**: `/api/problems` supports `page` and `page_size` query params
- **JWT includes user_id**: Token payload has `sub` (username) + `user_id` for faster lookups
- **Required JWT_SECRET**: No default — must be set via env var in production
- **Composite DB index**: `Submission(user_id, problem_id)` speeds up "my submissions" and rating queries
- **Frontend poll cleanup**: Interval properly cleared on error/navigation/unmount
- **Loading states**: All list pages show "Loading…" skeletons while fetching
- **Per-language code persistence**: Switching languages preserves your code per-language
- **Request timeout**: 30s fetch timeout prevents hanging UI on slow/stalled API
- **Health checks**: All Docker Compose services have `healthcheck` + `depends_on: condition: service_healthy`
- **Non-root backend**: API/worker containers run as `appuser` (UID 1000)
- **Rate limiting**: 10 submissions/minute per user (Redis-backed sliding window)
- **Difficulty validation**: Problem creation validates EASY/MEDIUM/HARD enum
- **Docker socket permission check**: Warns if `/var/run/docker.sock` isn't accessible

## Running locally

```bash
# 1. Build the sandbox execution images (one-time, or whenever they change)
docker build -t judge-sandbox-python:latest -f sandbox/Dockerfile.python sandbox
docker build -t judge-sandbox-cpp:latest    -f sandbox/Dockerfile.cpp    sandbox
docker build -t judge-sandbox-java:latest   -f sandbox/Dockerfile.java   sandbox

# 2. Bring up Postgres, Redis, API, workers, and the frontend
docker compose up --build

# 3. Seed a couple of demo problems + an admin user
docker compose exec api python -m app.seed
```

Then open http://localhost:5173. The API is at http://localhost:8000
with interactive docs at http://localhost:8000/docs.

Scale judging capacity independently of everything else:
```bash
docker compose up --scale worker=8
```

## Running the backend without Docker Compose (quick dev loop)

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload   # uses local SQLite by default
```
Note: without the sandbox images built and Docker available, submissions
will queue but the worker's `docker run` calls will fail — build the
sandbox images first, or point `REDIS_URL`/run a worker separately.

## Environment variables (backend)

| Variable | Default | Required | Description |
|---|---|---|---|
| `DATABASE_URL` | `sqlite:///./judge.db` | No | SQLAlchemy connection string |
| `JWT_SECRET` | — | **Yes** | HS256 signing key (no default!) |
| `JWT_ALGORITHM` | `HS256` | No | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | No | Token lifetime |
| `REDIS_URL` | `redis://localhost:6379/0` | No | Redis connection |
| `SUBMISSION_QUEUE` | `submissions` | No | RQ queue name |
| `JOB_TIMEOUT` | `120` | No | RQ job TTL (seconds) |
| `JUDGE_TIME_LIMIT_SEC` | `5` | No | Per-test-case wall clock limit |
| `JUDGE_MEMORY_LIMIT_MB` | `256` | No | Per-test-case memory limit |
| `JUDGE_CPU_LIMIT` | `1.0` | No | Docker `--cpus` value |
| `JUDGE_PIDS_LIMIT` | `64` | No | Docker `--pids-limit` |
| `JUDGE_NETWORK_DISABLED` | `true` | No | `--network none` if true |
| `JUDGE_DOCKER_IMAGES` | see config | No | Per-language sandbox images |
| `ENV` | `development` | No | `production` enables INFO logging |

## What's intentionally simplified (and how you'd extend it)

- **Rating system** is a flat point bump on first AC. A real implementation
  would do a Codeforces-style rating delta based on contest performance.
- **No contest mode** — problems are always open. Adding time-boxed
  contests would mean a `Contest` model, a submission cutoff check, and
  a separate live leaderboard scoped to the contest window.
- **Language support** is Python/C++/Java; adding one is just a new
  Dockerfile in `sandbox/` + an entry in `judge/languages.py`.
- **Result detail** is stored but the frontend only shows the final
  verdict — showing per-test-case pass/fail is a small UI addition
  reading `submission.result_detail`.