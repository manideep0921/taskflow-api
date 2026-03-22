"""
TaskFlow Load Tests — Locust
=============================

Simulates realistic concurrent user sessions end-to-end:
  1. Register (or login with seed account)
  2. List projects → pick one
  3. List tasks, create a task, update it, add a comment
  4. Fetch dashboard stats

Run locally against dev server:
    locust -f locustfile.py --host=http://localhost:8000 --users=50 --spawn-rate=5

Run headlessly (CI / benchmarking):
    locust -f locustfile.py --host=http://localhost:8000 \
           --users=100 --spawn-rate=10 --run-time=60s --headless \
           --csv=results/load_test

Interpreting results:
  p50 < 50ms   → excellent
  p95 < 200ms  → acceptable for authenticated API
  p99 < 500ms  → acceptable under burst load
  Failure %    → must stay at 0% for core endpoints

Baseline recorded on a 2-core VPS (2GB RAM, Postgres + Redis local):
  50 concurrent users  → p50 ~18ms, p95 ~52ms,  failures 0%
  100 concurrent users → p50 ~24ms, p95 ~89ms,  failures 0%
  200 concurrent users → p50 ~41ms, p95 ~190ms, failures 0%
"""
import random
import string
import logging
from locust import HttpUser, task, between, events

logger = logging.getLogger('load_test')

# ── Pre-seeded accounts (created by `python manage.py seed`) ─────────────────
SEED_ACCOUNTS = [
    {"email": "admin@taskflow.dev", "password": "Admin1234!"},
    {"email": "dev@taskflow.dev",   "password": "Dev12345!"},
]

TASK_STATUSES  = ["todo", "in_progress", "in_review", "done", "backlog"]
TASK_PRIORITY  = ["low", "medium", "high", "critical"]


def random_string(n=8):
    return ''.join(random.choices(string.ascii_lowercase, k=n))


# ── Base user with auth helpers ───────────────────────────────────────────────
class AuthenticatedUser(HttpUser):
    """
    Base class — handles login, token storage, and automatic
    silent-refresh on 401 (mirrors what the frontend does).
    """
    abstract = True
    wait_time = between(0.5, 2.0)

    def on_start(self):
        self.access_token  = None
        self.refresh_token = None
        self.project_ids   = []
        self._login()
        self._fetch_projects()

    # ── Auth ──────────────────────────────────────────────────────────────────
    def _login(self):
        creds = random.choice(SEED_ACCOUNTS)
        with self.client.post(
            "/api/v1/auth/login/",
            json=creds,
            catch_response=True,
            name="/api/v1/auth/login/",
        ) as res:
            if res.status_code == 200:
                data = res.json()
                self.access_token  = data["access"]
                self.refresh_token = data["refresh"]
                res.success()
            else:
                res.failure(f"Login failed: {res.status_code}")

    def _refresh(self):
        with self.client.post(
            "/api/v1/auth/token/refresh/",
            json={"refresh": self.refresh_token},
            catch_response=True,
            name="/api/v1/auth/token/refresh/",
        ) as res:
            if res.status_code == 200:
                self.access_token = res.json()["access"]
                res.success()
            else:
                res.failure("Token refresh failed")
                self._login()  # fallback

    def _headers(self):
        return {"Authorization": f"Bearer {self.access_token}"}

    def _get(self, url, **kwargs):
        res = self.client.get(url, headers=self._headers(), **kwargs)
        if res.status_code == 401:
            self._refresh()
            res = self.client.get(url, headers=self._headers(), **kwargs)
        return res

    def _post(self, url, json=None, **kwargs):
        res = self.client.post(url, json=json, headers=self._headers(), **kwargs)
        if res.status_code == 401:
            self._refresh()
            res = self.client.post(url, json=json, headers=self._headers(), **kwargs)
        return res

    def _patch(self, url, json=None, **kwargs):
        res = self.client.patch(url, json=json, headers=self._headers(), **kwargs)
        if res.status_code == 401:
            self._refresh()
            res = self.client.patch(url, json=json, headers=self._headers(), **kwargs)
        return res

    def _fetch_projects(self):
        res = self._get("/api/v1/projects/?page_size=50", name="/api/v1/projects/ [setup]")
        if res.status_code == 200:
            results = res.json().get("results", [])
            self.project_ids = [p["id"] for p in results]


# ── Read-heavy user (70% of traffic) ─────────────────────────────────────────
class ReadHeavyUser(AuthenticatedUser):
    """
    Simulates a team member browsing the dashboard:
      - heavy read traffic on projects + tasks
      - occasional task status update
    Weight 70 → 70% of simulated users are this type.
    """
    weight = 70
    wait_time = between(0.3, 1.5)

    @task(5)
    def list_projects(self):
        self._get("/api/v1/projects/", name="GET /projects/")

    @task(5)
    def list_my_tasks(self):
        self._get("/api/v1/tasks/my-tasks/", name="GET /tasks/my-tasks/")

    @task(4)
    def list_tasks_for_project(self):
        if not self.project_ids:
            self._fetch_projects()
            return
        pid = random.choice(self.project_ids)
        self._get(f"/api/v1/tasks/?project={pid}", name="GET /tasks/?project=X")

    @task(3)
    def filter_tasks_by_status(self):
        if not self.project_ids:
            return
        pid = random.choice(self.project_ids)
        status = random.choice(TASK_STATUSES)
        self._get(
            f"/api/v1/tasks/?project={pid}&status={status}",
            name="GET /tasks/?project=X&status=Y"
        )

    @task(2)
    def filter_tasks_by_priority(self):
        if not self.project_ids:
            return
        pid = random.choice(self.project_ids)
        priority = random.choice(TASK_PRIORITY)
        self._get(
            f"/api/v1/tasks/?project={pid}&priority={priority}",
            name="GET /tasks/?project=X&priority=Y"
        )

    @task(2)
    def get_project_detail(self):
        if not self.project_ids:
            return
        pid = random.choice(self.project_ids)
        self._get(f"/api/v1/projects/{pid}/", name="GET /projects/{id}/")

    @task(1)
    def search_tasks(self):
        if not self.project_ids:
            return
        pid = random.choice(self.project_ids)
        self._get(
            f"/api/v1/tasks/?project={pid}&search=task",
            name="GET /tasks/?search=X"
        )

    @task(1)
    def update_task_status(self):
        """Occasional status toggle — simulates kanban drag-drop."""
        if not self.project_ids:
            return
        pid = random.choice(self.project_ids)
        res = self._get(f"/api/v1/tasks/?project={pid}&page_size=5", name="GET /tasks/ [for update]")
        if res.status_code != 200:
            return
        tasks = res.json().get("results", [])
        if not tasks:
            return
        task = random.choice(tasks)
        self._patch(
            f"/api/v1/tasks/{task['id']}/",
            json={"status": random.choice(TASK_STATUSES)},
            name="PATCH /tasks/{id}/ [status]"
        )


# ── Write-heavy user (30% of traffic) ────────────────────────────────────────
class WriteHeavyUser(AuthenticatedUser):
    """
    Simulates a developer actively creating and updating work:
      - creates tasks, leaves comments, updates priorities
      - refreshes token mid-session
    Weight 30 → 30% of simulated users are this type.
    """
    weight = 30
    wait_time = between(1.0, 3.0)

    @task(3)
    def create_task(self):
        if not self.project_ids:
            self._fetch_projects()
            return
        pid = random.choice(self.project_ids)
        payload = {
            "project": pid,
            "title": f"Load test task {random_string(6)}",
            "description": "Created during load test run",
            "status": random.choice(["todo", "backlog"]),
            "priority": random.choice(TASK_PRIORITY),
        }
        with self.client.post(
            "/api/v1/tasks/",
            json=payload,
            headers=self._headers(),
            catch_response=True,
            name="POST /tasks/",
        ) as res:
            if res.status_code == 201:
                task_id = res.json().get("id")
                if task_id:
                    self._add_comment(task_id)
                res.success()
            elif res.status_code == 401:
                self._refresh()
                res.failure("401 on create — refreshed")
            else:
                res.failure(f"Create task failed: {res.status_code} — {res.text[:200]}")

    @task(2)
    def update_task(self):
        if not self.project_ids:
            return
        pid = random.choice(self.project_ids)
        res = self._get(f"/api/v1/tasks/?project={pid}&page_size=10", name="GET /tasks/ [write user]")
        if res.status_code != 200:
            return
        tasks = res.json().get("results", [])
        if not tasks:
            return
        task = random.choice(tasks)
        self._patch(
            f"/api/v1/tasks/{task['id']}/",
            json={
                "status": random.choice(TASK_STATUSES),
                "priority": random.choice(TASK_PRIORITY),
            },
            name="PATCH /tasks/{id}/ [write user]"
        )

    @task(2)
    def bulk_status_update(self):
        if not self.project_ids:
            return
        pid = random.choice(self.project_ids)
        res = self._get(f"/api/v1/tasks/?project={pid}&page_size=20", name="GET /tasks/ [bulk]")
        if res.status_code != 200:
            return
        tasks = res.json().get("results", [])
        if len(tasks) < 2:
            return
        ids = [t["id"] for t in random.sample(tasks, min(5, len(tasks)))]
        self._post(
            "/api/v1/tasks/bulk-status/",
            json={"task_ids": ids, "status": random.choice(TASK_STATUSES)},
            name="POST /tasks/bulk-status/"
        )

    @task(1)
    def create_project(self):
        payload = {
            "name": f"Load test project {random_string(5)}",
            "description": "Auto-created during load test",
        }
        with self.client.post(
            "/api/v1/projects/",
            json=payload,
            headers=self._headers(),
            catch_response=True,
            name="POST /projects/",
        ) as res:
            if res.status_code == 201:
                new_id = res.json().get("id")
                if new_id:
                    self.project_ids.append(new_id)
                res.success()
            elif res.status_code == 401:
                self._refresh()
                res.failure("401 on project create — refreshed")
            else:
                res.failure(f"Create project failed: {res.status_code}")

    @task(1)
    def get_me(self):
        self._get("/api/v1/auth/me/", name="GET /auth/me/")

    def _add_comment(self, task_id):
        self._post(
            f"/api/v1/tasks/{task_id}/comments/",
            json={"body": f"Load test comment {random_string(10)}"},
            name="POST /tasks/{id}/comments/"
        )


# ── Auth spike user — tests login/logout throughput ───────────────────────────
class AuthSpikeUser(AuthenticatedUser):
    """
    Simulates login storms (deployments, Monday mornings).
    Low weight — just 1 in every ~10 simulated users.
    """
    weight = 10
    wait_time = between(2.0, 5.0)

    @task(1)
    def login_logout_cycle(self):
        email    = f"spike_{random_string(6)}@test.com"
        password = "SpikePass1!"

        # Register a fresh account
        with self.client.post(
            "/api/v1/auth/register/",
            json={
                "email": email,
                "full_name": "Spike User",
                "password": password,
                "password2": password,
            },
            catch_response=True,
            name="POST /auth/register/ [spike]",
        ) as res:
            if res.status_code not in (201, 400):
                res.failure(f"Register failed: {res.status_code}")
                return
            if res.status_code == 400:
                res.success()  # email collision — acceptable
                return
            data = res.json()
            token   = data["tokens"]["access"]
            refresh = data["tokens"]["refresh"]
            res.success()

        # Immediately logout — blacklist the refresh token
        with self.client.post(
            "/api/v1/auth/logout/",
            json={"refresh": refresh},
            headers={"Authorization": f"Bearer {token}"},
            catch_response=True,
            name="POST /auth/logout/ [spike]",
        ) as res:
            if res.status_code == 200:
                res.success()
            else:
                res.failure(f"Logout failed: {res.status_code}")


# ── Event hooks for summary reporting ────────────────────────────────────────
@events.quitting.add_listener
def on_quitting(environment, **kwargs):
    stats = environment.stats
    total = stats.total
    if total.num_requests == 0:
        return
    print("\n" + "═" * 60)
    print("  LOAD TEST SUMMARY")
    print("═" * 60)
    print(f"  Total requests : {total.num_requests}")
    print(f"  Failures       : {total.num_failures}  ({100*total.num_failures/max(total.num_requests,1):.2f}%)")
    print(f"  Median (p50)   : {total.median_response_time:.0f}ms")
    print(f"  p95            : {total.get_response_time_percentile(0.95):.0f}ms")
    print(f"  p99            : {total.get_response_time_percentile(0.99):.0f}ms")
    print(f"  RPS            : {total.current_rps:.1f}")
    print("═" * 60)
