# UNIBZ_M2CI_EVENT_REGISTRATION

[![Build and test](https://github.com/pdramoss/UNIBZ_M2CI_EVENT_REGISTRATION/actions/workflows/tests.yml/badge.svg)](https://github.com/pdramoss/UNIBZ_M2CI_EVENT_REGISTRATION/actions/workflows/tests.yml)
[![Lint](https://github.com/pdramoss/UNIBZ_M2CI_EVENT_REGISTRATION/actions/workflows/lint.yml/badge.svg)](https://github.com/pdramoss/UNIBZ_M2CI_EVENT_REGISTRATION/actions/workflows/lint.yml)

## Run the application

The project provides a Flask web interface and a FastAPI HTTP API for managing users, events, and registrations. FastAPI publishes an interactive API reference at `http://127.0.0.1:8000/docs` and an OpenAPI document at `http://127.0.0.1:8000/openapi.json`.

### With Docker Compose

```sh
cp -n .env.example .env
# Set ADMIN_PASSWORD in .env to a strong random value, for example: openssl rand -hex 32
docker compose up --build
```

This builds the image as `local/unibz-m2ci-event-registration:latest` and starts both services:

- The Flask web interface at `http://127.0.0.1:5000`
- The FastAPI API and interactive docs at `http://127.0.0.1:8000` and `http://127.0.0.1:8000/docs`

Open the web interface in a browser to sign in and use the forms; the API service starts first and the UI sends requests to it over the Compose network. SQLite data is stored in the persistent `event_registration_data` Compose volume. Stopping the services or running `docker compose down` preserves the volume. `docker compose down -v` removes the volume and its data.

The UI supports public Client signup and profile CRUD, event browsing and Administrator event CRUD, Client-owned registration CRUD, and Administrator creation of Client/Administrator accounts. Sign in with an account that has the required role to use protected workflows. The CLI remains available as an optional API client.

### Build and push to Docker Hub

Set your Docker Hub namespace and optionally choose an image tag:

```sh
export DOCKERHUB_USERNAME=your-dockerhub-username
export IMAGE_TAG=latest
docker login
docker compose build app
docker compose push app
```

The resulting image is tagged as `${DOCKERHUB_USERNAME}/unibz-m2ci-event-registration:${IMAGE_TAG}`. `docker login` prompts for your Docker Hub credentials; do not put credentials in the Compose file or commit them to the project. Without `DOCKERHUB_USERNAME`, Compose uses the `local` namespace so local builds do not require registry access.

### Automated publishing from GitHub

The `Publish Docker image` workflow runs when a version tag matching `v*` is pushed. In the GitHub repository settings, add these Actions repository secrets:

- `DOCKERHUB_USERNAME`: your Docker Hub username
- `DOCKERHUB_TOKEN`: a Docker Hub access token with permission to push images

Then push a version tag, for example:

```sh
git tag v1.2.3
git push origin v1.2.3
```

The workflow first runs the `Build and test` workflow (Docker image build, unit tests and end-to-end tests) and only continues if it passes. It then builds the image and publishes both `v1.2.3` and `latest` tags to Docker Hub. It does not publish on ordinary branch pushes.

Two workflows run on every branch push and every pull request: `Build and test` (`.github/workflows/tests.yml`) and `Lint` (`.github/workflows/lint.yml`, Ruff). Each run publishes a summary on its Actions page, and the badges at the top of this file show the latest status on `main`.

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
uvicorn app.main:app --reload
```

The default SQLite database is `data/event_registration.sqlite3`. Override its location with `DATABASE_PATH`.

To run the web interface locally as well, start the API in one terminal and the Flask app in another:

```sh
waitress-serve --listen=127.0.0.1:5000 web.app:app
```

The local UI defaults to `http://127.0.0.1:8000` for its API. Set `API_BASE_URL` if the API runs elsewhere. Set `WEB_SECRET_KEY` to a stable random secret when running more than one UI worker or in a long-lived deployment; the local single-process development setup generates one when omitted.

## Use the web interface

Navigate to `http://127.0.0.1:5000` after starting Compose. The interface provides forms for login/logout, Client signup and profile CRUD, event CRUD for Administrators, registration CRUD for Clients, and Administrator creation of Client and Administrator accounts. The API remains the source of truth for authorization and validation, and API error details are displayed in the interface.

## Call the API from the terminal

The terminal client uses Python's standard library and sends requests to the running API. Set `API_BASE_URL` or pass `--base-url` before the resource name to use a different server.

The environment-configured Administrator is the bootstrap account. Administrators can create persistent Administrator and Client accounts; those accounts then log in with their own username and password. Log in to receive a 24-hour Bearer token. The CLI prompts for the password without echoing it and writes the token to standard output, so command substitution can place it in `API_TOKEN` without saving it to a token file:

```sh
export API_TOKEN="$(python scripts/api_cli.py auth login --username event-admin)"
```

```sh
python scripts/api_cli.py auth logout
unset API_TOKEN
```

Login credentials are also accepted directly by `POST /api/v1/auth/login`; send the returned token as `Authorization: Bearer <token>` on protected requests. Tokens are revocable: the logout command invalidates the current `API_TOKEN`. When it expires or is revoked, log in again.

```sh
python scripts/api_cli.py users list
python scripts/api_cli.py users create --data '{"name":"Alex","password":"replace-this-test-password","email":"alex@example.com","age":30,"username":"alex"}'
python scripts/api_cli.py users get 1
python scripts/api_cli.py users update 1 --data '{"age":31}'
python scripts/api_cli.py users delete 1

# Log in as an Administrator before creating accounts or writing events.
export API_TOKEN="$(python scripts/api_cli.py auth login --username event-admin)"
python scripts/api_cli.py events create --data '{"name":"Meetup","date":"2026-12-01","description":"Community meetup","capacity":50,"place":"Bolzano"}'

python scripts/api_cli.py clients create --data '{"name":"Sam","password":"replace-this-test-password","email":"sam@example.com","age":25,"username":"sam"}'
python scripts/api_cli.py administrators create --data '{"name":"Morgan","password":"replace-this-test-password","email":"morgan@example.com","age":35,"username":"morgan"}'

# Log in as the Client whose registrations you want to manage.
export API_TOKEN="$(python scripts/api_cli.py auth login --username alex)"
python scripts/api_cli.py registrations create --data '{"date":"2026-11-11","event_id":1}'
python scripts/api_cli.py registrations list
```

All three resources (`users`, `events`, and `registrations`) support `list`, `get`, `create`, `update`, and `delete` commands. Create and update values are JSON objects. List commands accept `--limit` and `--offset`.

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

Supported resources are `users`, `clients`, `administrators`, `events`, and `registrations`. `POST /users` remains public Client signup. `POST /clients` and `POST /administrators` require an Administrator Bearer token; persisted Administrators can create further accounts. Existing accounts are migrated as Clients. Event writes require an Administrator token. Registration create, list, get, update, and delete operations require a Client token. A Client can access only their own registrations; the API derives `user_id` from the authenticated account, so registration requests must not include it. Creation requires an existing `event_id` and is rejected when an event has reached capacity. Deleting a Client or event also deletes its registrations.

## API message localization

Application-generated API error messages are available in English (`en`) and Spanish (`es`). Send an `Accept-Language` header such as `Accept-Language: es` to request Spanish. Regional language tags such as `es-MX` are matched to their base language; if the header is missing or no supported language matches, the API responds in English. FastAPI/Pydantic request-validation messages are unchanged.

## Security note

This is a local development API. The environment-configured account is the bootstrap Administrator; newly created Administrators are stored in SQLite with hashed passwords and can authenticate independently. Login issues opaque, 24-hour Bearer tokens; only token hashes are persisted, and logout revokes the active token. Keep the service bound to localhost and do not expose it to an untrusted network without HTTPS. Protect `API_TOKEN` as a secret. Passwords are hashed in SQLite and omitted from API responses. Avoid putting real passwords in terminal commands, where command history may retain them.

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
API_BASE_URL=http://127.0.0.1:8000 python -m pytest -m e2e
```

The E2E test is skipped when `API_BASE_URL`, `ADMIN_USERNAME`, or `ADMIN_PASSWORD` is not set. Running `pytest` without those variables runs the ordinary unit tests and reports the E2E test as skipped.
