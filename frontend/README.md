# Termkeeper frontend

A standalone Vite + React + TypeScript app that talks to the Django backend
(`reporting` app's JSON API) exclusively over HTTP. No server-side
rendering, no shared build tooling, no dependency on the Django project -
see `openspec/changes/add-react-frontend/design.md` in the repo root for
the full contract this project is built against.

## Develop

```bash
npm install
cp .env.example .env.local   # adjust VITE_API_BASE_URL if the backend isn't on :8000
npm run dev                  # http://localhost:5173
```

The Django backend must be running separately (`python manage.py runserver`
on :8000 by default) with CORS configured to allow the Vite dev origin.

## Verify

```bash
npm run build   # tsc -b && vite build - zero TypeScript errors
npm run test    # vitest run
```

## Layout

- `src/api/types.ts` - TypeScript mirrors of the backend's DRF serializers.
- `src/api/client.ts` - a small typed `fetch` wrapper; every function throws
  a typed `ApiError` on a non-2xx response or a network failure.
- `src/components/` - shared UI: `SeverityBadge`, `Layout`, `LoadingState`,
  `ErrorState`.
- `src/pages/` - `ContractListPage` (`/`), `ContractDetailPage`
  (`/contracts/:id`), `GuardrailPage` (`/guardrail`).
