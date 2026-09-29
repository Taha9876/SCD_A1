/**
 * Browser half of the trace (bonus): frontend -> backend -> LLM as one trace.
 *
 * The fetch instrumentation opens a span for every call the app makes and adds
 * a W3C `traceparent` header to it. The backend's FastAPI instrumentation
 * continues that trace (backend/app/tracing.py), and its httpx instrumentation
 * carries it on to the model provider. One submit, one waterfall.
 *
 * This module is only ever loaded by a dynamic import in main.tsx, and only
 * when /config.js carries an exporter URL -- so with tracing off, not a byte
 * of OpenTelemetry is downloaded, and the default bundle is unchanged.
 *
 * Spans are posted to the same origin (/otel/v1/traces), which nginx proxies
 * to the collector. Same reasoning as /api: no CORS, no collector URL baked
 * into the bundle, and the collector's port is never exposed to the internet.
 */
import { registerInstrumentations } from '@opentelemetry/instrumentation'
import { FetchInstrumentation } from '@opentelemetry/instrumentation-fetch'
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http'
import { resourceFromAttributes } from '@opentelemetry/resources'
import { BatchSpanProcessor, WebTracerProvider } from '@opentelemetry/sdk-trace-web'
import { ATTR_SERVICE_NAME } from '@opentelemetry/semantic-conventions'

export interface TracingOptions {
  exporterUrl: string
  /** Set only when the API is on another origin (API_BASE_URL). */
  apiBaseUrl?: string
}

export function startTracing({ exporterUrl, apiBaseUrl }: TracingOptions): WebTracerProvider {
  const provider = new WebTracerProvider({
    resource: resourceFromAttributes({ [ATTR_SERVICE_NAME]: 'civicpulse-frontend' }),
    // Batched, so exporting never competes with the request being traced.
    spanProcessors: [new BatchSpanProcessor(new OTLPTraceExporter({ url: exporterUrl }))],
  })
  // Installs the W3C trace-context propagator: this is what writes `traceparent`.
  provider.register()

  registerInstrumentations({
    tracerProvider: provider,
    instrumentations: [
      new FetchInstrumentation({
        // Never trace the exporter's own POSTs, or every export makes a span
        // that needs exporting.
        ignoreUrls: [/\/v1\/traces/],
        // Same-origin /api gets the header automatically. A cross-origin API
        // needs listing explicitly, and must allow the header in its CORS.
        propagateTraceHeaderCorsUrls: apiBaseUrl ? [new RegExp(`^${escapeRegExp(apiBaseUrl)}`)] : [],
        clearTimingResources: true,
      }),
    ],
  })
  return provider
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
