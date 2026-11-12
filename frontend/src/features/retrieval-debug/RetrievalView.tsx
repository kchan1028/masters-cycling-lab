import { useEffect, useState, type FormEvent } from 'react'
import { api, errorMessage, type AnswerDebug, type SearchRequest, type SearchResponse } from '../../api/client'

function answerIdFromHash(): string {
  return new URLSearchParams(window.location.hash.split('?')[1] ?? '').get('answer') ?? ''
}

function score(value: number | null | undefined): string {
  return value == null ? '—' : value.toFixed(3)
}

function timings(values: Record<string, unknown>): string {
  return Object.entries(values)
    .map(([name, ms]) => `${name} ${Number(ms).toFixed(0)} ms`)
    .join(' · ')
}

export default function RetrievalView() {
  return (
    <section aria-labelledby="retrieval-heading">
      <h2 id="retrieval-heading">Retrieval debug</h2>
      <p className="muted">
        See exactly which passages a query finds, before any answer is written. Scores only order the results.
      </p>
      <SearchPanel />
      <AnswerDebugPanel />
    </section>
  )
}

function SearchPanel() {
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState<SearchRequest['mode']>('vector')
  const [candidateK, setCandidateK] = useState('10')
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!query.trim()) return
    setLoading(true)
    try {
      setResult(await api.search({ query: query.trim(), mode, candidate_k: Number(candidateK) }))
      setError(null)
    } catch (caught) {
      setError(errorMessage(caught))
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <form onSubmit={submit} className="stack">
        <label htmlFor="search-query">Query</label>
        <input id="search-query" value={query} maxLength={1000} onChange={(event) => setQuery(event.target.value)} />
        <div className="row">
          <label htmlFor="search-mode">Mode</label>
          <select id="search-mode" value={mode} onChange={(event) => setMode(event.target.value as typeof mode)}>
            <option value="vector">Vector (embeddings)</option>
            <option value="lexical">Lexical (keywords)</option>
          </select>
          <label htmlFor="candidate-k">Results</label>
          <input
            id="candidate-k"
            type="number"
            min={1}
            max={50}
            value={candidateK}
            onChange={(event) => setCandidateK(event.target.value)}
          />
          <button type="submit" disabled={loading || !query.trim()}>
            {loading ? 'Searching…' : 'Search'}
          </button>
        </div>
      </form>
      {error && (
        <p className="notice problem" role="alert">
          {error}
        </p>
      )}
      {result && <SearchResults result={result} />}
    </>
  )
}

function SearchResults({ result }: { result: SearchResponse }) {
  return (
    <div className="stack">
      <p className="muted">
        {result.results.length} results from {result.searched_documents} searchable documents ·{' '}
        {timings(result.timings_ms)}
        {result.embedding_model_id && ` · ${result.embedding_model_id} @ ${result.embedding_model_revision?.slice(0, 7)}`}
      </p>
      <p className="muted">{result.score_note}</p>
      {result.results.length === 0 ? (
        <p>Nothing matched. Check that documents are indexed, or try other words.</p>
      ) : (
        <table>
          <caption className="visually-hidden">Search results</caption>
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Passage</th>
              <th scope="col">Pages</th>
              {result.mode === 'vector' ? (
                <>
                  <th scope="col">Distance</th>
                  <th scope="col">Similarity</th>
                </>
              ) : (
                <th scope="col">Lexical score</th>
              )}
            </tr>
          </thead>
          <tbody>
            {result.results.map((hit) => (
              <tr key={hit.chunk_id}>
                <td>{hit.rank}</td>
                <td>
                  <details>
                    <summary>
                      {hit.document_title ?? 'Untitled document'}
                      {hit.publication_year && ` (${hit.publication_year})`}
                    </summary>
                    <p className="excerpt">{hit.excerpt}</p>
                  </details>
                </td>
                <td>{hit.pages.map((page) => page.page_number).join(', ')}</td>
                {result.mode === 'vector' ? (
                  <>
                    <td>{score(hit.cosine_distance)}</td>
                    <td>{score(hit.similarity)}</td>
                  </>
                ) : (
                  <td>{score(hit.lexical_score)}</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function AnswerDebugPanel() {
  // Prefilled when opened from an answer's "How this answer was built" link.
  const [answerId, setAnswerId] = useState(answerIdFromHash)
  const [requested, setRequested] = useState(answerIdFromHash)
  const [debug, setDebug] = useState<AnswerDebug | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!requested) return
    let cancelled = false
    api
      .answerDebug(requested)
      .then((loaded) => {
        if (cancelled) return
        setDebug(loaded)
        setError(null)
      })
      .catch((caught) => {
        if (cancelled) return
        setDebug(null)
        setError(errorMessage(caught))
      })
    return () => {
      cancelled = true
    }
  }, [requested])

  function submit(event: FormEvent) {
    event.preventDefault()
    setRequested(answerId.trim())
  }

  return (
    <div className="stack">
      <h3>How an answer was built</h3>
      <form onSubmit={submit} className="row">
        <label htmlFor="answer-id">Answer ID</label>
        <input id="answer-id" value={answerId} onChange={(event) => setAnswerId(event.target.value)} />
        <button type="submit" disabled={!answerId.trim()}>
          Show
        </button>
      </form>
      {error && (
        <p className="notice problem" role="alert">
          {error}
        </p>
      )}
      {debug && (
        <>
          <p className="muted">
            Embeddings: {debug.embedding_model_id} @ {debug.embedding_model_revision.slice(0, 7)} · Model:{' '}
            {debug.llm_model ?? 'not called'} · Prompt: {debug.prompt_version ?? '—'} · {timings(debug.timings_ms)}
          </p>
          <table>
            <caption className="visually-hidden">Candidate passages</caption>
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Passage</th>
                <th scope="col">Pages</th>
                <th scope="col">Distance</th>
                <th scope="col">Sent to model</th>
              </tr>
            </thead>
            <tbody>
              {debug.candidates.map((candidate) => (
                <tr key={candidate.rank}>
                  <td>{candidate.rank}</td>
                  <td>
                    <details>
                      <summary>{candidate.document_title ?? 'Untitled document'}</summary>
                      <p className="excerpt">{candidate.excerpt}</p>
                    </details>
                  </td>
                  <td>{candidate.page_numbers.join(', ')}</td>
                  <td>{score(candidate.cosine_distance)}</td>
                  <td>
                    {candidate.selected ? `Yes, as ${candidate.evidence_id}` : 'No'}
                    {candidate.reason && <div className="muted">{candidate.reason}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}
