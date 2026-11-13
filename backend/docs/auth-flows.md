# Authentication flows

## Signup
```mermaid
sequenceDiagram
    participant Client
    participant API as Freshmart API
    participant SMS as SMS Provider
    participant DB as PostgreSQL

    Client->>API: POST /api/v1/auth/signup/start { phone }
    API->>DB: create OTP challenge
    API->>SMS: send OTP code
    SMS-->>Client: SMS delivered
    Client->>API: POST /api/v1/auth/signup/verify-otp { challenge_id, otp }
    API-->>Client: signup_token (15m, single-use)
    Client->>API: POST /api/v1/auth/signup/complete { ... } with Idempotency-Key
    API->>DB: create business, outlet, owner, device, settings
    API-->>Client: access_token, refresh_token, business + outlet
```

## PIN login
```mermaid
sequenceDiagram
    participant Client
    participant API
    participant Redis
    participant DB

    Client->>API: GET /api/v1/auth/staff-list with X-Device-Token
    API->>DB: verify active device and outlet membership
    API-->>Client: staff list
    Client->>API: POST /api/v1/auth/pin-login { staff_id, pin }
    API->>Redis: check I.P./device rate limits
    API->>DB: validate PIN and business status
    API-->>Client: access token + refresh token
```

## Offline unlock
```mermaid
sequenceDiagram
    participant Client
    participant API
    participant DB

    Client->>API: POST /api/v1/auth/offline-unlock/issue { pin }
    API->>DB: verify current PIN and device
    API-->>Client: salt + expires_at
    Client->>Client: derive verifier locally
    Client->>API: POST /api/v1/auth/offline-sessions/sync { sessions }
    API->>DB: record audit trail
```

## Token refresh with reuse detection
```mermaid
sequenceDiagram
    participant Client
    participant API
    participant DB

    Client->>API: POST /api/v1/auth/refresh { refresh_token }
    API->>DB: locate refresh token family
    API->>DB: revoke old token and mint replacement
    API-->>Client: new access + refresh
    Client->>API: POST /api/v1/auth/refresh with old token
    API->>DB: detect family reuse
    API->>DB: revoke entire token family
    API-->>Client: TOKEN_REUSED
```

## Password reset
```mermaid
sequenceDiagram
    participant Client
    participant API
    participant SMS
    participant DB

    Client->>API: POST /api/v1/admin/auth/password-reset/start { phone }
    API->>DB: create password-reset challenge
    API->>SMS: send reset code
    Client->>API: POST /api/v1/admin/auth/password-reset/verify-otp { challenge_id, otp }
    API-->>Client: reset_token
    Client->>API: POST /api/v1/admin/auth/password-reset/complete { reset_token, new_password }
    API->>DB: validate single-use token and revoke sessions
    API-->>Client: success
```

## Device pairing
```mermaid
sequenceDiagram
    participant Client
    participant API
    participant DB

    Client->>API: POST /api/v1/devices/pair { pairing_code, device_name, platform }
    API->>DB: validate one-time code and business match
    API-->>Client: device_token
```

## Rate limits and lockouts
| Scope | Rule |
| --- | --- |
| OTP per phone | 3 per hour |
| OTP per IP | 20 per hour |
| OTP global daily | 10000/day |
| PIN login IP | 60/min |
| PIN login device | 30/min |
| Admin login IP | 30/min |
| Password-reset phone | 3/hour |
| Password-reset IP | 20/hour |
| Lockout failures | 5 before lock |
| Lockout duration | 15 min, escalating |
| Staff access token | 15 min |
| Admin access token | 10 min |
| Staff refresh token | 30 days |
| Admin refresh token | 7 days |
| Signup token | 15 min |
| Reset token | 15 min |
| Offline unlock | max 7 days |

## Notes
- The dev OTP code is accepted only in non-production.
- Reset and signup OTPs are never stored in plaintext.
- Admin refresh-cookie transport and CSRF validation are not implemented. `ADMIN_COOKIE_MODE` is a reserved setting and does not activate cookie behavior.
- Device pairing is shown as a future integration flow; no pairing endpoint or pairing-code generation route is currently included.
