# UI language switcher and API documentation page

Date: 2026-11-25

## Intent

Two things the web interface cannot do today: let someone choose the language from
inside the page, and reach the Swagger API reference without knowing a URL.

The language half is not a greenfield feature. `APIClient` already accepts an
`accept_language` argument (`web/app.py:62`) and all three call sites already forward
the **browser's** `Accept-Language` header (`:156`, `:193`, `:418`), so a
Spanish-configured browser already receives Spanish API errors. What is missing is an
explicit, in-page choice that overrides the browser.

The harder part is that almost nothing in the interface is translated. The
`common/locales/{en,es}.json` catalogs hold 19 keys and every one is an API *error*
message. The interface's own text is hardcoded English: roughly 61 visible strings
across the 8 templates, 9 `flash()` calls, plus the label columns of `RESOURCE_FIELDS`
and `DETAIL_FIELD_LABELS` — about 90 strings in total. `<html lang="en">` is hardcoded
as well. A switcher that changed only the API messages would leave someone who picks
*Español* looking at an English page with one Spanish error on it, which reads as
broken. So this change localizes the interface itself.

## Goals

- A language control, visible on every page, offering English and Spanish.
- Choosing a language changes the whole interface: navigation, buttons, form labels,
  table headers, flash messages, page titles.
- The choice survives page loads, login, and logout.
- The chosen language is also sent to the API, so an error message matches the page it
  appears on.
- A page in the interface that links to each service's Swagger reference.

## Non-goals

- Any third language. The mechanism must not make one hard, but none is added.
- Extending the API's `MessageKey` catalog; it is already complete in both languages.
- Translating **data**. Event names, descriptions, usernames and places are user
  content and stay exactly as entered.
- Localized date or number *formatting*. Babel can do it, but dates come from the API
  as ISO strings and the forms post them back; reformatting them would mean parsing
  and reserialising on every form round-trip, which risks changing what gets stored.

## Anti-goals — ways this fails even while "working"

- **Silent fallback to English.** Flask-Babel serves the untranslated string when a
  compiled `.mo` is missing or stale. The feature would then appear to work in
  development and quietly do nothing in production. This must fail loudly instead.
- **The web image gaining a dependency on `common/`.** `web/Dockerfile` deliberately
  copies only `web/`; the interface has no backend code and no database driver. The UI
  catalog must live under `web/`, not be shared with the API's.
- **The language resetting when someone logs in or out.** See the constraint below.

## Constraints

- **`login()` and `logout()` both call `session.clear()`** (`web/app.py:176`, `:195`).
  Anything kept in the Flask session is destroyed at both moments.
- The web image must stay self-contained: no `common/`, no service code.
- CSRF protection is global (Flask-WTF), so any state-changing POST needs a token.
- Ruff `select = ["E4","E7","E9","F"]`, target `py312`.
- `.mo` files are compiled artifacts, not source.

## Approaches considered

1. **JSON catalogs plus a `t()` helper** — `web/locales/{en,es}.json` mirroring the
   API's existing catalog shape, with a `translate()` function injected into Jinja.
   No new dependency, no build step, and one localization idiom across the codebase.
   *This was the recommendation.*
2. **Flask-Babel** — the standard tool: `{{ _('Events') }}`, `.po` sources, compiled
   `.mo`, `pybabel extract`/`compile`. Brings real tooling, pluralization and a format
   translators already know. Costs two dependencies and a compile step in the
   Dockerfile, in CI and in local development. **Chosen by the project owner.**
3. **Per-locale template copies** (`templates/es/…`) — dropped. It duplicates all
   eight templates and guarantees they drift apart.

Approach 2 is what gets built. The compile step is the main cost, and the design below
addresses it directly rather than leaving it implicit.

## Design

### Dependencies

`Flask-Babel>=4.0,<5.0` goes in **`web/requirements.txt`** only. The 4.x API matters: it takes the selector as a constructor keyword, `Babel(app, locale_selector=…)`, where 2.x used a `@babel.localeselector` decorator that no longer exists. Initialise it inside the `create_app()` factory (`web/app.py:119`), not at module level, and set `BABEL_DEFAULT_LOCALE = "en"` alongside the app's other config — the backend services never see
it, which keeps their images unchanged. The root `requirements.txt` already does
`-r web/requirements.txt`, so local development and the test suite pick it up with no
further edit. Pin it in the style of the file's other entries.

### Catalog layout and the compile step

- `babel.cfg` at the repository root: extraction rules for `web/**.py` (python) and
  `web/templates/**.html` (`jinja2.ext.babel_extract`).
- `web/translations/{en,es}/LC_MESSAGES/messages.po` — **committed source.**
- `messages.mo` — **not committed**; add `*.mo` to `.gitignore`.
- `messages.pot` — also **not committed** and gitignored; it is regenerated by
  `pybabel extract` and is an intermediate, not source.

First-time creation: `pybabel extract -F babel.cfg -o messages.pot .`, then
`pybabel init -i messages.pot -d web/translations -l en` and the same for `es`.
Afterwards use `pybabel update` so existing translations survive re-extraction.

`.mo` is produced by `pybabel compile -d web/translations` in three places:

| Where | Why |
| --- | --- |
| `web/Dockerfile`, after `COPY web/` | the image must ship compiled catalogs |
| `.github/workflows/service-web.yml`, before pytest | tests assert real translation |
| documented for local dev in `README.md` / `CLAUDE.md` | otherwise the UI silently runs English |

`pybabel` is available wherever Flask-Babel is installed, since Babel is its
dependency — no extra build-only package.

**Guard against the silent fallback.** A unit test asserts that a known string
actually renders in Spanish. If `.mo` is missing or stale, that test fails rather than
the interface quietly serving English. This is the mitigation for the first anti-goal
and is not optional.

### Choosing the locale

Precedence, highest first:

1. the `locale` cookie, if its value is a supported language;
2. `request.accept_languages.best_match(["en","es"])` — today's behaviour, so anyone
   who never touches the switcher sees no change;
3. English.

A Flask-Babel `locale_selector` implements exactly that.

**The choice lives in a cookie, not the session.** Both `session.clear()` calls would
otherwise wipe it at login and logout. A language preference is not sensitive — the
only reason the session is server-side is to keep the bearer token out of the browser,
which does not apply here — and a cookie also survives session expiry and needs no
change to either handler. It respects the existing `WEB_COOKIE_SECURE` config, and
sets `SameSite=Lax` and a long `max_age`.

### The switcher

`GET /language/<locale>`, which validates the locale against the supported list,
aborts 404 otherwise, sets the cookie and redirects back to the page the request came
from (falling back to the index).

**`request.referrer` must not be trusted as a redirect target.** It is attacker-controllable, so an unvalidated redirect is an open-redirect bug. Accept it only when it parses to a relative path with no netloc and no scheme; otherwise redirect to the index. A test should cover an absolute external referrer. A `GET` is appropriate here and needs no CSRF
ceremony: it sets a display preference, not application state, and this keeps the
control to two plain links that work without JavaScript.

In `base.html`'s `.header-actions`, **outside the existing
`{% if session.get('access_token') %}` / `{% else %}` branch** (`base.html:26-35`) so
it appears for signed-in and anonymous visitors alike, rendered as `EN · ES` with the
active language marked as current rather than linked:

```
Event Registration   Events  Clients  My registrations     EN · ES   alex · client  [Log out]
                                                            ^^
                                                      active, not a link
```

### Wrapping the strings

- Templates: `{{ _('…') }}`, across all eight.
- `flash()` calls and route-level messages: `gettext`.
- **`RESOURCE_FIELDS` and `DETAIL_FIELD_LABELS` are module-level**, evaluated at
  import time, outside any request. They must use **`lazy_gettext`**, not `gettext`,
  or they will raise on import. This is the single easiest thing to get wrong here.
- `web/app.py:272` and `:352` build messages with an f-string:
  `flash(f"{resource[:-1].capitalize()} created.")`. That cannot be translated as
  written, because the sentence is assembled from a resource name. Replace with a
  parameterized message whose subject is itself translated, e.g.
  `gettext("%(name)s created.", name=…)` over a small map of translated singulars.
- `<html lang="en">` becomes the active locale.

### Sending the locale to the API

All three `APIClient(...)` constructions replace
`accept_language=request.headers.get("Accept-Language", "")` with
`str(get_locale())` from `flask_babel`. Reuse Flask-Babel's own resolved value rather than re-implementing the precedence rules in a second helper; there must be exactly one place that decides the locale, or the page and its error messages can disagree. so a Spanish page shows Spanish API errors even when the browser asks for
English. This is the one place where the two localization systems meet, and the API
side needs no change — it already honours `Accept-Language`.

### The API documentation page

`GET /docs` in the UI, rendering a new template that links to the three references.

This works because of how the gateway routes: `location /docs/accounts|events|registrations`
go to those services, and bare `/docs` falls through `location /` to the interface.
Verified: `/docs` currently returns the UI's 404.

- The links are **absolute paths** (`/docs/accounts`, …), not `url_for`, because the
  gateway serves them, not Flask. They open in a new tab (`rel="noopener"`).
- There is deliberately **no combined OpenAPI document** — the all-in-one app was
  removed when the services were split — so this is three entries, one per service,
  each labelled with what that service owns. The page should say so, since "three
  Swagger pages" is otherwise surprising.
- A nav link, visible to everyone: the documentation endpoints need no authentication.
- **Route precedence:** Flask must prefer the static `/docs` rule over the existing
  `@app.get("/<resource>")`. Werkzeug ranks static segments above converters, so this
  should hold, but it must be asserted by a test rather than assumed.

### Tests

New, in `tests/unit/test_web_app.py`:

- the switcher sets the cookie and redirects back;
- an unsupported locale is rejected;
- with the cookie set to `es`, a page renders Spanish — **the guard against an
  uncompiled catalog**;
- with no cookie, a Spanish `Accept-Language` header still yields Spanish, and no
  header yields English;
- the resolved locale reaches the API client as `Accept-Language`;
- `/docs` returns 200, links to all three services, and is not swallowed by
  `/<resource>`;
- both `.po` catalogs define the same message ids, **and every `msgid` in `es.po`
  has a non-empty `msgstr`**. The second half matters more than the first: a
  freshly extracted catalog has every `msgstr` empty, so an "identical ids" test
  alone passes while the interface still renders English. This is the counterpart
  of the API's `test_localized_catalogs_define_the_same_messages`, strengthened.

Existing tests should survive: `test_web_app.py` asserts on `"Previous"`, `"Next"` and
`"requires the administrator role"`, all of which stay English under the default
locale. `tests/e2e/test_web_registration_workflow.py:163` asserts on `"My registrations"`
and likewise keeps passing, though it is now translation-sensitive — worth a comment
there.

I also recommend one e2e addition: switch to Spanish and assert the nav label changed.
It is the only check that proves the compiled catalog shipped **inside the image**,
which no unit test can establish.

### Documentation

- `CLAUDE.md` — a "Flask UI specifics" note on the catalogs, `lazy_gettext` for
  module-level labels, and the compile step; the commands table gains the `pybabel
  compile` line.
- `README.md` — the language control and the `/docs` page under the UI section; the
  compile step in local setup.
- `testing-strategy.md` — the new unit tests and the `service-web.yml` compile step.

## Left to the builder

- The Spanish wording itself, beyond matching the tone of the existing `es.json`.
- CSS for the switcher in `web/static/style.css`, following the existing
  `.header-link` / `.identity` treatment.
- Whether the `/docs` page lists the services as cards or a simple list.
