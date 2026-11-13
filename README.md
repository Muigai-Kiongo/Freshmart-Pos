# Freshmart POS

Freshmart POS is a Kenyan point-of-sale project. The backend is built with
FastAPI, PostgreSQL, Redis, SQLAlchemy async, and Alembic. Authentication
includes owner signup, staff PIN login, offline unlock, and owner/admin
password authentication with TOTP and password recovery. Sales, catalog,
M-Pesa, reporting, and full business/device administration are out of scope.

## Project status

- Authentication foundation: implemented (database models/migrations and
  security utilities).
- Signup, staff PIN auth, offline unlock, and owner/admin auth: implemented
  with unit/API tests.
- Admin refresh-cookie/CSRF transport and device-pairing endpoints: not
  implemented; the cookie-mode setting is reserved and does not enable cookie
  transport.
- Static development seed users: not provided; create the initial owner
  through signup.
- Sales, inventory, M-Pesa, reports, and full device administration: not
  implemented.

## Quick start

Clone the repository (or use your existing checkout), then, from the
repository root, copy the example environment file and replace the
development values with local secrets:

```powershell
git clone https://github.com/Muigai-Kiongo/Freshmart-Pos.git
Set-Location Freshmart-Pos
Copy-Item backend\.env.example backend\.env
docker compose --env-file backend\.env up -d
Set-Location backend
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The API listens at `http://127.0.0.1:8000`; Swagger UI is at
`http://127.0.0.1:8000/docs`. `backend/.env` must contain unique local
secrets; never use the example values in production.

The first owner account is created through the signup endpoints. In
non-production environments, the development SMS provider accepts OTP
`000000`; this shortcut is disabled in production. The owner chooses their
own password and PIN during signup. There are no preconfigured user
credentials.

There is no development seed-account script in this module. Do not
expect fixed owner, cashier, or platform-admin credentials; create the
initial owner through signup.

## Environment variables

| Name | Purpose | Example | Required |
| --- | --- | --- | --- |
| `ENVIRONMENT` | Runtime environment | `development` | No |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Local PostgreSQL container credentials/database | Set unique local values in `backend/.env` | For Docker |
| `DATABASE_URL` | Async PostgreSQL connection | `postgresql+asyncpg://<user>:<password>@localhost:5432/dazu_pos` | Yes |
| `REDIS_URL` | Redis connection for rate limits and ephemeral auth state | `redis://localhost:6379/0` | Yes |
| `JWT_ISSUER` | JWT issuer claim | `dazu-pos` | No |
| `JWT_KID` | Current signing-key identifier | `v1` | No |
| `JWT_STAFF_SECRET` | Staff-token signing secret (32+ characters) | `replace-with-a-random-secret` | Yes |
| `JWT_ADMIN_SECRET` | Admin-token signing secret (32+ characters) | `replace-with-a-random-secret` | Yes |
| `JWT_SIGNUP_SECRET` | Signup-token signing secret (32+ characters) | `replace-with-a-random-secret` | Yes |
| `JWT_RESET_SECRET` | Reset-token signing secret (32+ characters) | `replace-with-a-random-secret` | Yes |
| `JWT_STAFF_SECRETS`, `JWT_ADMIN_SECRETS`, `JWT_SIGNUP_SECRETS`, `JWT_RESET_SECRETS` | Optional comma-separated `kid:secret` key-rotation sets | `v1:old-secret,v2:new-secret` | No |
| `PIN_PEPPER` | Server-side PIN pepper | `replace-with-a-random-secret` | Yes |
| `OTP_PEPPER` | OTP hashing pepper | `replace-with-a-random-secret` | Yes |
| `MFA_ENCRYPTION_KEY` | Fernet key for TOTP secrets | Generate with `Fernet.generate_key()` | For MFA |
| `OTP_TTL_SECONDS` | OTP validity period | `300` | No |
| `OTP_RESEND_COOLDOWN_SECONDS` | OTP resend cooldown | `60` | No |
| `OTP_MAX_RESENDS` | Maximum resends per challenge | `3` | No |
| `OTP_MAX_ATTEMPTS` | Maximum OTP verification attempts | `5` | No |
| `OTP_PHONE_HOURLY_LIMIT` | OTP sends per phone per hour | `3` | No |
| `OTP_IP_HOURLY_LIMIT` | OTP sends per IP per hour | `20` | No |
| `OTP_GLOBAL_DAILY_LIMIT` | Global OTP send cap per day | `10000` | No |
| `SIGNUP_CAPTCHA_THRESHOLD` | Signup starts per IP before CAPTCHA | `5` | No |
| `ALLOWED_PHONE_PREFIXES` | Accepted Kenyan phone prefixes | `2547,2541` | No |
| `ADMIN_COOKIE_MODE` | Reserved admin cookie-mode setting; cookie transport/CSRF are not implemented | `false` | No |
| `CORS_ORIGINS` | Comma-separated CORS allowlist | `http://localhost:3000,http://localhost:5173` | No |
| `AT_API_KEY`, `AT_USERNAME` | Africa's Talking credentials | Set in deployment secret store | For production SMS |
| `AT_SENDER_ID` | SMS sender ID | `DAZU` | No |
| `TURNSTILE_SECRET` | Optional Cloudflare Turnstile secret | Set in deployment secret store | No |
| `ARGON2_TIME_COST`, `ARGON2_MEMORY_KIB`, `ARGON2_PARALLELISM` | Argon2id work factors | `3`, `65536`, `2` | No |
| `TRIAL_DAYS` | New-business trial duration | `14` | No |
| `STAFF_ACCESS_MINUTES`, `ADMIN_ACCESS_MINUTES` | Staff/admin access token duration | `15`, `10` | No |
| `STAFF_REFRESH_DAYS`, `ADMIN_REFRESH_DAYS` | Staff/admin refresh token duration | `30`, `7` | No |
| `SIGNUP_TOKEN_MINUTES`, `RESET_TOKEN_MINUTES` | Signup/reset token duration | `15`, `15` | No |
| `OFFLINE_UNLOCK_MAX_DAYS` | Maximum offline unlock duration | `7` | No |
| `LOCKOUT_FAILURES`, `LOCKOUT_BASE_SECONDS` | Failed-login threshold and base lockout | `5`, `900` | No |
| `PIN_LOGIN_IP_LIMIT`, `PIN_LOGIN_DEVICE_LIMIT` | PIN login attempts per minute | `60`, `30` | No |
| `ADMIN_LOGIN_IP_LIMIT` | Admin login attempts per minute | `30` | No |
| `PASSWORD_RESET_PHONE_HOURLY_LIMIT`, `PASSWORD_RESET_IP_HOURLY_LIMIT`, `PASSWORD_RESET_GLOBAL_DAILY_LIMIT` | Password-reset OTP caps | `3`, `20`, `10000` | No |

## Backend structure

- `backend/app/api/routers` — signup, staff-auth, and admin-auth routes
- `backend/app/api/schemas` — validated request and response models
- `backend/app/api/dependencies.py` — auth service and reusable auth dependencies
- `backend/app/core` — settings, JWT, hashing, phone/OTP/PIN validation,
  lockout, rate limiting, localization, and crypto
- `backend/app/db` — async SQLAlchemy and Redis connections
- `backend/app/integrations` — SMS provider interface and implementations
- `backend/app/models` — business, staff, device, OTP, session, and audit models
- `backend/app/services` — signup, staff-auth, and admin-auth business logic
- `backend/alembic` — database migrations
- `backend/tests/unit` — unit and API tests
- `backend/scripts` — API schema export script
- `backend/docs` — auth flows and API collection

## API overview

Interactive API documentation: [Swagger UI](http://127.0.0.1:8000/docs).
The exported contract is `backend/docs/openapi.json` (generated by
`backend/scripts/export_openapi.py`).

| Area | Endpoint overview |
| --- | --- |
| Signup | `POST /api/v1/auth/signup/start`, `/signup/verify-otp`, `/otp/resend`, `/signup/complete` |
| Staff auth | `GET /api/v1/auth/staff-list`, `POST /api/v1/auth/pin-login`, `/refresh`, `/logout`, `/logout-all`, `/change-pin` |
| Sessions and profile | `GET /api/v1/auth/sessions`, `DELETE /api/v1/auth/sessions/{id}`, `GET /api/v1/auth/me` |
| Offline unlock | `POST /api/v1/auth/offline-unlock/issue`, `/offline-unlock/revoke`, `/offline-sessions/sync` |
| Admin auth | `POST /api/v1/admin/auth/login`, `/refresh`, `/logout`, `/logout-all`, `/change-password`, `/reset-own-pin` |
| Admin MFA and reset | `POST /api/v1/admin/auth/2fa/setup`, `/2fa/enable`, `/2fa/disable`, `/password-reset/start`, `/password-reset/verify-otp`, `/password-reset/complete` |

The staff PIN and session endpoints require a registered device token.
Admin access tokens use a distinct audience and signing secret from staff
tokens. The configured admin cookie mode is not active: admin refresh tokens
are currently returned in JSON, and cookie/CSRF handling is not implemented.

## Authentication lifetimes and limits

| Credential or rule | Lifetime / limit |
| --- | --- |
| OTP | 5 minutes; 5 verification attempts |
| OTP resend | 60-second cooldown; 3 resends per challenge |
| OTP sends per phone | 3 per hour |
| OTP sends per IP | 20 per hour |
| OTP global cap | 10,000 per day |
| Signup and password-reset tokens | 15 minutes |
| Staff access token | 15 minutes |
| Staff refresh token | 30 days |
| Admin access token | 10 minutes |
| Admin refresh token | 7 days |
| Offline unlock | Up to 7 days |
| PIN login | 60 requests/IP/minute; 30 requests/device/minute |
| Admin login | 30 requests/IP/minute |
| Password-reset sends | 3 per phone/hour; 20 per IP/hour; 10,000 global/day |
| PIN/password lockout | 5 failures; 15-minute base duration, escalating |

Rate-limit settings can be adjusted with the corresponding `OTP_*`,
`PIN_LOGIN_*`, `ADMIN_LOGIN_*`, `PASSWORD_RESET_*`, and `LOCKOUT_*`
environment variables.

## Error codes

| Code | Meaning |
| --- | --- |
| `INVALID_CREDENTIALS` | Credentials or access token are invalid |
| `ACCOUNT_LOCKED` | Login is temporarily locked; retry information is included |
| `OTP_INVALID` | OTP is incorrect |
| `OTP_EXPIRED` | OTP challenge has expired |
| `OTP_TOO_MANY_ATTEMPTS` | OTP challenge exceeded its attempt limit |
| `RATE_LIMITED` | Request limit has been reached |
| `DEVICE_REVOKED` | Device or device-bound session has been revoked |
| `DEVICE_NOT_REGISTERED` | A valid registered device is required |
| `BUSINESS_SUSPENDED` | Business is suspended |
| `MFA_REQUIRED` | Multi-factor authentication is required |
| `WEAK_PASSWORD` | Password does not meet the password policy |
| `WEAK_PIN` | PIN does not meet the PIN policy |
| `TOKEN_REUSED` | Rotated refresh token was presented again |
| `VALIDATION_ERROR` | Request fields are invalid |

Messages are localized in English and Kiswahili based on `Accept-Language`.

## Development and tests

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing
```

The suite uses SQLite and fake Redis for unit/API testing. PostgreSQL and
Redis are started with Docker Compose for local integration and migration
work. Ruff and mypy are the configured repository checks when installed:

```powershell
ruff check .
ruff format --check .
mypy app
```

## Auth flow documentation

See [backend/docs/auth-flows.md](backend/docs/auth-flows.md) for signup,
PIN login, offline unlock, refresh rotation, password reset, and device
pairing flow diagrams. Device pairing is documented as a future integration;
there is currently no pairing endpoint or pairing-code seed route. The Bruno examples are in
`backend/docs/bruno-auth-collection.json`.

## Changelog

- 2026-11-13: Delivered backend authentication endpoints, security
  foundations, migrations, tests, and API/auth documentation. Cookie/CSRF
  transport, pairing endpoints, and seed users remain out of scope.
