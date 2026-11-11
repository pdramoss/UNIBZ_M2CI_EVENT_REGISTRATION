# Testing strategy and delivery path

## Test scope

| Layer | Location | What it checks | Required services |
| --- | --- | --- | --- |
| Unit/API, CLI, and web UI | `tests/unit/` | API behavior through FastAPI's test client, persistence and role rules, authentication/localization, CLI request mapping, and Flask form/session behavior | None; uses temporary test databases and a mocked API boundary for UI requests |
| Playwright end-to-end | `tests/e2e/` | Documented API workflow plus Admin/Client login, event and Client form CRUD, registration form CRUD, resulting API state, data cleanup, and token revocation | Running API and web services with bootstrap Admin credentials |

The E2E tests use Playwright's Python `APIRequestContext`; they do not launch a browser or install browser binaries. The API workflow generates unique account/event data, while the web workflow submits actual HTML forms to Flask and verifies persisted API state. Both clean up their created data and revoke sessions. Flask UI role checks and server-side session behavior are also covered by unit tests.

## Fresh-checkout setup and commands

Run commands from the repository root. Python and pip are required for all tests. Docker Engine/Desktop and Docker Compose are additionally required for the E2E test.

Create a virtual environment and install development dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Run the unit/API, CLI, and Flask UI tests:

```sh
pytest -q tests/unit
```

Run all tests. Without E2E environment settings, the Playwright tests are reported as skipped:

```sh
pytest -q
```

To run the Playwright E2E workflow, create the local environment file from the example, set a non-empty strong `ADMIN_PASSWORD`, and start the Compose services. The example uses `ADMIN_USERNAME=event-admin`; keep `.env` local and do not commit it.

```sh
cp -n .env.example .env
# Set ADMIN_PASSWORD in .env; a strong value can be generated with: openssl rand -hex 32
docker compose up --build -d
```

Load the same bootstrap credentials into the test process and invoke the E2E marker:

```sh
set -a
. ./.env
set +a
API_BASE_URL=http://127.0.0.1:8000 pytest -q -m e2e
```

```sh
curl --fail http://127.0.0.1:8000/openapi.json -o /dev/null
curl --fail http://127.0.0.1:5000/ -o /dev/null
```

The E2E test is skipped if any of `API_BASE_URL`, `ADMIN_USERNAME`, or `ADMIN_PASSWORD` is missing or empty. `docker compose down` stops the service but preserves its SQLite volume; do not use `docker compose down -v` unless you intend to delete application data.

## Recorded test results

Validated locally on 2026-11-11 with Python 3.15.2, pytest 9.2.0, Playwright 1.65.0, Docker Compose 5.6.1, and Docker Engine 29.9.2. The Docker image itself runs Python 3.12.

| Command/check | Result |
| --- | --- |
| `pytest -q tests/unit` | 36 passed |
| `pytest -q` | 36 passed, 2 skipped; the skips are E2E tests because the ordinary unit-test invocation did not set service/credential environment |
| `API_BASE_URL=http://127.0.0.1:8000 pytest -q -m e2e` with `.env` loaded | 2 passed, 36 deselected |
| `GET /docs` and `GET /openapi.json` on localhost | Both returned HTTP 200 |
| Flask UI test-client checks | Form submissions, server-side token handling, role gating, and API error display are covered in `tests/unit/test_web_app.py` |
| Flask UI routes | Home, event listing, and login pages returned HTTP 200; the Playwright workflow created, read, and deleted a registration through UI forms and verified API state |
| Post-run application state | The test verified its registration, Client, and event were deleted and both tokens were revoked; the API event listing contained no Playwright test event afterward |
| `git diff --check` | Passed |

The E2E command intentionally selects only the `e2e` marker; `36 deselected` in that run is expected and does not mean those tests failed.

## From code change to a running version

1. Make a change and run `pytest -q tests/unit` locally. Before exercising the integrated HTTP workflow, start Compose and run `pytest -q -m e2e` with the bootstrap settings above. The same checks run automatically in the `Build and test` workflow (`.github/workflows/tests.yml`) on every branch push, on every pull request, and on manual dispatch: a `unit` job compiles the sources, builds the Docker image, runs `pytest tests/unit`, writes a results table to the run summary and uploads the JUnit report as an artifact; then an `e2e` job starts the Compose services with generated bootstrap credentials and runs `pytest -q -m e2e`, failing if any E2E test is skipped. A separate `Lint` workflow (`.github/workflows/lint.yml`) runs `ruff check` on the same triggers and reports findings as annotations; run it locally with `ruff check .`.
2. To run the changed application locally, use `docker compose up --build` (or `docker compose up --build -d` to continue using the terminal). Compose builds the local image, starts the API and Flask UI, and binds them to `127.0.0.1:8000` and `127.0.0.1:5000`.
3. To publish an image, manually configure the `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repository secrets, create a version tag matching `v*`, and push the tag. For example:

   ```sh
   git tag v1.2.3
   git push origin v1.2.3
   ```

4. `.github/workflows/publish-image.yml` first runs the `Build and test` workflow and stops if it fails. It then checks out the source, sets up Buildx, logs in to Docker Hub, builds the image, and pushes the version tag and `latest`. Publishing is the end of the automated delivery path. There is no configured deployment target or automatic rollout; deploying a published image to a running host remains a manual operational step.

## Manual steps, delays, and likely failure points

- **Local setup:** create/activate the virtual environment, install development packages, and set a non-empty bootstrap password. A fresh dependency installation requires package-index access.
- **Starting the application:** Docker must be installed and its daemon running. The first Compose build may need to download the Python base image and application dependencies. Ports `8000` and `5000` must be available. The UI service waits for the API health check before starting.
- **E2E configuration:** source the same `.env` used by Compose into the shell running pytest. A wrong `API_BASE_URL`, missing credentials, or running the test before the API is ready causes the E2E check to skip or fail to connect; check the skip count and OpenAPI readiness command rather than treating a skipped test as a pass.
- **Persistent data:** Compose keeps SQLite data in a named volume. The test cleans only records it created; avoid deleting the volume to reset the test.
- **Image publishing:** a pushed `v*` tag and valid Docker Hub secrets are manual prerequisites. Missing secrets, invalid credentials, network issues, or a tag that does not match the trigger prevent publication. GitHub Actions must build and push before the image is available in the registry.
- **Deployment:** publishing does not start or update an application server. The repository currently documents local Compose execution and image publication, but not a remote deployment mechanism.
