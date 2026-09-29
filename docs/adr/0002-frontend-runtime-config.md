# ADR 0002: Runtime configuration for the frontend

- Status: accepted
- Date: 2026-09-20
- Deciders: both team members

## Context

Vite inlines `import.meta.env.*` into the static bundle at **build** time. So
the obvious approach:

```ts
const API = import.meta.env.VITE_API_URL   // WRONG for our purposes
```

produces an image that works against exactly one backend. Deploying the same
artifact to dev, CI and the cluster would then need three builds — and
build-once-deploy-many is gone, along with any guarantee that the image you
tested is the image you shipped.

## Decision

Two mechanisms, with a clear primary.

**Primary: nginx proxies `/api`.** `frontend/nginx.conf` forwards `/api/` to
`${BACKEND_ORIGIN}`, substituted by `envsubst` at container start. The browser
only ever calls same-origin `/api`, so the bundle contains no backend URL at all
— there is nothing to bake in — and the normal path has no CORS preflight.

**Secondary: `/config.js` for a cross-origin backend.**
`frontend/docker-entrypoint.sh` writes

```js
window.__CIVICPULSE_CONFIG__ = { apiBaseUrl: "${API_BASE_URL}" };
```

into the web root before `exec nginx`. `index.html` loads it with a plain
`<script src="/config.js">` **before** the module bundle, and nginx serves it
`Cache-Control: no-store`, so a redeploy cannot leave a browser holding the
previous environment's config. `apiBaseUrl()` in `frontend/src/api/client.ts`
reads it and defaults to `''`, meaning same origin.

`vite build` warns that `/config.js` "can't be bundled without type=module".
That warning is the feature working: the file must not be bundled.

## Consequences

**Good.** One image runs everywhere. `docker run -e BACKEND_ORIGIN=...` is the
entire deployment interface. The Kubernetes manifests set `API_BASE_URL: ""` and
`BACKEND_ORIGIN: http://backend:8000` and nothing else. Two tests in
`frontend/tests/StatsView.test.tsx` assert the runtime lookup, so a regression
back to `import.meta.env` fails CI.

**Bad.** One more moving part at container start: if `envsubst` is missing, the
nginx config renders with an empty `proxy_pass` and every `/api` call 502s. The
entrypoint prints the resolved values on startup precisely so that shows up in
`docker compose logs` immediately.

**Bad.** With `readOnlyRootFilesystem: true` in Kubernetes the entrypoint needs
writable `emptyDir` mounts for `config.js`, `/etc/nginx/conf.d`,
`/var/cache/nginx` and `/tmp` — four extra volumes in `k8s/base/frontend.yaml`
to keep the root filesystem read-only. Worth it.

**Note on secrets.** Nothing secret may ever go into `config.js`. It is served
to every browser that loads the page. "It is minified" is not a defence.

## Alternatives rejected

- **Build per environment.** Three images for one commit, and no way to prove
  the tested one is the deployed one.
- **Fetch config from `/api/config` on boot.** Adds a blocking round trip before
  first render, and creates a chicken-and-egg problem: you need the API URL to
  fetch the API URL.
- **A ConfigMap-mounted `config.js`.** Works on Kubernetes, does nothing for
  Compose, so we would still need the entrypoint for local development.
