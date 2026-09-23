# NILTV Dashboard — Frontend

Next.js 16 (App Router) + React 19 + TypeScript + Tailwind CSS v4 dashboard for
Duke NIL athlete social-media analytics. Charts via Recharts, tables via
TanStack Table. Hosted on **AWS Amplify**.

See the [root README](../README.md) for backend, infrastructure, and architecture.

## Development

```bash
npm install
cp .env.example .env.local   # then fill in the values (see below)
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). With the local preset the
login page is skipped; otherwise log in with `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`.

The frontend never talks to the database directly. It only calls the backend
API over HTTP, so point `INTERNAL_API_URL` at a local backend (`docker compose up`
in the repo root) or at the dev API. The upload routes (`/api/brand/upload`,
`/api/trueblue/upload`) `POST` and write to the database behind that API.

Before pushing, always run `npm run build` and `npm run lint` locally — Amplify
deploys `main` automatically and a type/lint error will break the live site.

## Environment Variables

Copy `.env.example` to `.env.local` for local dev; deployed builds read the
same vars from the Amplify branch settings. `.env.local` is gitignored — never
commit real values.

| Variable | Description |
|---|---|
| `INTERNAL_API_URL` | Backend API base URL used by server components. `http://localhost:8000` for a local backend, or `https://api-dev.niltv.com` for dev. |
| `DASHBOARD_USERNAME` | Login username (validated server-side in `app/api/auth/route.ts`). |
| `DASHBOARD_PASSWORD` | Login password. Also used as the `X-API-Key` when `DASHBOARD_API_KEY` is unset. |
| `DASHBOARD_API_KEY` | Key the server attaches as `X-API-Key` to backend calls. Must match the backend's `DASHBOARD_API_KEY` (or its `DASHBOARD_PASSWORD` if that is unset). |
| `AUTH_DISABLED` | `true` skips the login page and cookie check. Honoured only when `NODE_ENV` is not `production`, i.e. never on Amplify. Pair with a backend running `ENVIRONMENT=local`. |

Ask a maintainer for the dev values.

## Build

```bash
npm run build
npm run start
```

## Deployment

Pushes to `main` are built and deployed automatically by AWS Amplify.
