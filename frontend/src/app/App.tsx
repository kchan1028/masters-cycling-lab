import { useEffect, useState } from 'react'
import { api } from '../api/client'

type ApiState = 'checking' | 'reachable' | 'unreachable'

const apiStateText: Record<ApiState, string> = {
  checking: 'Checking the API…',
  reachable: 'API is reachable.',
  unreachable: 'API is not reachable. Start the backend and reload.',
}

export default function App() {
  const [apiState, setApiState] = useState<ApiState>('checking')

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
      <header>
        <h1>Masters Cycling Lab</h1>
        <p className="lede">A research workspace for evidence relevant to masters cyclists.</p>
      </header>
      <main>
        <p role="status" data-state={apiState}>
          {apiStateText[apiState]}
        </p>
        <p>
          Document upload, research questions, retrieval inspection and evaluation views are added in later
          milestones. See <code>docs/roadmap.md</code>.
        </p>
      </main>
    </div>
  )
}
