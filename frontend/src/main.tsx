import React from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import { ErrorBoundary } from './components/ErrorBoundary'
import './styles.css'

// Tracing is opt-in at RUNTIME, like the API base URL: the dynamic import
// means the OpenTelemetry code is a separate chunk that is never fetched
// unless /config.js names an exporter. A tracing failure must never stop the
// app from rendering, so it is logged and ignored.
const runtimeConfig = window.__CIVICPULSE_CONFIG__
if (runtimeConfig?.otelExporterUrl) {
  const exporterUrl = runtimeConfig.otelExporterUrl
  import('./tracing')
    .then(({ startTracing }) => startTracing({ exporterUrl, apiBaseUrl: runtimeConfig.apiBaseUrl }))
    .catch((error: unknown) => console.warn('tracing disabled:', error))
}

const container = document.getElementById('root')
if (!container) throw new Error('#root is missing from index.html')

createRoot(container).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
)
