# NILTV Dashboard

Analytics dashboard for Duke NIL athlete social media metrics.
Pulls data from Instagram and Zoomph (both via official APIs).

dashboard.niltv.com

---

## Getting Started

```bash
git clone git@github.com:NILTVdev/niltv-dashboard.git
cd niltv-dashboard                  # checks out dev, the default branch
docker compose up                   # db + API :8000 + dashboard :3000, no login
```

That's the full loop: a local database, API and dashboard with no auth and no
secrets. The dashboard reloads as you edit `frontend/`. See
[Local (recommended)](#local-recommended) for seeding data and for running
without Docker.

**Before you push:**

```bash
cd frontend
npm install
npm run build && npm run lint        # the same gate CI runs
```

Push a **branch** and open a PR against `dev`. See
[Shipping a change](#shipping-a-change) for the full loop.

## How to test

**Local.** Full stack with no auth and no secrets:

```bash
docker compose up                                                        # db + API :8000 + dashboard :3000
python -m pytest backend/tests -q                                        # backend tests (CI runs these)
cd frontend && npm run build && npm run lint                             # the frontend gate CI runs
```

Without Docker, see [Local (recommended)](#local-recommended) for the
Postgres + `uvicorn` + `npm run dev` path.
Open http://localhost:3000; the login page is skipped, and
http://localhost:3000/api/health says whether the frontend can reach the API.

**Dev.** Open a PR against `dev` (the default branch). CI runs lint, type-check,
build, migrations and tests on the PR. Merge, and the backend deploys to the
dev API and Amplify builds the `dev` branch; a build that cannot reach
its backend fails in Amplify before it goes live. Then test at
https://dev.d3nvp99dnw61rc.amplifyapp.com with the dev login. Nightly jobs are
not scheduled on dev, and nothing writes to S3 or SNS unless
`ALLOW_SIDE_EFFECTS=1` is set.

**Prod.** Release with a PR from `dev` into `main`. Production deploys the same
way, with the same build check. https://dashboard.niltv.com/api/health reports
the built commit and whether the API key in the build matches the backend.

---

## Environments

Three tiers, one code path. `ENVIRONMENT` (backend) and `AUTH_DISABLED`
(frontend) pick the behaviour; nothing else changes between them.

| | **local** | **dev** | **production** |
|---|---|---|---|
| Where | your machine (`docker compose up`) | `dev` branch → dev API + Amplify `dev` branch | `main` → production API + Amplify `main` |
| Auth | **off** (`ENVIRONMENT=local`, `AUTH_DISABLED=true`) | login + `X-API-Key`, dev-only secrets | login + `X-API-Key` |
| Data | empty, or loaded with `scripts/seed_local.py` | shared dev data, tokens stripped | live |
| Nightly jobs | not scheduled | not scheduled; side effects suppressed | scheduled |
| S3 / SNS / CloudWatch | off | off unless `ALLOW_SIDE_EFFECTS=1` | on |
| API docs | on | on | off |
| Migrations | `scripts/migrate` on start | `scripts/migrate` on deploy | `scripts/migrate` on deploy |
| Health | `localhost:3000/api/health` | [dev.d3nvp99dnw61rc.amplifyapp.com/api/health](https://dev.d3nvp99dnw61rc.amplifyapp.com/api/health) | [dashboard.niltv.com/api/health](https://dashboard.niltv.com/api/health) |

Safety rails: the backend **refuses to start** in `ENVIRONMENT=local` unless
`DB_HOST` is a local database, and the frontend ignores `AUTH_DISABLED` in a
production build, so neither bypass can ever front the dev or prod database.

How a change moves through the tiers is in [Shipping a change](#shipping-a-change).

### Shipping a change

`dev` is the default branch. Every change goes through it before it reaches
production.

1. **Branch from `dev`** and open a PR against `dev`. That is the default base
   for `gh pr create` and the GitHub UI. CI runs lint, type-check, build,
   migrations and tests on the PR.
2. **Merge to `dev`.** The backend deploys to the dev API and Amplify
   builds the `dev` branch. The build's postBuild step makes the same keyed
   backend call every page makes, so a build that cannot authenticate fails
   in Amplify and the previous build stays live.
3. **Test on the dev dashboard** with the dev login.
4. **Release** with a PR from `dev` into `main`. Merging deploys production the
   same way, with the same verification.

Guard rails:

- **Checks** (the secret scan and the PR base rule in one run) fails any PR
  into `main` that does not come from `dev`, a
  `hotfix/*` branch or a `revert-*` branch, and comments how to retarget. If a
  retarget with `gh pr edit --base` prints a GraphQL error about projects, it
  did not apply. Check with `gh pr view --json baseRefName` or use the Edit
  button in the PR.
- **Hotfixes** go to `main` on a `hotfix/*` branch. Merge `main` back into
  `dev` right after so the branches do not drift.
- **Reverting a release** means a `revert-*` PR into `main`. Bring the fix back
  through `dev` as a fresh commit (`git cherry-pick`), never by merging the
  original branch again: git treats the original commit as already in `main`,
  and the next release would keep the revert and drop the feature.
- **Environment variables** for the frontend live on the Amplify **branch**
  (`dev` and `main` each carry their own `INTERNAL_API_URL` and `DASHBOARD_*`).
  Never set a per-environment value at the app level: it applies to every
  branch, and the next build of the other branch ships it. The build spec is
  `amplify.yml` in this repo.

### Local (recommended)

```bash
docker compose up                                   # db + API (:8000) + dashboard (:3000), no login
docker compose exec api python -m scripts.seed_local --backups seed/backups   # optional: load a backups folder
```

The local database starts empty. `scripts/seed_local.py` loads a folder of
backup JSON files (default `seed/backups/`, gitignored) into it. It refuses to
run against production.

Without Docker: `cp .env.local.example .env`, start Postgres on 55432 (or edit
`DB_PORT`), then `python -m scripts.migrate && uvicorn backend.main:app --reload`;
in `frontend/`, `cp .env.example .env.local` (the local preset is the default)
and `npm run dev`.

### Migrations

`python -m scripts.migrate` applies every `backend/migrations/*.sql` not yet
recorded in `schema_migrations`, in order, one transaction each; `--status`
lists applied/pending, `--dry-run` previews. A database that was migrated by
hand before the runner existed is adopted once with
`python -m scripts.migrate --fake 026` (records 001–026 without running them).
CI applies the whole chain against a throwaway Postgres with the same runner.

**Never against production:** hand-applied migrations ([backend/migrations/](backend/migrations/),
no version tracking / rollback), the cron jobs (`python -m backend.jobs.run_*`,
they write rows + push S3/SNS), and the upload `POST` routes.

---

## Layout

```
backend/      FastAPI app, routers, models, jobs, migrations, tests
frontend/     Next.js app (see frontend/README.md)
scripts/      operator scripts (migrations, seeding, roster import, brand accounts)
.github/      CI and deploy workflows
```

Hosting and third-party integration setup are not covered in this repository.

## Environment Variables

Copy `.env.example` to `.env` 
`.env` is gitignored — never commit real values;

| Variable | Description |
|---|---|
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` | Postgres connection (the compose database listens on `127.0.0.1:55432`) |
| `DB_PASS` | PostgreSQL password for `niltv_user` |
| `IG_ACCESS_TOKEN` | Instagram long-lived token (60-day expiry) |
| `IG_BUSINESS_ID` | Your IG Business account ID (hub for Business Discovery) |
| `ZOOMPH_API_KEY` / `ZOOMPH_FEED_ID` | Zoomph access token + feed ID |
| `AWS_S3_BUCKET` | S3 bucket name for JSON backups |
| `AWS_SNS_TOPIC_ARN` | SNS topic ARN for failure email alerts |
| `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` | Dashboard login (password also acts as the API key) |

Frontend-only contributors don't need the third-party tokens — placeholder values
are fine to boot a local backend if you aren't exercising that integration.

The frontend reads `INTERNAL_API_URL`, `DASHBOARD_USERNAME`, `DASHBOARD_PASSWORD`
and (optionally) `DASHBOARD_API_KEY` from `frontend/.env.local` on your machine
and from the Amplify branch settings on dev and prod. `DASHBOARD_API_KEY` must
match the backend it points at; `/api/health` on the deployed site tells you if
it does not.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/athletes` | All active athletes with latest snapshot |
| GET | `/api/athletes/{id}` | Single athlete detail |
| GET | `/api/snapshots/athletes/{id}` | Historical follower snapshots |
| GET | `/api/posts/athletes/{id}` | Recent IG posts |
| GET | `/api/zoomph` | Zoomph posts (filter with `?platform=Instagram`) |
| GET | `/api/zoomph/summary` | Aggregated stats by platform |

Interactive docs: `http://localhost:8000/docs` on the local stack.

---

## Secret hygiene

Every commit is scanned for secret-shaped strings, locally and in CI.

1. Install gitleaks once: `go install github.com/zricethezav/gitleaks/v8@v8.24.3` (or `brew install gitleaks`).
2. Point git at the repo's hooks once per clone: `git config core.hooksPath .githooks`.

The `Checks` workflow runs the same scan over the full history on every pull request and every push to `main`. Real credentials live in an ignored `.env` file or in GitHub Actions secrets, never in the tree. If one ever lands in a commit, rotate it first, then rewrite history.

Maintainer clones and CI also run a supplementary scan from a private rule file.

## License

The code in this repository is released under the MIT License (see
[LICENSE](LICENSE)). The license covers the code only. It does not grant any
right to:

- the NIL TV, NIL Star and TrueBlueTV names and logos, the campus channel
  marks, or any third-party brand, school, conference or league mark that
  appears in the assets;
- photographs, video, captions and other media of athletes and other people;
- athlete, applicant, subscriber and partner data, including anything the
  pipelines in this repository produce.

Third-party components keep their own licenses; see THIRD_PARTY_NOTICES.md
where present.
