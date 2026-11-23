# UNIBZ_M2CI_EVENT_REGISTRATION

[![Shared and cross-service tests](https://github.com/pdramoss/UNIBZ_M2CI_EVENT_REGISTRATION/actions/workflows/shared.yml/badge.svg)](https://github.com/pdramoss/UNIBZ_M2CI_EVENT_REGISTRATION/actions/workflows/shared.yml)
[![End-to-end tests](https://github.com/pdramoss/UNIBZ_M2CI_EVENT_REGISTRATION/actions/workflows/e2e.yml/badge.svg)](https://github.com/pdramoss/UNIBZ_M2CI_EVENT_REGISTRATION/actions/workflows/e2e.yml)
[![Lint](https://github.com/pdramoss/UNIBZ_M2CI_EVENT_REGISTRATION/actions/workflows/lint.yml/badge.svg)](https://github.com/pdramoss/UNIBZ_M2CI_EVENT_REGISTRATION/actions/workflows/lint.yml)

## Architecture

![A browser and the command-line client reach an nginx gateway on 127.0.0.1:9000; the gateway routes to the Flask interface and to the accounts, events and registrations services, and all three services read and write one shared SQLite file on a Docker volume](github_repo_files/arquitectura.jpeg)

Five containers run under Docker Compose, and **each is built from its own folder and its own `Dockerfile` into its own image**. Only the gateway publishes a port — bound to `127.0.0.1:9000` — so everything else is reachable solely over the Compose network.

| Component | Role |
| --- | --- |
| `gateway/` | nginx, the single entry point and the only component that knows the application is divided. Routes by path; holds no business logic. |
| `services/accounts/`, `services/events/`, `services/registrations/` | The back end, as three independently deployable FastAPI services. Together they are the only component that touches the database, and the single source of truth for validation and authorization. |
| `web/` | The Flask interface on `:5000`, unpublished. A thin HTTP client that reads one back-end setting, `GATEWAY_URL`. |
| `common/` | The schema, the password format, the localized message catalogue and the shared FastAPI assembly, copied into each backend image at build time. |
| `scripts/api_cli.py` | A stdlib-only CLI that also defaults to the gateway, so it needs to know nothing about the split. Run from the host; copied into no image. |

Two invariants hold the design together, and both are visible in the diagram above.

**The three services share one SQLite file.** That is what keeps the split cheap: each service resolves a bearer token by reading `auth_sessions` itself and joins across tables it does not own, so **no service ever calls another over HTTP**. A second database, or one service calling another, would break the design.

**The interface never learns that the back end is split.** It holds no API address at all — only `GATEWAY_URL` — so its own calls go back out through the gateway rather than addressing a service directly. That is the loop the diagram shows between `UI Flask` and `Gateway nginx`, and it is why the gateway must stay transparent by contract: it never inspects, validates or rewrites a payload.

[One URL in front of five containers](#one-url-in-front-of-five-containers) below has the full routing table, the gateway's failure modes and the reasoning behind both invariants.

## Run the application

The project provides a Flask web interface, an nginx gateway, and a FastAPI back end split across three services, for managing users, events, and registrations. Each service publishes its own interactive API reference: `http://127.0.0.1:9000/docs/accounts`, `/docs/events` and `/docs/registrations`.

### With Docker Compose

```sh
cp -n .env.example .env
# Set ADMIN_PASSWORD in .env to a strong random value, for example: openssl rand -hex 32
docker compose up --build
```

This builds one image per container — `local/unibz-m2ci-accounts`, `local/unibz-m2ci-events`, `local/unibz-m2ci-registrations`, `local/unibz-m2ci-web` and `local/unibz-m2ci-gateway`, each tagged `:latest` — and starts those five containers. Exactly one port is published:

- **The whole application at `http://127.0.0.1:9000`** — the gateway, and the only address any client needs

### One URL in front of five containers

The back end is three services, not one. The gateway is the single entry point and the only component that knows the application is divided at all; it routes each request by its path:

| Request | Served by | Container |
| --- | --- | --- |
| `/api/v1/auth/...`, `/api/v1/users`, `/api/v1/clients`, `/api/v1/administrators` | authentication and the user records | `accounts` |
| `/api/v1/events...` | the event catalogue | `events` |
| `/api/v1/registrations...` | registrations and the capacity check | `registrations` |
| `/docs/accounts`, `/docs/events`, `/docs/registrations` | that service's own Swagger page | the owning service |
| `/health` | the gateway itself | `gateway` |
| `/` and every other page | the Flask web interface | `web` |

Nothing outside the gateway needs to know any of this. A browser uses one address; the web interface uses that same address for its own calls and holds no backend address at all, only `GATEWAY_URL`; the CLI defaults to it too. Only the gateway publishes a port — the three services and the interface are reachable solely over the Compose network.

#### The three services share one database

Each is built from its own folder and its own `Dockerfile` into its own image, and they mount the same `event_registration_data` volume, so there is a single SQLite file. That is what keeps the split cheap: every service resolves a bearer token by reading `auth_sessions` itself, and a registration still checks an event's capacity with a join, so **no service ever calls another one**. A session issued by `accounts` is accepted by `events` and `registrations`, and logging out through `accounts` revokes it everywhere.

The database runs in WAL mode, set once at startup. With three processes writing one file, the default rollback journal would make a writer block every reader for the length of its transaction — and the capacity check holds a write transaction.

#### The gateway

It is nginx: `gateway/Dockerfile` builds `FROM nginx:1.27-alpine` and copies `gateway.conf.template` into the image, so it adds no Python and no dependency to the project. The configuration is baked in rather than mounted, which makes the gateway as self-contained and as versioned as the four application images — it can run on a host that has no copy of this repository. It holds no business logic and rewrites no path — each service stays the single source of truth for its own validation and authorization.

Set `GATEWAY_ACCOUNTS_UPSTREAM`, `GATEWAY_EVENTS_UPSTREAM`, `GATEWAY_REGISTRATIONS_UPSTREAM` and `GATEWAY_WEB_UPSTREAM` to point it elsewhere (`host:port`, no scheme), and `GATEWAY_TIMEOUT` to change its 15-second upstream timeout. Only nginx's own failures produce a gateway-authored body, and each path answers in the shape its caller expects: an unreachable service gives 502 and a slow one 504, both as the API's `{"detail": ...}`, while an unavailable interface gives a short HTML 503 page, since a browser asking for a page should not receive JSON. An `/api/v1` path no service owns gets the gateway's own JSON 404. The parts fail independently: with a backend service stopped, the interface still loads and the other services still answer.

Open `http://127.0.0.1:9000` in a browser to sign in and use the forms. The three services start first, the interface next, and the gateway last, so that nothing reaches the gateway before the back end is healthy. SQLite data is stored in the persistent `event_registration_data` Compose volume. Stopping the services or running `docker compose down` preserves the volume. `docker compose down -v` removes the volume and its data.

The UI supports public Client signup and profile CRUD, event browsing and Administrator event CRUD, Client-owned registration CRUD, and Administrator creation of Client/Administrator accounts. Sign in with an account that has the required role to use protected workflows. The CLI remains available as an optional API client.

### Build the images

Each service owns its `Dockerfile`, and every build uses the repository root as its context so the image can reach `common/`:

```sh
docker build -f services/accounts/Dockerfile -t unibz-m2ci-accounts:local .
docker build -f services/events/Dockerfile -t unibz-m2ci-events:local .
docker build -f services/registrations/Dockerfile -t unibz-m2ci-registrations:local .
docker build -f web/Dockerfile -t unibz-m2ci-web:local .
docker build -f gateway/Dockerfile -t unibz-m2ci-gateway:local ./gateway
```

Note the gateway's context: `./gateway`, not `.`. It needs nothing from `common/`, so there is no reason to hand it the whole repository.

`docker compose build` does the same four builds and applies the names above with the `${DOCKERHUB_USERNAME:-local}` namespace and `${IMAGE_TAG:-latest}` tag. Each image carries only what it needs: a backend image holds `common/` and one service folder, and the web image holds neither — it is a thin HTTP client, so it ships no FastAPI and no database driver.

There is no combined image. Nothing builds all three services into one artifact any more, which is the point of the split.

### Architectures

A plain `docker build` or `docker compose build` produces an image for the architecture of the machine that builds it. On an Apple Silicon Mac that is `linux/arm64`, which runs natively in Docker Desktop's Apple Virtualization framework VM; on a typical x86 server or CI runner it is `linux/amd64`. To build one service for both locally:

```sh
docker buildx build --platform linux/amd64,linux/arm64 \
  -f services/accounts/Dockerfile -t unibz-m2ci-accounts:multiarch .
docker image ls --tree | grep -A2 multiarch
```

### Publishing

**This project publishes no images.** The `Publish Docker image` workflow was removed along with the single combined image it pushed, so there is no `v*` tag release path and the `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` secrets are unused. The service boundaries are still moving; publishing is deferred until they settle, at which point each service gets its own tag.

To push by hand in the meantime, set a namespace and use Compose:

```sh
export DOCKERHUB_USERNAME=your-dockerhub-username
export IMAGE_TAG=latest
docker login
docker compose build accounts events registrations web gateway
docker compose push accounts events registrations web gateway
```

`docker login` prompts for your Docker Hub credentials; do not put credentials in the Compose file or commit them to the project. Without `DOCKERHUB_USERNAME`, Compose uses the `local` namespace so local builds need no registry access.

### Continuous integration

Each service has its own pipeline, so they no longer wait on each other to go green:

| Workflow | Runs | Triggered by |
| --- | --- | --- |
| `service-accounts.yml`, `service-events.yml`, `service-registrations.yml` | that service's image build and its unit tests | changes to that service or to `common/` |
| `service-web.yml` | the web image build and the UI unit tests | changes to `web/` |
| `service-gateway.yml` | the gateway image build, then `nginx -t` on the rendered config and a no-leftover-placeholder check — no Python, no pytest | changes to `gateway/` |
| `shared.yml` | the cross-service contract, the `common/` foundation and the CLI | every push |
| `e2e.yml` | the whole five-container stack | every push |
| `lint.yml` | Ruff over the repository | every push |

The per-service workflows are path filtered, so a change touching only one service leaves the others not merely passing but **not running**. That is deliberate; be aware of it before marking any of them a required check, since GitHub blocks on a skipped required check. `shared.yml` and `e2e.yml` are never filtered, because a change anywhere can break them. Each run publishes a summary on its Actions page, and the badges at the top of this file show the latest status on `main`.

### Locally

```sh
cp -n .env.example .env
# Set ADMIN_PASSWORD in .env to a strong random value.
set -a
. ./.env
set +a
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn services.events.main:app --port 8002 --reload
```

The default SQLite database is `data/event_registration.sqlite3`. Override its location with `DATABASE_PATH`.

Each service is its own ASGI app, so running the back end locally means starting the ones you need, each on its own port, all sharing one database file:

```sh
uvicorn services.accounts.main:app      --port 8001 --reload
uvicorn services.events.main:app        --port 8002 --reload
uvicorn services.registrations.main:app --port 8003 --reload
```

Each serves only its own routes, and its Swagger page is at `/docs/<service>` — so the catalogue is at `http://127.0.0.1:8002/docs/events`. A session issued by `accounts` on 8001 is honoured by the other two, because all three read the same `auth_sessions` table.

**There is no all-in-one app.** The combined application was removed with the split, so no single local port serves every `/api/v1` path. The web interface reads exactly one setting for its back end, `GATEWAY_URL` (default `http://127.0.0.1:9000`), and holds no API address at all — which is the point: it cannot be pointed at one piece of the back end by accident. The gateway is nginx rather than Python, so it has no local non-container form. **To work on the interface, use Compose:**

```sh
docker compose up --build -d
```

That gives the interface a real gateway on 9000, which is the deployed shape rather than a development shortcut.

For the real arrangement, run all three with Compose and use `http://127.0.0.1:9000` for everything. After editing `gateway/gateway.conf.template`, apply it with `docker compose up -d --build gateway`. A plain `docker compose restart gateway` is **not** enough any more: the template is baked into the gateway's image, so it has to be rebuilt, not just restarted. Set `WEB_SECRET_KEY` to a stable random secret when running more than one UI worker or in a long-lived deployment; the local single-process development setup generates one when omitted.

## Use the web interface

Navigate to `http://127.0.0.1:9000` after starting Compose. The interface provides forms for login/logout, Client signup and profile CRUD, event CRUD for Administrators, registration CRUD for Clients, and Administrator creation of Client and Administrator accounts. The API remains the source of truth for authorization and validation, and API error details are displayed in the interface. Deleting a record goes through a confirmation page that names it, and a rejected form shows the API's message on the field it belongs to. A signed-in Client manages its own account at `/profile`, where account details and the password are two separate forms; the Clients directory and the per-record pages under `/users` are Administrator-only, while `/users/new` stays open as the signup form.

See [usability-evaluation.md](usability-evaluation.md) for the heuristic evaluation of this interface against Jakob Nielsen's ten usability heuristics: the 20 findings, the measured colour contrast, which six were fixed and which were deferred.

## API routes

All routes are prefixed with `/api/v1`. `users`, `events`, and `registrations` support:

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/{resource}` | List records (`limit` and `offset` supported) |
| `POST` | `/{resource}` | Create a record |
| `GET` | `/{resource}/{id}` | Read one record |
| `PATCH` | `/{resource}/{id}` | Update supplied fields |
| `DELETE` | `/{resource}/{id}` | Delete a record |
| `POST` | `/auth/login` | Exchange account credentials for a Bearer token |
| `POST` | `/auth/logout` | Revoke the current Bearer token |
| `POST` | `/clients` | Administrator creates a Client |
| `POST` | `/administrators` | Administrator creates an Administrator |
| `GET` | `/users/me` | Read the account the Bearer token belongs to |
| `PATCH` | `/users/me` | Update that account without knowing its id |

Authenticate with `POST /api/v1/auth/login` and send the token it returns as an `Authorization: Bearer <token>` header on every protected request. Tokens are revocable: `POST /api/v1/auth/logout` invalidates the current one, and when it expires or is revoked you log in again.

Supported resources are `users`, `clients`, `administrators`, `events`, and `registrations`. `POST /users` remains public Client signup. `POST /clients` and `POST /administrators` require an Administrator Bearer token; persisted Administrators can create further accounts. Existing accounts are migrated as Clients. **User records are owner-or-Administrator only.** `GET /users` lists Client records and requires an Administrator token. `GET`, `PATCH` and `DELETE /users/{id}` require a token, and a Client may use them only on its own record; an Administrator may use them on any. `GET` and `PATCH /users/me` resolve the account from the token, so a Client never needs to know its own id, and they answer 404 for the bootstrap Administrator, which has no stored record. `UserPatch` has no `role` field, so a Client cannot promote itself. Event writes require an Administrator token; event reads stay public. Registration create, list, get, update, and delete operations require a Client token. A Client can access only their own registrations; the API derives `user_id` from the authenticated account, so registration requests must not include it. Creation requires an existing `event_id` and is rejected when an event has reached capacity. Deleting a Client or event also deletes its registrations.

## API message localization

Application-generated API error messages are available in English (`en`) and Spanish (`es`). Send an `Accept-Language` header such as `Accept-Language: es` to request Spanish. Regional language tags such as `es-MX` are matched to their base language; if the header is missing or no supported language matches, the API responds in English. FastAPI/Pydantic request-validation messages are unchanged.

## Security note

This is a local development API. The environment-configured account is the bootstrap Administrator; newly created Administrators are stored in SQLite with hashed passwords and can authenticate independently. Login issues opaque, 24-hour Bearer tokens; only token hashes are persisted, and logout revokes the active token. Keep the service bound to localhost and do not expose it to an untrusted network without HTTPS. Protect Bearer tokens as secrets. Passwords are hashed in SQLite and omitted from API responses. Client records are not public: reading, changing or deleting one requires the owner's or an Administrator's token. Avoid putting real passwords in terminal commands, where command history may retain them.

## Bash exit-code exercise

Run the script from the repository root to see a successful and a failing command, their exit codes, and conditional interpretations:

```sh
./scripts/interpret_exit_codes.sh
```

## Bash function exercise

Run the function example to classify several positive, zero, and negative integers:

```sh
./scripts/check_even_odd.sh
```

## Tests

See [testing-strategy.md](testing-strategy.md) for fresh-checkout setup, unit and Playwright API test commands, recorded results, and the delivery path.

```sh
python -m pip install -r requirements-dev.txt
pytest
```

### Playwright end-to-end tests

The Playwright tests use Python's `APIRequestContext` to exercise the documented API and submit forms to the Flask UI against a running Docker Compose stack. They create unique Client, event, and registration data, check responses and persisted state, then delete test records and revoke sessions. No browser installation is needed.

Start the services using the Docker Compose instructions above, then load the local bootstrap credentials and run both workflows:

```sh
docker compose up --build -d
set -a
. ./.env
set +a
API_BASE_URL=http://127.0.0.1:9000 GATEWAY_BASE_URL=http://127.0.0.1:9000 python -m pytest -m e2e
```

The E2E tests are skipped when `API_BASE_URL`, `ADMIN_USERNAME`, or `ADMIN_PASSWORD` is not set; `WEB_BASE_URL` defaults to `http://127.0.0.1:9000` and `GATEWAY_BASE_URL` falls back to `API_BASE_URL`. All of them now name the gateway, because it is the only published port: there is no address that reaches a single backend service from outside. Running `pytest` without those variables runs the ordinary unit tests and reports the E2E tests as skipped.
