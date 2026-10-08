# Security

This document records the security design and the OWASP ASVS level 1 review. It is updated at the end of each phase that changes the attack surface. The Phase 17 penetration style checks and scan results are appended here.

## Authentication

| Topic | Implementation |
|---|---|
| Registration | Patients only. The role is never accepted from the client (unknown fields are rejected). The response is identical whether or not the address is already registered; an existing address receives an "account already exists" email instead. |
| Email verification | One time token, 256 bits, only its SHA-256 hash is stored, valid 24 hours. Login is refused until the address is verified. |
| Password policy | Minimum 12 characters, maximum 128, checked against a list of common passwords, rejected when it consists of three or fewer distinct characters or contains the email name. |
| Hashing | argon2id (`argon2-cffi`), time cost 3, memory 64 MiB, parallelism 2 by default, all configurable. Hashes are upgraded on login when parameters change. |
| Access token | JWT (HS256), 15 minutes, held in memory by the frontend. Claims: subject, role, MFA flag, token type, `jti`, issuer, issued and expiry times. The role claim is informational: authorization always reads the role from the database, so a demoted or deactivated user loses access immediately. |
| Refresh token | Opaque random value in an `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth` cookie, 14 days, stored only as a hash. |
| Rotation and reuse detection | Every refresh issues a new token in the same family and revokes the old one. Presenting an already revoked token revokes the entire family and writes an audit entry. |
| Lockout | Five failed attempts lock the account for 15 minutes. The response is the same generic message in every failure case, including while locked. An unknown email still performs a password hash verification so timing does not reveal which accounts exist. |
| Password reset | One time token, hash stored, valid 30 minutes. A new request invalidates earlier links. A successful reset ends all sessions. |
| MFA | TOTP (RFC 6238, 6 digits, 30 seconds, one step of drift tolerated). Mandatory for admin and dentist: without it, login returns a limited `mfa_setup` token that can only complete enrolment. Optional for other roles. Eight single use recovery codes, stored as argon2id hashes. The TOTP secret is encrypted at rest. Used codes cannot be replayed within 90 seconds. Failed MFA attempts count towards lockout. |
| Token separation | Access, MFA challenge and MFA setup tokens carry a type claim; a token is accepted only for its own purpose. |

Endpoints: `/auth/register`, `/auth/verify-email`, `/auth/login`, `/auth/mfa/verify`, `/auth/mfa/setup`, `/auth/mfa/enable`, `/auth/mfa/disable`, `/auth/refresh`, `/auth/logout`, `/auth/forgot`, `/auth/reset`, `/auth/password`, `/auth/me`.

## Authorization

Role checks use the `require_roles(...)` dependency. Object level checks are performed in the service layer.

| Resource | patient | receptionist | dentist | admin |
|---|---|---|---|---|
| Own profile and appointments (`/me/...`) | read, write | - | - | - |
| Staff schedule and booking for patients | - | read, write | read (own chair), complete or no show | read, write |
| Patient records (`/patients`) | - | read, write | read, only patients they treat | read, write |
| Audit logs | - | - | - | read |
| User roles | - | - | - | write (not their own) |

A dentist requesting a patient they do not treat receives 404, indistinguishable from a missing record. Patients reach appointments and invoices only through `/me/...` routes that filter by their own patient id, and another patient's appointment is reported as 404. Dentists change the status of their own appointments only. Each of these has negative tests.

Role changes end the user's sessions and are audited. A user promoted to a role that requires MFA must enrol before any access token is accepted.

## Data protection

- **Field encryption.** AES-256-GCM through `cryptography`. Stored as `<key_id>:<base64url(nonce || ciphertext)>`. The column name is bound into the authenticated data so a value cannot be moved between fields. Covered fields: date of birth, phone, address, insurance member id, MFA secret. Keys come from `FIELD_ENCRYPTION_KEY`; older keys are listed in `FIELD_ENCRYPTION_OLD_KEYS` so rotation never makes data unreadable. Generate keys with `python -m scripts.generate_encryption_key <id>`. Production refuses to start without a key and without a strong `JWT_SECRET`.
- **Transport and headers.** Caddy terminates TLS and sets HSTS, a content security policy, `X-Content-Type-Options`, `Referrer-Policy` and `Permissions-Policy`. The API sets the same headers itself (HSTS only in production) with a `default-src 'none'` policy and `Cache-Control: no-store`.
- **CORS** uses an allowlist from `CORS_ORIGINS`. Credentials are allowed only for those origins.
- **CSRF.** `SameSite=Strict` on the refresh cookie, plus a double submit token (`csrf_token` cookie echoed in `X-CSRF-Token`) and an `Origin` allowlist check on `/auth/refresh` and `/auth/logout`. Other endpoints authenticate with a bearer header and are not exposed to CSRF.
- **Rate limiting** (Redis, fixed window): login 5 per minute per IP and per account (MFA verification per user), public booking 20 per hour per IP, chat 30 per minute per session, contact form 5 per hour. Registration, verification email and password reset requests are limited per IP and per address. Limits are settings. Responses carry `Retry-After`. Rate limiting depends on the real client address: behind the reverse proxy set `FORWARDED_ALLOW_IPS` to the proxy address so `X-Forwarded-For` is trusted only from it.
- **Audit log.** Recorded: login, failed login, lockout, logout, registration, email verification, password change and reset request, MFA changes and failures, refresh token reuse, staff record views, searches and changes, profile changes, role changes, audit log views. Metadata is passed through an allowlist filter that drops any key resembling a credential or personal data, and failed logins for unknown addresses store only a short one way fingerprint.
- **Input validation.** Pydantic models with `extra="forbid"` on every request body, which prevents mass assignment. All database access uses bound parameters through SQLAlchemy.
- **Retention.** The nightly job (03:30) deletes chat messages older than 90 days and removes emptied sessions, and anonymizes guest patients (no user account) whose appointments are all cancelled and older than 12 months. Both periods are rows in `app_settings` (`chat_retention_days`, `guest_anonymize_months`).
- **Dependency and secret scanning.** `pip-audit`, `npm audit`, Trivy and gitleaks run in CI and in the pre-commit hook where applicable. Bandit runs on the backend.

## Payment data

Card payments are sandbox simulations. Card number, expiry and security code are accepted as `SecretStr`, validated in memory and discarded; only the last four digits and a generated `SBX-` reference are stored, and tests assert that nothing else reaches the database or the audit log. Validation errors do not echo the submitted values. A real processor would take card entry out of the application entirely (hosted fields or redirect) to keep the service out of PCI DSS scope. Invoice amounts are protected by database check constraints, payments by a row lock, and discounts by role limits, each with tests.

## Known limits and decisions

- Verification and reset links use random stored tokens rather than signed stateless links. This allows revocation and single use, and satisfies the "signed, expiring" requirement through the server side expiry.
- A refresh token that is presented twice within moments by two browser tabs triggers reuse detection and signs the user out. The frontend serializes refresh calls to avoid this.
- Uploads are not part of the system yet. When added, type and size checks are required.
- Content security policy for the web application is defined in the Caddyfile and verified in Phase 12 together with the Leaflet tile source.

## OWASP ASVS level 1 review

Status values: **Met** (implemented and tested), **Planned** (assigned phase), **N/A**.

### V2 Authentication

| Requirement | Status | Notes |
|---|---|---|
| 2.1.1 Password length at least 12 characters | Met | Enforced on register, reset, change. |
| 2.1.2 Allow at least 64 characters, at most 128 | Met | |
| 2.1.7 Check against breached or common passwords | Met | Local common password list. A larger list can replace the file. |
| 2.1.8 Password strength guidance | Planned | Frontend strength meter, Phase 11. |
| 2.1.9 No composition rules | Met | |
| 2.2.1 Anti automation of credential stuffing | Met | Per IP and per account limits, lockout. |
| 2.2.3 Secure notification of authentication changes | Planned | Password change notification email, Phase 6. |
| 2.3.1 System generated initial passwords are random and expire | Met | No initial passwords exist; demo accounts get random passwords at seed time (Phase 18). |
| 2.4.1 Salted, adaptive password storage | Met | argon2id. |
| 2.5.1 Recovery secrets are random and single use | Met | 256 bit tokens, hashed, 30 minute expiry. |
| 2.5.2 No password hints or knowledge based recovery | Met | |
| 2.5.4 No default accounts | Met | |
| 2.7 Out of band verifier | N/A | |
| 2.8.1 Time based OTP | Met | TOTP with replay protection. |

### V3 Session management

| Requirement | Status | Notes |
|---|---|---|
| 3.2.1 New session token on authentication | Met | New refresh family at every login. |
| 3.2.2 At least 64 bits of entropy | Met | 256 bits. |
| 3.3.1 Logout invalidates the session | Met | Refresh family revoked server side. |
| 3.4.1 Cookie `Secure` | Met | |
| 3.4.2 Cookie `HttpOnly` | Met | Refresh token. The CSRF token cookie is intentionally readable. |
| 3.4.3 Cookie `SameSite` | Met | Strict. |
| 3.4.5 Cookie path restriction | Met | `/api/v1/auth`. |
| 3.7.1 Re-authentication for sensitive actions | Met | Password required for password change and MFA disable. |

### V4 Access control

| Requirement | Status | Notes |
|---|---|---|
| 4.1.1 Enforced on a trusted service layer | Met | Dependencies and service functions. |
| 4.1.2 User and data attributes cannot be manipulated | Met | Forbidden extra fields, role read from the database. |
| 4.1.3 Least privilege | Met | See the matrix; tests cover each role on each route. |
| 4.1.5 Fail securely | Met | Unknown or malformed tokens return 401. |
| 4.2.1 No IDOR | Met for current routes | Cross patient tests; extended per endpoint in Phases 4 and 5. |
| 4.2.2 CSRF protection | Met | See above. |
| 4.3.1 Administrative interfaces use MFA | Met | Mandatory for admin and dentist. |

### V5 Validation, sanitization and encoding

| Requirement | Status | Notes |
|---|---|---|
| 5.1.1 HTTP parameter pollution defences | Met | Typed parameters. |
| 5.1.3 Positive validation | Met | Pydantic models. |
| 5.2.x Sanitization, injection | Met | Parameterized queries only. Search text is bound, not interpolated (tested). |
| 5.3.x Output encoding | Planned | React encodes by default; link allowlist for chat output in Phase 9. |

### V6 Stored cryptography

| Requirement | Status | Notes |
|---|---|---|
| 6.1.1 Regulated data encrypted at rest | Met | Field level AES-GCM for personal data. |
| 6.2.1 Approved algorithms | Met | AES-256-GCM, argon2id, SHA-256, HS256 with a 32 character minimum secret in production. |
| 6.2.x Random values from a CSPRNG | Met | `secrets` module. |
| 6.4.1 Key management | Met | Key ids, rotation through old keys, secrets only in the environment. |

### V7 Error handling and logging

| Requirement | Status | Notes |
|---|---|---|
| 7.1.1 No credentials or payment details in logs | Met | Audit allowlist filter, request logs contain no bodies. |
| 7.1.2 No other sensitive data in logs | Met | |
| 7.2.1 Log authentication and access control events | Met | |
| 7.4.1 Generic error messages with an id | Met | Uniform error body with request id; unhandled errors reveal nothing. |

### V8 Data protection

| Requirement | Status | Notes |
|---|---|---|
| 8.1.x Sensitive data caching | Met | `Cache-Control: no-store` on API responses. |
| 8.2.x Client side storage | Met | Access token kept in memory only (frontend, Phase 11). |
| 8.3.4 Retention | Met | Nightly purge and anonymization. |

### V9 Communication

| Requirement | Status | Notes |
|---|---|---|
| 9.1.1 TLS for all connections | Met in production profile | Caddy automatic TLS; HSTS. |
| 9.2.x Back end TLS | Planned | Single host Compose network. Revisit if services are split across hosts. |

### V10 Malicious code and V11 Business logic

| Requirement | Status | Notes |
|---|---|---|
| 10.3.2 Dependency integrity and vulnerability checks | Met | Lockfiles, `pip-audit`, `npm audit`, Trivy. |
| 11.1.x Business logic flow limits | Met | Double booking guard in the database, slot holds, per IP and per address limits on booking, verification codes and contact forms, one time guest codes with an attempt cap. |

### V12 Files and V13 API

| Requirement | Status | Notes |
|---|---|---|
| 12.x File handling | N/A | No uploads yet. |
| 13.1.x API input validation, content types | Met | JSON only, typed models. |
| 13.2.x REST method restrictions | Met | Explicit methods per route, CORS method allowlist. |

### V14 Configuration

| Requirement | Status | Notes |
|---|---|---|
| 14.1.x Build and deployment | Met | Lockfiles, non root container user, CI scans. |
| 14.2.1 Components up to date | Met | Audited in CI. |
| 14.4.x HTTP security headers | Met | API and Caddy. |
| 14.5.3 CORS allowlist | Met | |

## Test coverage of the above

`tests/auth` contains the authentication, MFA, token rotation, role matrix, cross patient, mass assignment, encryption, audit, rate limit, retention and HTTP hardening tests (about 170 cases). They run against a real PostgreSQL server and an in-memory Redis.
