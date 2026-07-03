<p align="center">
  <img src="docs/logo.svg" alt="TaskForge logo" width="110"/>
</p>

# TaskForge Backend

[![CI](https://github.com/Abdullah-Masood-05/taskforge-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/Abdullah-Masood-05/taskforge-backend/actions)  
[![Code coverage](https://codecov.io/gh/Abdullah-Masood-05/taskforge-backend/branch/main/graph/badge.svg)](https://codecov.io/gh/Abdullah-Masood-05/taskforge-backend)

---

## Table of Contents
- [About](#about)
- [Architecture Overview](#architecture-overview)
- [Features Implemented (Phase 1)](#features-implemented-phase1)
- [Quick Start (Docker)](#quick-start-docker)
- [Local Development](#local-development)
- [Testing](#testing)
- [API Documentation](#api-documentation)
- [Demo Credentials](#demo-credentials)
- [Contributing](#contributing)
- [License](#license)

---

## About
**TaskForge** is a multi‑tenant project‑management SaaS backend built with **Django 5**, **Django REST Framework**, **PostgreSQL**, and **Redis**.  The service provides robust role‑based access control (RBAC), custom JWT authentication, and tenant isolation using row‑level permissions.

---

## Architecture Overview
The repository contains a single Django project that is deliberately split into reusable apps.  Key architectural decisions include:
- **Row‑level multi‑tenancy** – a single database schema with tenant identifiers (`Organization`, `Membership`). This simplifies migrations and analytics while maintaining strong isolation.
- **Custom JWT workflow** – thin wrappers around `simplejwt` for full control over token payloads and blacklisting on logout.
- **Dual organization resolution** – tenant can be supplied via URL slug or the `X-Organization-Slug` header, giving flexibility to front‑end clients.
- **Security hardening** – integrations such as `django‑axes` protect against brute‑force attacks.
- **Dockerised development** – multi‑stage Dockerfile and `docker‑compose.yml` enable reproducible local environments.

---

## Features Implemented (Phase 1)
| Feature | Status | Description |
|---|---|---|
| Custom User model | ✅ | Email‑based login, UUID primary key, extensible fields |
| Settings split | ✅ | Environment‑specific settings (`base.py`, `dev.py`, `prod.py`) |
| Custom JWT auth | ✅ | SimpleJWT with token blacklisting |
| Google OAuth2 | ✅ | Social login via `django‑allauth` & `dj‑rest‑auth` |
| Multi‑tenancy | ✅ | Row‑level tenant isolation via `Organization` & `Membership` |
| RBAC permissions | ✅ | DRF permission classes (`IsOrgAdmin`, `IsOrgMember`, `IsOrgViewer`) |
| CurrentOrg middleware | ✅ | Auto‑detect tenant from slug or header |
| Brute‑force protection | ✅ | `django‑axes` integration |
| Health check endpoint | ✅ | `/api/v1/health/` validates DB & Redis |
| OpenAPI documentation | ✅ | Swagger UI (`/api/v1/docs/`) and Redoc (`/api/v1/redoc/`) |
| Test suite | ✅ | `pytest` with `factory_boy`; >80 % coverage |
| Docker development | ✅ | Multi‑stage Dockerfile + Compose |
| CI workflow | ✅ | GitHub Actions for linting, security scans, tests |
| Demo data seeding | ✅ | `python manage.py seed` creates reproducible demo data |

---

## Quick Start (Docker)
```bash
# 1. Copy the example environment file and adjust values as needed
cp .env.example .env

# 2. Build and start the services
docker compose up --build -d

# 3. Run migrations and seed demo data (handled automatically on first start, but can be run manually)
# docker compose exec web python manage.py migrate
# docker compose exec web python manage.py seed
```
The API documentation will be available at:
- **Swagger UI**: <http://localhost:8000/api/v1/docs/>  
- **Redoc**: <http://localhost:8000/api/v1/redoc/>

---

## Local Development
If you prefer a non‑Docker workflow:
```bash
# 1. Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows use `.venv\Scripts\activate`

# 2. Install development dependencies
pip install -r requirements/dev.txt

# 3. Set up a PostgreSQL database and Redis instance (default ports are 5432 and 6379)
#    Configure connection details in a `.env` file based on `.env.example`

# 4. Apply migrations and load seed data
python manage.py migrate
python manage.py seed

# 5. Start the development server
C:\Users\Abdullah Masood\Documents\Installer\Rectify11Installe
```

---

## Demo / Screenshot Data
`seed` creates the org and users; `seed_demo_project` fills it with a large,
realistic showcase board — **"Platform Relaunch Q1"** — built to fully populate
the project dashboard (Kanban columns, timeline, velocity chart, priority
distribution and activity feed):

```bash
python manage.py seed_demo_project --large-project --reset
```

What it seeds:
- 8 demo team members with stable avatar URLs (deterministic per email)
- 5 columns (Backlog, To-Do, In Progress, In Review, Done — Done is terminal)
- 7 colored labels and ~150 tasks with 1–3 assignees, labels, priorities,
  start/due dates spread over the next 8 months, and progress on
  in-progress cards
- ~200 backfilled activity-log entries across the past weeks, so the
  activity feed and velocity chart have data immediately

Flags: `--large-project` seeds the full ~150-task board (default ~50);
`--reset` deletes and recreates just this demo project, leaving all other
orgs/projects untouched. Log in as `admin@taskforge.dev` and open the
project board to see the populated dashboard.

---

## Testing
```bash
# Using the Docker environment (recommended for CI consistency)
docker compose exec web pytest

# Or locally (ensure the test database is configured)
pytest
```
The test suite includes unit, integration, and API tests with a target of 80 %+ coverage.

---

## API Documentation
Interactive documentation is generated automatically via **drf‑spectacular**:
- Swagger UI: <http://localhost:8000/api/v1/docs/>
- Redoc: <http://localhost:8000/api/v1/redoc/>

All endpoints are versioned under the `/api/v1/` prefix.

---

## Demo Credentials
| Role | Email | Password |
|---|---|---|
| Admin | `admin@taskforge.dev` | `TaskForge2024!` |
| Member | `alice@taskforge.dev` | `TaskForge2024!` |
| Viewer | `bob@taskforge.dev` | `TaskForge2024!` |

Demo organization slug: **`taskforge-demo`**

---

## Contributing
Contributions are welcome! Please follow these steps:
1. Fork the repository and clone your fork.
2. Create a feature branch (`git checkout -b feature/your-feature`).
3. Write tests for any new functionality.
4. Ensure the full test suite passes (`pytest`).
5. Open a Pull Request with a clear description of the changes.

Please adhere to the existing code style (PEP 8) and run the linters (`flake8` and `black`) before submitting.

---

## License
This project is licensed under the **MIT License** – see the [LICENSE](LICENSE) file for details.
