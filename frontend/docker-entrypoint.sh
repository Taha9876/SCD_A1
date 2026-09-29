#!/bin/sh
# Generate the runtime configuration, then hand off to nginx.
#
# This script is the reason one frontend image runs in dev, in CI and on the
# cluster. A Vite build inlines import.meta.env values into the static
# JavaScript, so anything read that way is frozen at BUILD time and the image
# becomes environment-specific. Instead the browser loads /config.js, which is
# written here at CONTAINER START from environment variables.
#
#   API_BASE_URL     '' (default) means same origin: nginx proxies /api.
#                    Set it only when the backend is on a different origin.
#   BACKEND_ORIGIN   where nginx sends /api. A service name, never localhost.
#   OTEL_COLLECTOR_ORIGIN
#                    optional (bonus tracing). When set, e.g. http://jaeger:4318,
#                    nginx proxies same-origin /otel/v1/traces to it and the
#                    browser is told to export spans there. Unset: no tracing,
#                    no proxy location, and the tracing chunk is never loaded.
#
# See docs/adr/0002-frontend-runtime-config.md.

set -eu

API_BASE_URL="${API_BASE_URL:-}"
BACKEND_ORIGIN="${BACKEND_ORIGIN:-http://backend:8000}"
OTEL_COLLECTOR_ORIGIN="${OTEL_COLLECTOR_ORIGIN:-}"

# /tmp, not the web root. Under Kubernetes the root filesystem is read-only and
# /tmp is a writable emptyDir; under Compose /tmp is simply writable. nginx
# serves this file at /config.js (see nginx.conf). An earlier version wrote into
# /usr/share/nginx/html via a subPath mount -- but a subPath of an empty volume
# makes Kubernetes create a DIRECTORY named config.js, and every pod crash-looped.
CONFIG_PATH=/tmp/config.js

# No secrets here, ever: anything written into this file is served to every
# browser that loads the page. "It is minified" is not a defence, and neither
# is "nobody will look".
OTEL_EXPORTER_URL=""
OTEL_LOCATION_PATH=/tmp/otel-location.conf
if [ -n "$OTEL_COLLECTOR_ORIGIN" ]; then
  OTEL_EXPORTER_URL="/otel/v1/traces"
  # Exact-match location, POST only: this proxies trace export and nothing
  # else, so it cannot be used to reach the collector's other endpoints.
  cat > "$OTEL_LOCATION_PATH" <<LOCATION
location = /otel/v1/traces {
    limit_except POST { deny all; }
    client_max_body_size 1m;
    proxy_pass ${OTEL_COLLECTOR_ORIGIN}/v1/traces;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    access_log off;
}
LOCATION
else
  # nginx.conf always includes this file, so it must exist even when empty.
  : > "$OTEL_LOCATION_PATH"
fi

cat > "$CONFIG_PATH" <<CONFIG
// Generated at container start by docker-entrypoint.sh. Do not edit.
window.__CIVICPULSE_CONFIG__ = {
  apiBaseUrl: "${API_BASE_URL}",
  otelExporterUrl: "${OTEL_EXPORTER_URL}"
};
CONFIG

# Substitute only BACKEND_ORIGIN. Naming the variable matters: a bare envsubst
# would also eat nginx's own $host, $remote_addr and $uri and produce a config
# with empty proxy headers.
envsubst '${BACKEND_ORIGIN}' \
  < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf

echo "civicpulse-frontend: apiBaseUrl='${API_BASE_URL:-<same origin>}' backend='${BACKEND_ORIGIN}' tracing='${OTEL_COLLECTOR_ORIGIN:-off}'"

# exec, so nginx becomes PID 1 and receives SIGTERM directly. Without exec the
# signal stops this shell and nginx is left to be SIGKILLed.
exec "$@"
