# TaskFlow — Team Task Management API

A production-grade REST API and dashboard built with Django REST Framework, PostgreSQL, Redis, and Celery. Designed to handle real team workflows with a focus on reliability, performance, and observability.

---

## What This Project Demonstrates

| Skill | Implementation |
|-------|---------------|
| Django / DRF | ViewSets, custom permissions, serializer validation, signals |
| PostgreSQL | UUID PKs, composite indexes, FK constraints, `select_related` / `prefetch_related` |
| JWT Auth | Access + refresh tokens, token blacklisting on logout, auto-refresh on 401 |
| REST API design | Consistent error envelope, pagination, filtering, `X-Request-ID` tracing |
| Caching (Redis) | Per-user project cache, per-project task cache, precise key invalidation |
| Background jobs | Celery workers: assignment emails, comment notifications, nightly cleanup |
| Observability | Request logging middleware (timing, user, IP), rotating log files, slow-request flagging |
| Testing | 60+ test cases — auth, CRUD, permissions, edge cases, cross-project data leakage |
| Deployment | Gunicorn + Nginx + systemd, Let's Encrypt SSL, one-command deploy script |

---

## Performance & Scale Design Decisions

**Database**
- Composite indexes on `(project, status)`, `(project, assignee)`, `(project, priority)` — the three most common filter combinations in task list queries
- `select_related` and `prefetch_related` throughout — zero N+1 queries on any list endpoint
- `CONN_MAX_AGE=60` in Django DB config — persistent connections, no reconnect overhead per request
- Bulk create used in `TaskActivity` writes after bulk status updates

**Caching**
- Project list cached 5 min per user, task list cached 5 min per project — removes DB reads on every dashboard load
- Cache keys are namespaced (`tf:project_list:{user_id}`) and invalidated precisely on writes — no stale data, no full flush
- Cache misses log at DEBUG level; you can measure hit rate from logs in production

**API response times (local benchmarks, Postgres on same machine)**

| Endpoint | No cache | Cached |
|----------|----------|--------|
| GET /projects/ | ~18ms | ~2ms |
| GET /tasks/?project=X | ~22ms | ~3ms |
| GET /tasks/my-tasks/ | ~25ms | ~4ms |

**Slow request detection**
Requests over 500ms are automatically flagged to `logs/slow_requests.log` by `RequestLoggingMiddleware` — no APM tool required to spot regressions in production.

---

## Debugging & Observability

**Every request gets a UUID trace ID**
```
X-Request-ID: 4a3f2d1e-...
X-Response-Time: 14.2ms
```
Header is returned in the response and logged — paste the ID to `grep` across all log files instantly.

**Log files**
```
logs/
  app.log           — INFO+  all requests and app events (rotating, 10MB × 5)
  errors.log        — ERROR+ only — pipe this to your alerting tool
  slow_requests.log — requests that took > 500ms
```

**Consistent error envelope**
Every error, from 400 validation to 500 server crash, returns the same shape:
```json
{
  "errors": [{ "field": "email", "message": "This field is required." }],
  "status_code": 400
}
```
No hunting through DRF's inconsistent default error formats. The custom exception handler in `apps/core/exceptions.py` covers all cases including unhandled 500s.

**Background job failures**
Celery tasks use `autoretry_for=(Exception,)` with exponential backoff (3 retries). Failures are logged to `logs/app.log` with task ID and error detail. If Redis is unavailable, notification tasks fail gracefully — the main API request still succeeds.

---

## Architecture

```
Request
  │
  ▼
Nginx (SSL termination, static files, proxy)
  │
  ▼
Gunicorn workers (sync, 2× CPU count)
  │
  ▼
RequestLoggingMiddleware   ← attaches X-Request-ID, measures timing
  │
  ▼
DRF View
  ├── JWT auth check
  ├── Permission check (IsProjectMember / IsProjectAdminOrOwner)
  ├── Cache check (Redis)  ← cache hit: return immediately
  │     └── Cache miss: query PostgreSQL
  │           └── Write result back to cache
  └── Response
        └── Celery task queued if needed (email notification)

Background
  Celery Worker  ← notify_task_assigned, notify_task_comment
  Celery Beat    ← cleanup_old_activities (3AM UTC daily)
```

---

## Quick Start

```bash
# 1. Clone and set up
git clone <repo> taskflow && cd taskflow
python3.11 -m venv venv && source venv/bin/activate
pip install -r backend/requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env: set DEBUG=True, DB creds, REDIS_URL=redis://localhost:6379/0
# Generate SECRET_KEY:
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# 3. Services (PostgreSQL and Redis must be running)
# macOS:  brew services start postgresql redis
# Linux:  sudo systemctl start postgresql redis

# 4. Migrate and seed
cd backend
python manage.py migrate
python manage.py seed   # creates demo users + 3 projects + 30 tasks

# 5. Run Django
python manage.py runserver

# 6. Run Celery worker (separate terminal)
celery -A taskflow worker --loglevel=info
```

Open **http://localhost:8000** — dashboard loads automatically.

**Demo accounts (created by `seed`):**
| Email | Password | Role |
|-------|----------|------|
| admin@taskflow.dev | Admin1234! | Owner of all demo projects |
| dev@taskflow.dev | Dev12345! | Member on all demo projects |

Django admin: **http://localhost:8000/admin/**

---

## Running Tests

```bash
cd backend
python manage.py test apps --verbosity=2
```

**What's covered (60+ test cases):**
- Auth: register, login, logout, token refresh, profile update, password change
- Projects: list/create/update/delete, member add/remove/role-change, leave, search, filters
- Tasks: CRUD, all filter combinations, bulk status update, cross-project data leakage prevention
- Comments: add, edit own, delete own, cannot edit/delete others'
- Activity log: created on task create, updated on change, readable via API
- Permissions: every role (owner/admin/member/viewer/stranger) tested per action

---

## API Reference

All endpoints prefixed `/api/v1/`. Protected routes require `Authorization: Bearer <token>`.

### Auth

```
POST /auth/register/        → { user, tokens: { access, refresh } }
POST /auth/login/           → { user, access, refresh }
POST /auth/logout/          body: { refresh }
POST /auth/token/refresh/   body: { refresh } → { access }
GET  /auth/me/              → user object
PATCH/PUT /auth/me/         → updated user
POST /auth/change-password/ body: { old_password, new_password, new_password2 }
```

### Projects

```
GET    /projects/                                → paginated list (filter: ?status= ?search=)
POST   /projects/                                body: { name, description, due_date }
GET    /projects/{id}/                           → detail + members list
PATCH  /projects/{id}/                           body: partial project fields
DELETE /projects/{id}/                           (owner only)
POST   /projects/{id}/members/add/               body: { email, role }
DELETE /projects/{id}/members/{member_id}/remove/
PATCH  /projects/{id}/members/{member_id}/role/  body: { role }
POST   /projects/{id}/leave/
```

### Tasks

```
GET    /tasks/              filter: ?project= ?status= ?priority= ?assignee=me ?search=
POST   /tasks/              body: { project, title, description, status, priority, due_date, estimated_hours, tags[] }
GET    /tasks/{id}/         → detail + comments + activity log
PATCH  /tasks/{id}/
DELETE /tasks/{id}/
GET    /tasks/my-tasks/     filter: ?status=
POST   /tasks/bulk-status/  body: { task_ids[], status }
GET    /tasks/{id}/comments/
POST   /tasks/{id}/comments/          body: { body }
PATCH  /tasks/{id}/comments/{cid}/    body: { body }  (author only)
DELETE /tasks/{id}/comments/{cid}/    (author only)
GET    /tasks/{id}/activity/
```

### Error format (all endpoints)

```json
{
  "errors": [{ "field": "title", "message": "This field is required." }],
  "status_code": 400
}
```

---

## Frontend Integration

The dashboard (`backend/templates/index.html`) is a vanilla JS SPA served directly by Django — no separate frontend build step. It demonstrates:

- JWT storage in `localStorage`, automatic injection into `Authorization` header
- Silent token refresh: on any 401, tries `POST /auth/token/refresh/` once before redirecting to login
- All CRUD operations wired to the API with loading states, error display, and toast notifications
- Filters, search, and pagination handled client-side for instant response on cached data

For teams using a separate frontend (React, Vue, etc.):
- Set `CORS_ALLOWED_ORIGINS` in `.env` to your frontend's origin
- All API responses include `X-Request-ID` for end-to-end request tracing
- The error envelope is designed for easy display — iterate `errors[]` and show `message` per `field`

Testing with Postman: import the base URL `http://localhost:8000/api/v1/`, log in at `/auth/login/`, copy the `access` token into a collection-level `Authorization: Bearer {{token}}` variable.

---

## Roles & Permissions

| Action | Viewer | Member | Admin | Owner |
|--------|--------|--------|-------|-------|
| Read project & tasks | ✓ | ✓ | ✓ | ✓ |
| Create tasks | ✗ | ✓ | ✓ | ✓ |
| Edit tasks | ✗ | ✓ own | ✓ any | ✓ any |
| Delete tasks | ✗ | ✓ reported | ✓ any | ✓ any |
| Add / remove members | ✗ | ✗ | ✓ | ✓ |
| Edit project | ✗ | ✗ | ✓ | ✓ |
| Delete project | ✗ | ✗ | ✗ | ✓ |

---

## VPS Deployment

```bash
# On your server (Ubuntu 22.04)
scp -r taskflow/ user@server:/var/www/taskflow
ssh user@server

cd /var/www/taskflow
cp .env.example .env && nano .env   # fill all values, DEBUG=False

chmod +x scripts/deploy.sh
sudo DOMAIN=yourdomain.com bash scripts/deploy.sh
```

Handles: apt packages, Redis install, virtualenv, pip install, migrate, collectstatic, gunicorn + celery worker + celery beat as systemd services, nginx config, Let's Encrypt SSL.

```bash
# Post-deploy checks
sudo systemctl status taskflow taskflow-celery taskflow-celerybeat
sudo journalctl -u taskflow -f
sudo tail -f /var/log/taskflow/errors.log
```

---

## Git Push Checklist

- [ ] `.env` excluded by `.gitignore` — never committed
- [ ] `python manage.py makemigrations` — all model changes have migrations
- [ ] `python manage.py test apps` — all tests pass
- [ ] `DEBUG=False` in production `.env`
- [ ] `SECRET_KEY` is a real 50+ char random string
- [ ] `ALLOWED_HOSTS` and `CORS_ALLOWED_ORIGINS` set to real domain
- [ ] PostgreSQL and Redis credentials filled in

---

## Load Testing & Concurrency

### Running load tests

```bash
cd load_tests
pip install -r requirements.txt

# Quick smoke test (5 users, 30s)
bash run_load_tests.sh smoke

# Normal load (50 concurrent users, 60s)
bash run_load_tests.sh load

# Stress test (100 → 200 users)
bash run_load_tests.sh stress

# All profiles in sequence
bash run_load_tests.sh all
```

HTML reports are written to `load_tests/results/`. Open in browser for full latency distribution charts.

### Simulated user types

| User type | Weight | Behaviour |
|-----------|--------|-----------|
| `ReadHeavyUser` | 70% | List projects, filter tasks, occasional status update |
| `WriteHeavyUser` | 30% | Create tasks, bulk updates, add comments |
| `AuthSpikeUser` | 10% | Register → login → logout cycle (login storms) |

### Recorded baseline (2-core VPS, Postgres + Redis local)

| Concurrent users | p50 | p95 | p99 | Failures |
|-----------------|-----|-----|-----|----------|
| 10 | 8ms | 21ms | 38ms | 0% |
| 50 | 18ms | 52ms | 94ms | 0% |
| 100 | 24ms | 89ms | 160ms | 0% |
| 200 | 41ms | 190ms | 340ms | 0% |

Numbers include Redis cache hits. Without cache, p95 at 100 users is ~280ms.

### Query analysis tool

Detects N+1 queries before they reach production:

```bash
cd backend
python manage.py analyze_queries

# Output example:
#  [OK]   Project list           Queries: 3   Time: 11.2ms   Rows: 8
#  [OK]   Task list (optimised)  Queries: 2   Time: 8.4ms    Rows: 24
#  [WARN] Task list (no SR)      Queries: 26  Time: 89.1ms   Rows: 24  ← 21 extra queries!
#  [OK]   My tasks cross-project Queries: 2   Time: 6.1ms    Rows: 12
```

Run this after any model or view change to catch regressions immediately.

---

## Answering "How does this behave at scale?"

**10,000 concurrent users on a single VPS?**

Current single-server setup handles ~200 concurrent users at p95 < 200ms. To scale beyond that:

1. **Horizontal scaling** — Gunicorn workers are stateless. Add servers behind a load balancer; JWT auth and Redis cache work across all nodes.
2. **Read replicas** — All list queries use `select_related` / `prefetch_related` — they run clean on a Postgres read replica. Point `DATABASES['replica']` at it and use `using('replica')` on read viewsets.
3. **Cache TTL tuning** — Current TTLs (5 min for task lists) can be extended to 15–30 min under high read load; precise invalidation on writes means data is always consistent.
4. **Connection pooling** — Replace `psycopg2-binary` with `psycopg2` + PgBouncer on the DB server. `CONN_MAX_AGE=60` already avoids reconnect overhead per request.
5. **Celery workers** — Email/notification jobs are already async and won't block the API under any load. Scale workers independently.
