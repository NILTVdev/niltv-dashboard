# GitHub Workflows

The branch flow these serve: feature branch -> PR into `dev` (the default
branch) -> merge deploys the dev stack -> PR from `dev` into `main` deploys
production. See the root README, "Shipping a change".

## Checks (`checks.yml`)

Runs on every PR and on pushes to `main`. One job covers two checks:

- **PR base rule.** Any PR into `dev` passes. A PR into `main` passes only when
  the head branch is `dev`, `hotfix/*` or `revert-*`; otherwise it fails,
  comments once with the retarget instructions, and re-runs when the base is
  edited so the PR goes green after the fix. This is what stops a feature
  branch from deploying straight to production.
- **Secret scan.** gitleaks scans every commit reachable from the ref with the
  default rules (`.gitleaks.toml`).

## Frontend CI (`frontend-ci.yml`)

Runs on PRs touching `frontend/` and on pushes to `main`. Installs deps, lints,
type-checks (`tsc --noEmit`), runs the unit tests (`npm test`) and runs
`next build`. All data-fetching pages are `force-dynamic`, so the build needs
no API access or secrets. This is the gate that stops a broken frontend from
reaching Amplify.

## Backend CI (`backend-ci.yml`)

Runs on PRs touching `backend/`, `scripts/migrate.py` or `requirements.txt`,
and on pushes to `main`. Spins up a throwaway Postgres 15 service and:

1. Installs deps, `ruff` and `pytest`
2. Lints for fatal errors only (`E9,F63,F7,F82`), which keeps noise low on
   existing code
3. Syntax-checks all of `backend/` (`compileall`)
4. Applies every migration with `scripts/migrate`, the same runner the deploy
   uses
5. Runs the functional tests (`pytest backend/tests`)

Uses dummy env values, so no real credentials are required.

## Deploy Backend (`deploy-backend.yml`)

Runs on pushes to `main` or `dev` that touch `backend/`, `scripts/`,
`requirements.txt`, or the workflow file itself. `main` deploys the production
API and `dev` the dev API. A final smoke check requests the public
`/api/health` and fails the run if it does not return 200 within a minute.

The recurring data-pull jobs are not GitHub Actions workflows. Their schedule
is defined in this workflow.
