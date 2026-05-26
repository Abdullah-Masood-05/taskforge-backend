# TaskForge Backend

> Multi-tenant project management SaaS API — built with Django 5, DRF, PostgreSQL, and Redis.

[![CI](https://github.com/Abdullah-Masood-05/taskforge-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/Abdullah-Masood-05/taskforge-backend/actions)

---

## Architecture

This repository contains the backend REST API service for **TaskForge**. It is designed with robust multi-tenancy, clean role-based access control (RBAC), custom JWT security, and a modular architecture.

---

## Phase 1 — What's Implemented

| Feature | Status | Description |
|---|---|---|
| **Custom User model** | ✅ | Email-based login, UUID primary keys, and extensible fields. |
| **Settings Split** | ✅ | Environment-aware settings split (`base.py`, `dev.py`, `prod.py`). |
| **Custom JWT Auth** | ✅ | Thin views wrapping simplejwt with strict token blacklisting. |
| **Google OAuth2** | ✅ | Social login callback bridge via `django-allauth` + `dj-rest-auth`. |
| **Multi-Tenancy** | ✅ | Row-level tenant isolation using `Organization` and `Membership` models. |
| **Role-based Permissions** | ✅ | custom DRF permission classes (`IsOrgAdmin`, `IsOrgMember`, `IsOrgViewer`). |
| **CurrentOrgMiddleware** | ✅ | Automatic org resolution from URL slug or `X-Organization-Slug` header. |
| **Brute Force Protection** | ✅ | Integration of `django-axes` for secure login attempts. |
| **Health Check** | ✅ | `/api/v1/health/` checking database and Redis status. |
| **OpenAPI Docs** | ✅ | Auto-generated Swagger UI (`/api/v1/docs/`) and Redoc. |
| **Robust Testing** | ✅ | Full `pytest` integration with `factory_boy` and 80%+ test coverage. |
| **Docker Development** | ✅ | Fully configured multi-stage Dockerfile and Docker Compose environment. |
| **CI Workflow** | ✅ | Automated GitHub Actions executing code linting, security scans, and tests. |
| **Demo Data Seeding** | ✅ | `python manage.py seed` command to inject instant idempotent demo data. |

---

## Quick Start (dockerized)

Get up and running in a few simple steps:

```bash
# 1. Copy the example environment file
cp .env.example .env

# 2. Build and start services
docker compose up --build

# 3. (Optional) Run migrations and seed data manually if not done automatically
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed
```

Once running, the interactive API documentation will be available at:
- **Swagger UI**: [http://localhost:8000/api/v1/docs/](http://localhost:8000/api/v1/docs/)
- **Redoc**: [http://localhost:8000/api/v1/redoc/](http://localhost:8000/api/v1/redoc/)

---

## Demo Credentials (after seeding)

| Role | Email | Password |
|---|---|---|
| **Admin** | `admin@taskforge.dev` | `TaskForge2024!` |
| **Member** | `alice@taskforge.dev` | `TaskForge2024!` |
| **Viewer** | `bob@taskforge.dev` | `TaskForge2024!` |

Demo Organization Slug: `taskforge-demo`

---

## API Endpoints (Phase 1)

```text
POST   /api/v1/auth/register/
POST   /api/v1/auth/login/
POST   /api/v1/auth/token/refresh/
POST   /api/v1/auth/logout/
GET    /api/v1/auth/me/
PUT    /api/v1/auth/me/
POST   /api/v1/auth/change-password/

GET    /api/v1/organizations/
POST   /api/v1/organizations/
GET    /api/v1/organizations/{slug}/
PATCH  /api/v1/organizations/{slug}/
DELETE /api/v1/organizations/{slug}/

GET    /api/v1/organizations/{slug}/members/
POST   /api/v1/organizations/{slug}/members/
PATCH  /api/v1/organizations/{slug}/members/{id}/
DELETE /api/v1/organizations/{slug}/members/{id}/

GET    /api/v1/health/
GET    /api/v1/docs/
GET    /api/v1/redoc/
```

---

## Running Tests Locally (Non-Docker)

Ensure you have a PostgreSQL database and Redis server running locally, then:

```bash
# 1. Install dependencies
pip install -r requirements/dev.txt

# 2. Run test suite
pytest
```

---

## Architectural & Design Decisions

- **Row-level multi-tenancy** — Chosen over schema-per-tenant (`django-tenant-schemas`) to maintain ease of operations (single database migrations, straightforward querying for platform analytics) and high performance. Enforced robustly at the permission and middleware levels.
- **Enriched Custom JWT Views** — Thin wrapper views around `django-rest-framework-simplejwt` were built directly rather than relying fully on `dj-rest-auth` views. This allows complete control over the token's response shape and claims without invasive monkey-patching.
- **Dual Org Resolution** — Resolves active tenant from either the URL slug first or falls back to an `X-Organization-Slug` HTTP header. This ensures API calls are flexible and painless for frontend integration.
- **Token Blacklisting on Logout** — Utilizing simplejwt's token blacklist middleware for robust invalidation of sessions upon logout.
