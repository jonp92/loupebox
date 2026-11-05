# Develop Loupebox

Loupebox is a FastAPI and Postgres server, a React admin app in `web/`, an embeddable widget in `web/widget/`
and a background worker. The code is on [GitHub](https://github.com/jonp92/loupebox). Read
[CONTRIBUTING.md](https://github.com/jonp92/loupebox/blob/master/CONTRIBUTING.md) before you open a pull
request. Contributions need a DCO sign-off (`git commit -s`).

## Run it without Docker for the app

```bash
./scripts/setup.sh && docker compose up -d db   # writes .env, then starts only Postgres
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
python -m scripts.create_superadmin you@example.com
uvicorn app.main:app --reload                   # API at http://127.0.0.1:8000
python -m app.worker                            # sends alerts; nothing is sent without it

cd web && cp .env.example .env && npm install && npm run dev   # admin app at http://localhost:5173
```

## Tests

`pytest` runs the suite on in-memory SQLite. To run it on Postgres, set `TEST_DATABASE_URL` to a **throwaway**
database, because the suite drops all its tables. `ruff check .` runs the linter.

In `web/`, `npm run build` type-checks and builds the admin app and the widget. `npm test` builds the widget and
runs its tests.

## The documentation site

The pages are Markdown files in `docs/`, built with [Zensical](https://zensical.org):

```bash
pip install -r requirements-docs.txt
zensical serve        # preview at http://localhost:8000
zensical build        # writes the site to site/
```

Screenshots are made by `scripts/docs_screenshots.mjs` (the admin app) and `scripts/docs_widget_screenshot.mjs` (the widget). See the comment at the top of each file.

## Add a notification provider or challenge

Providers (`app/notifications/providers/`) and challenge verifiers (`app/challenges/verifiers/`) register with
a decorator, and every module in those folders is loaded at start. Add a file, not an entry in a list.

## Widget

Source is TypeScript in `web/widget/src` (one small module per concern). `npm run build` in `web/` builds the
admin app and the widget (`dist/widget/v1/loupebox.js`, about 11 kB gzipped, plus type declarations in
`dist/widget/v1/types/`). `npm test` rebuilds the widget and runs its tests against the built file, using
Node's test runner and jsdom. The web Docker image serves it with the CORS headers browsers need for module
scripts. When adding a feature: add an optional option (give it a default in `options.ts`), add a `capabilities`
entry, document it in `docs/collect/widget.md`, and keep the v1 promise in the widget docs.
