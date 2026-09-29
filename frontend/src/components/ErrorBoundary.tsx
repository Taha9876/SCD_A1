import { Component, type ErrorInfo, type ReactNode } from 'react'

import { IconAlert } from './Icon'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/**
 * Without this, one render-time exception blanks the whole page and a citizen
 * sees white. With it they see something they can act on.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // The browser console, not a server: this is a rendering bug and we have
    // no error-reporting backend to send it to.
    console.error('Unhandled rendering error', error, info.componentStack)
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="panel error-panel" role="alert">
          <IconAlert />
          <h2>Something went wrong on this page</h2>
          <p>
            Your report was not lost if you had already submitted it. Reload to
            continue; if this keeps happening, the browser console has the detail.
          </p>
          <pre>{this.state.error.message}</pre>
          <button type="button" className="button" onClick={() => window.location.reload()}>
            Reload the page
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
