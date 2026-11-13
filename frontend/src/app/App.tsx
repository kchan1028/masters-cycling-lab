import { useEffect, useState } from 'react'
import { api } from '../api/client'
import DocumentsView from '../features/documents/DocumentsView'
import EvaluationsView from '../features/evaluations/EvaluationsView'
import ResearchView from '../features/research/ResearchView'
import RetrievalView from '../features/retrieval-debug/RetrievalView'

const VIEWS = [
  { path: 'research', label: 'Ask a question' },
  { path: 'documents', label: 'Papers' },
  { path: 'retrieval', label: 'Search details' },
  { path: 'evaluations', label: 'Search scores' },
] as const

type ApiState = 'checking' | 'reachable' | 'unreachable'

const apiStateText: Record<ApiState, string> = {
  checking: 'Connecting to the server…',
  reachable: 'Connected to the server.',
  unreachable: "Can't reach the server. Start the backend and reload.",
}

function currentPath(): string {
  return window.location.hash.replace(/^#\/?/, '').split('?')[0] || 'research'
}

export default function App() {
  const [path, setPath] = useState(currentPath)
  const [apiState, setApiState] = useState<ApiState>('checking')

  useEffect(() => {
    const onHashChange = () => setPath(currentPath())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  useEffect(() => {
    let cancelled = false
    api
      .live()
      .then(() => {
        if (!cancelled) setApiState('reachable')
      })
      .catch(() => {
        if (!cancelled) setApiState('unreachable')
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="page">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <div>
          <h1>Masters Cycling Lab</h1>
          <p className="lede">Research on masters cyclists, answered from papers you can check.</p>
        </div>
        <p role="status" data-state={apiState} className="api-state">
          {apiStateText[apiState]}
        </p>
        <nav aria-label="Main">
          <ul>
            {VIEWS.map((view) => (
              <li key={view.path}>
                <a href={`#/${view.path}`} aria-current={path === view.path ? 'page' : undefined}>
                  {view.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <main id="main" tabIndex={-1}>
        {path === 'documents' && <DocumentsView />}
        {path === 'retrieval' && <RetrievalView />}
        {path === 'evaluations' && <EvaluationsView />}
        {!['documents', 'retrieval', 'evaluations'].includes(path) && <ResearchView />}
      </main>
    </div>
  )
}
