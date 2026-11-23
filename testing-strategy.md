# Testing strategy and delivery path

## Test scope

| Layer | Location | What it checks | Required services |
| --- | --- | --- | --- |
| Unit/API, CLI, and web UI | `tests/unit/` | API behavior through FastAPI's test client, persistence and role rules, authentication/localization, CLI request mapping, and Flask form/session behavior. One file per service — `test_accounts_api.py`, `test_events_api.py`, `test_registrations_api.py` — plus `test_common.py` for the shared `common/` foundation, `test_api_cli.py` and `test_web_app.py` | None; uses temporary test databases and a mocked API boundary for UI requests |
| Unit/service split | `tests/unit/test_services.py` | That each backend service serves only the routes it owns and 404s on the others, that the three together cover the whole API, that each documents itself under `/docs/<service>`, and that a session issued by `accounts` is honoured by `events` and `registrations` and revoked for both on logout | None; three test clients over one temporary database |
| Playwright end-to-end | `tests/e2e/` | Documented API workflow plus Admin/Client login, event and Client form CRUD, the Client's own `/profile` screen (rename and password change) and the refusal of `/users` to a Client, registration form CRUD, resulting API state, data cleanup, and token revocation; and the gateway contract: a preserved query string, an upstream 401 relayed with its `WWW-Authenticate` challenge, localized 404 details, a 204 logout, the interface's HTML and each service's JSON served from the one entry point, and three disjoint OpenAPI documents at `/docs/<service>` | All five containers running, with bootstrap Admin credentials |

The gateway is an nginx configuration file rather than Python, so it has no unit tests: there is nothing to import and stub in process. Its contract is covered end to end against the running containers instead, which is also a stronger check — the earlier Python forwarder's unit tests stubbed the upstream hop, while these exercise the real one. The paths E2E cannot reach, because they need a container to be down or to be recreated, are verified manually and recorded below.

Note what the unit suite does and does not prove about the split. Each service is now built and imaged on its own, so nothing composes them into one application; the suite instead runs the three apps side by side in one interpreter over one temporary database, which is how they run in Compose. `tests/unit/conftest.py` provides both views: `services`, the three test clients, and `api`, a facade that dispatches each request to the service owning its path using the same prefix table the gateway routes by — so a test expecting a 404 gets it from the owning service rather than from a service that simply never had the route. `tests/unit/test_services.py` builds the three service apps in process, so it covers the routing boundary and the shared-session behaviour exactly. It does not cover the gateway's path routing, nor three separate processes contending for one SQLite file; those are only observable against the running stack, and the manual checks below are what establish them.

The E2E tests use Playwright's Python `APIRequestContext`; they do not launch a browser or install browser binaries. The API workflow generates unique account/event data, while the web workflow submits actual HTML forms to Flask and verifies persisted API state. Both clean up their created data and revoke sessions. Flask UI role checks and server-side session behavior are also covered by unit tests.

Two behaviours added after the usability evaluation and the profile work are worth naming, because each is asserted in a way that would otherwise look redundant. **Deletion is confirmed, not immediate:** `GET /<resource>/<id>/delete` renders a confirmation page naming the record and makes no `DELETE` call, while `POST` to the same URL deletes. The E2E workflows post to that URL directly, so the POST contract is covered there and the GET arm is covered in `test_web_app.py`. **User records are owner-or-Administrator only:** `test_accounts_api.py` asserts the whole matrix — a Client reaching its own record and being refused another's, `GET /users` refused anonymously and to a Client, `users/me` resolving the account from the token, the bootstrap Administrator having no record to return, and `PATCH` rejecting a `role` field. `test_common.py` asserts localization against `GET /api/v1/events/404` rather than a user route precisely so that it keeps testing translation rather than authentication.

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
API_BASE_URL=http://127.0.0.1:9000 GATEWAY_BASE_URL=http://127.0.0.1:9000 pytest -q -m e2e
```

```sh
curl --fail http://127.0.0.1:9000/health -o /dev/null
curl --fail http://127.0.0.1:9000/ -o /dev/null
curl --fail http://127.0.0.1:9000/api/v1/events -o /dev/null
curl --fail http://127.0.0.1:9000/docs/accounts/openapi.json -o /dev/null
```

The E2E tests are skipped if any of `API_BASE_URL`, `ADMIN_USERNAME`, or `ADMIN_PASSWORD` is missing or empty. `GATEWAY_BASE_URL` defaults to `http://127.0.0.1:9000`. `docker compose down` stops the service but preserves its SQLite volume; do not use `docker compose down -v` unless you intend to delete application data.

## Recorded test results

Validated locally on 2026-11-23 with Python 3.15.2, pytest 9.2.0, Playwright 1.65.0, Docker Compose 5.6.1, and Docker Engine 29.9.2. The Docker image itself runs Python 3.12.

| Command/check | Result |
| --- | --- |
| `pytest -q tests/unit` | 53 passed |
| `pytest -q` | 53 passed, 3 skipped; the skips are E2E tests because the ordinary unit-test invocation did not set service/credential environment |
| `API_BASE_URL=http://127.0.0.1:9000 GATEWAY_BASE_URL=http://127.0.0.1:9000 WEB_BASE_URL=http://127.0.0.1:9000 pytest -q -m e2e` with `.env` loaded | 3 passed, 53 deselected |
| `GET /docs`, `GET /openapi.json` and `GET /redoc` on the gateway | All three returned HTTP 404. There is no combined application any more, so no shared documentation path exists; each service documents itself at `/docs/<service>` instead, and these paths fall through to the interface |
| `GET /health` on the gateway | Returned HTTP 200 naming all four targets: `accounts:8000`, `events:8000`, `registrations:8000`, `web:5000` |
| One URL for everything on `:9000` | `/` and `/login` returned HTTP 200 `text/html`, `/static/style.css` HTTP 200 `text/css`, `/api/v1/events` HTTP 200 `application/json`, `/health` HTTP 200 `application/json` |
| Path routing to the three services | The gateway access log's `$upstream_addr` showed three distinct container addresses: `/api/v1/auth/login` and `/api/v1/users` to the accounts container, `/api/v1/events` to events, `/api/v1/registrations` to registrations, `/` and `/static/...` to web |
| Per-service documentation through the gateway | `/docs/accounts`, `/docs/events` and `/docs/registrations` each returned HTTP 200, and their `openapi.json` documents hold disjoint path sets — asserted in the gateway E2E test |
| Three services initializing one empty database at once | Three cold starts on a fresh volume: all three containers healthy, full schema present, no `database is locked` or traceback in any log |
| `PRAGMA journal_mode` on the shared volume | `wal` |
| 240 concurrent requests across the three services, 60 of them writes | All 2xx. Mixed `GET /api/v1/users` (accounts), `GET`/`PATCH /api/v1/events` (events) and `GET /api/v1/registrations` (registrations) at 32 threads, then one registration created and the event's `available_seats` correctly 59 of 60 |
| Recreating the backend containers without restarting the gateway | Routing still correct. `accounts` and `registrations` exchanged container addresses and every path still reached its own service, which the earlier `upstream`-block configuration got wrong silently — it sent `/api/v1/auth` to the events container |
| CLI through the gateway with no `--base-url` | `auth login` (accounts) returned a token, `events list` (events) listed events, `registrations list` returned the registrations service's own HTTP 403 for an administrator, `auth logout` (accounts) succeeded |
| Published ports | Only `127.0.0.1:9000`. Neither the interface nor any backend service publishes one, so the gateway is the only way in. Anything answering on host `:5000` is unrelated — on macOS, AirPlay Receiver replies there with an empty `403` |
| The parts fail independently | With `web` stopped, `/` returned the gateway's HTML 503 while `/api/v1/events` still returned 200; with the events service stopped, `/` still returned 200 while `/api/v1/events` returned 502 `{"detail":"Could not reach the API."}`. Both recovered to 200 after `docker compose start` |
| `nginx -t` inside the gateway container | Configuration syntax ok, test successful; the rendered file shows the four targets substituted and the surviving `$request_id`, so `envsubst` replaced only `GATEWAY_*`. **This check now runs in CI** (`service-gateway.yml`) rather than only by hand, since the gateway has its own image to validate |
| Query string preserved through variable `proxy_pass` | `/api/v1/events?limit=1&offset=0` returned exactly one record, so switching to per-request resolution did not drop the query |
| Unauthenticated `POST /api/v1/events` through the gateway | HTTP 401 with `www-authenticate: Bearer` relayed from the API, body identical to the direct call |
| `GET /api/v1/nothing` | HTTP 404 with the gateway's own `{"detail": ...}`, rather than falling through to the interface's HTML |
| Gateway with a backend service stopped (`docker compose stop events`) | HTTP 504 with `{"detail":"The API did not respond in time."}` — the API's error shape, not nginx's HTML page; `/health` kept returning 200, and traffic recovered to 200 after `docker compose start app` |
| 120 concurrent reads against `:9000/api/v1/events` and against `:9000/` | All 200; `test_concurrent_reads_do_not_fail` covers the single-process case in the unit suite |
| Full UI flow through the gateway | Login, event listing with `limit=500`, event lookup and registration creation each appear once in `docker compose logs gateway`, with the request id, method, path, upstream status and duration |
| Web E2E workflow with `WEB_BASE_URL=http://127.0.0.1:9000` | Passed: CSRF-protected form login, registration create/edit/delete and cleanup all work with the interface served through the gateway |
| Flask UI test-client checks | Form submissions, server-side token handling, role gating, and API error display are covered in `tests/unit/test_web_app.py` |
| Flask UI routes | Home, event listing, and login pages returned HTTP 200; the Playwright workflow created, read, and deleted a registration through UI forms and verified API state |
| Post-run application state | The test verified its registration, Client, and event were deleted and both tokens were revoked; the API event listing contained no Playwright test event afterward |
| `git diff --check` | Passed |

The E2E command intentionally selects only the `e2e` marker; `53 deselected` in that run is expected and does not mean those tests failed.

### Re-validated after the service split (2026-11-25)

The three backend services moved into `services/<name>/`, each with its own `Dockerfile`, `requirements.txt` and image, over a shared `common/` package; the combined application was removed. The checks below were re-run after that change. The rows in the table above that are not repeated here were **not** re-run and remain the 2026-11-23 record.

| Command/check | Result |
| --- | --- |
| `ruff check .` | All checks passed |
| `python -m compileall -q common services web scripts` | Clean |
| `pytest -q tests/unit` | 53 passed — the same count as before the split, with `test_api.py`'s 16 tests redistributed across `test_accounts_api.py` (6, including the restart test), `test_events_api.py` (3), `test_registrations_api.py` (3) and `test_common.py` (4) |
| `pytest -q` | 53 passed, 3 skipped (the E2E tests, no service/credential environment set) |
| Four independent image builds | `docker build -f services/<service>/Dockerfile .` succeeded for `accounts`, `events` and `registrations`, and `-f web/Dockerfile` for `web`. Backend images 227 MB each, web 217 MB, against 239 MB for the single combined image they replace |
| Image isolation | Each backend image holds `common/` and only its own service folder — no other service's code. The web image holds neither `common/` nor any service folder, so it ships no FastAPI and no database driver |
| `docker compose up --build -d --wait` | All five containers reported healthy |
| `GET /health` on the gateway | HTTP 200 naming all four targets: `accounts:8000`, `events:8000`, `registrations:8000`, `web:5000` |
| Per-service documentation through the gateway | `/docs/accounts`, `/docs/events` and `/docs/registrations` each returned HTTP 200 with disjoint path sets: 6 paths, 2 paths and 2 paths respectively |
| `GET /docs`, `/openapi.json`, `/redoc` | HTTP 404 — confirming no combined documentation path survives the split |
| `GET /api/v1/nonsense` | HTTP 404 with the gateway's own `{"detail":"No service owns this path."}` |
| `GET /` through the gateway | HTTP 200 |
| `API_BASE_URL=... GATEWAY_BASE_URL=... WEB_BASE_URL=... pytest -q -m e2e -rs` with `.env` loaded | 3 passed, 53 deselected — the full E2E suite, including the Playwright web-form workflow |
| Stale-reference sweep | No `app.main`, `app.services`, `app/api`, `app/core`, `app/models`, `app/schemas` or `app/locales` reference remains in any `.py`, `.yml`, `.md`, `.ini`, `.toml` or `Dockerfile` |
| Workflow YAML | All workflow files parse, each with the expected job and triggers (seven at this point; `service-gateway.yml` was added by the follow-on change below, making eight) |

### Usability remediation and the profile screen (2026-11-25)

Two changes after the split: the six high-severity findings of the heuristic evaluation (see [usability-evaluation.md](usability-evaluation.md)), then a Client profile screen with the ownership model it requires. Checks re-run after both:

| Command/check | Result |
| --- | --- |
| `ruff check .` | All checks passed |
| `python -m compileall -q common services web scripts` | Clean |
| `pytest -q tests/unit` | 74 passed, up from 53: 6 cases for the usability fixes and 15 for the profile and ownership work. `test_api.py`'s former 422 assertion was re-pointed from the removed `HTTP 422:` transport format to the user-facing text and the field it binds to |
| `pytest -q -m e2e` with `.env` loaded and the stack up | 3 passed, 74 deselected. The web workflow now also drives `/profile`, and its Client-record deletion moved to the Administrator session, which is who may do it |
| Tests re-pointed, not deleted | `test_common.py`'s four localization assertions moved to `/api/v1/events/404`, which stays public; `test_services.py` gained `/api/v1/users/me`; the user-CRUD assertions in `test_accounts_api.py` gained Administrator headers |
| Colour contrast measured from the tokens | The two placeholder failures (2.44:1 on login, 2.99:1 elsewhere) raised to 5.92:1 and 6.04:1. Every other pair already passed; see the table in the evaluation |
| Delete confirmation, by hand through the gateway | `GET /events/<id>/delete` returned 200 naming the record, and the record still existed afterwards; the subsequent `POST` deleted it and the API then answered 404 |
| Field-level errors, by hand | A non-integer `age` produced `<a href="#age">` in the summary plus an inline message bound with `aria-describedby`; entered values were preserved and the password never echoed |
| Ownership, by hand through the gateway | Anonymous `GET /api/v1/users` 401; as a Client, own record 200, another Client's 403 on `GET`, `PATCH` and `DELETE`, and the list 403; as an Administrator, 200. `/users` in the browser: 302 signed out, 403 as a Client, 200 as an Administrator; `/users/new` stayed 200 for anyone |
| Profile screen, by hand | `/profile` showed the signed-in Client's own values; a rename persisted and followed into the header; a mismatched password confirmation returned 400, reported on the confirmation field and made no API call; a matching one changed the password, after which the old password returned 401 and the new one 200 |
| Bootstrap Administrator profile | `/profile` returned 200 with "No stored account" and no form, rather than erroring — it authenticates from environment variables and has no `users` row |
| Probe data removed | Every account and event created by the manual checks was deleted afterwards and verified absent |

Then the gateway was given its own `Dockerfile` and image, so that it too is a self-contained artifact rather than stock nginx plus a bind-mounted config. `gateway.conf.template` was **not** modified. Re-checked:

| Command/check | Result |
| --- | --- |
| `docker build -f gateway/Dockerfile ./gateway` | Built. Context is `gateway/` alone — the gateway needs nothing from `common/` |
| `nginx -t` on the rendered configuration | Syntax ok, test successful. The image entrypoint renders the template whenever the command is `nginx`, so this validates the rendered file rather than the template |
| Rendered configuration complete | All four upstreams substituted, `/health` fully rendered, and the only surviving `GATEWAY_` mention is prose in a comment. Negative control: dropping one variable leaves a `${GATEWAY_…}` placeholder, which both `nginx -t` and the placeholder check reject |
| `NGINX_ENVSUBST_FILTER` behaviour | Verified as a **guard, not a fix**: omitting it does not blank `$request_id`, because the entrypoint substitutes only variables that exist in the environment and none of nginx's own names collide with the container's. It is kept because a future colliding variable would otherwise corrupt the config silently |
| Stock `conf.d/default.conf` removed | Absent from the image; `nginx -T` shows no `listen 80` server, so the gateway answers on 9000 alone |
| `docker compose up --build -d --wait` | All five containers healthy, the gateway now running `local/unibz-m2ci-gateway:latest` with **0 mounts** — its configuration comes entirely from its image |
| Routing unchanged from the new image | `/health`, `/docs/{accounts,events,registrations}/openapi.json` and `/api/v1/events` returned 200; `/api/v1/nonsense` returned the gateway's own 404 JSON; `/` returned 200; an unauthenticated `POST /api/v1/events` relayed 401 with `www-authenticate: Bearer` |
| `pytest -q -m e2e -rs` | 3 passed, 53 deselected. `tests/e2e/test_gateway_forwarding.py` passed **unmodified** — behaviour is identical, only packaging moved |
| `pytest -q tests/unit` and `ruff check .` | 53 passed; all checks passed |
| The new edit loop | Confirmed in both directions: after editing the template, `docker compose restart gateway` serves the **old** body, and `docker compose up -d --build gateway` serves the new one. The probe edit was reverted |
| CI job simulated locally under bash | Both validation steps pass on a correct render and fail on an incomplete one |

## From code change to a running version

1. Make a change and run `pytest -q tests/unit` locally. Before exercising the integrated HTTP workflow, start Compose and run `pytest -q -m e2e` with the bootstrap settings above. The same checks run automatically, but no longer as one workflow: each service has its own pipeline, so they do not wait on each other to go green.

   | Workflow | Job | Runs |
   | --- | --- | --- |
   | `service-accounts.yml`, `service-events.yml`, `service-registrations.yml` | `build-and-test` | compiles `common/` and that service, builds that service's image from its own `Dockerfile`, runs that service's unit test file, writes a results table to the run summary and uploads the JUnit report |
   | `service-web.yml` | `build-and-test` | the same for `web/` and `tests/unit/test_web_app.py` |
   | `service-gateway.yml` | `build-and-validate` | builds the gateway image, runs `nginx -t` against the **rendered** configuration, and fails if any `${GATEWAY_…}` placeholder survived rendering. No Python and no pytest — the gateway has no unit tests by design |
   | `shared.yml` | `shared` | compiles every tree and runs the three suites no single service owns: `test_services.py` (the split contract), `test_common.py` (the shared foundation) and `test_api_cli.py` |
   | `e2e.yml` | `e2e` | starts the Compose stack with generated bootstrap credentials and runs `pytest -q -m e2e`, failing if any E2E test is skipped |
   | `lint.yml` | `ruff` | `ruff check` over the repository, reported as annotations; run it locally with `ruff check .` |

   The four per-service workflows are path filtered on their own folder plus `common/`, so a change touching one service leaves the others **not running** rather than passing — intended, but it means none of them should be made a required status check without accounting for skipped runs. `shared.yml`, `e2e.yml` and `lint.yml` are unfiltered and run on every branch push, every pull request, and manual dispatch.
2. To run the changed application locally, use `docker compose up --build` (or `docker compose up --build -d` to continue using the terminal). Compose builds five images, one per container, and starts them: the `accounts`, `events` and `registrations` services, the Flask UI, and the gateway. One port is published, `127.0.0.1:9000`, and it is the whole application's entry point; everything else is reachable only over the Compose network.
3. **There is no automated publishing.** `.github/workflows/publish-image.yml` was removed together with the single combined image it pushed, so no `v*` tag triggers a release and the `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` secrets are unused. The delivery path now ends at a green CI run plus a local `docker compose up --build`.

   To push by hand, set `DOCKERHUB_USERNAME` and `IMAGE_TAG`, `docker login`, then `docker compose build accounts events registrations web` and `docker compose push accounts events registrations web`. Each image is the architecture of the machine that builds it; `docker buildx build --platform linux/amd64,linux/arm64 -f services/<service>/Dockerfile .` produces a multi-architecture manifest for one service. Publishing is deferred deliberately while the service boundaries are still moving, and there is no configured deployment target or automatic rollout either; deploying an image to a running host remains a manual operational step.

## Manual steps, delays, and likely failure points

- **Local setup:** create/activate the virtual environment, install development packages, and set a non-empty bootstrap password. A fresh dependency installation requires package-index access.
- **Starting the application:** Docker must be installed and its daemon running. The first Compose build may need to download the Python base image, the application dependencies and the `nginx:1.27-alpine` image. Port `9000` must be available on the host. The three backend services start first, the UI next, and the gateway last, so nothing reaches the gateway before the back end is healthy.
- **E2E configuration:** source the same `.env` used by Compose into the shell running pytest. A wrong `API_BASE_URL`, missing credentials, or running the test before the API is ready causes the E2E check to skip or fail to connect; check the skip count and OpenAPI readiness command rather than treating a skipped test as a pass.
- **Persistent data:** Compose keeps SQLite data in a named volume. The test cleans only records it created; avoid deleting the volume to reset the test.
- **Image publishing:** entirely manual now that the publish workflow is gone. `docker login`, a `DOCKERHUB_USERNAME`, and `docker compose build`/`push` per service are all prerequisites, and nothing in CI verifies that an image reached a registry.
- **Deployment:** publishing does not start or update an application server. The repository currently documents local Compose execution and manual image publication, but not a remote deployment mechanism.
