import { useState, type FormEvent } from 'react'
import { api, ApiError, errorMessage, fileUrl, type Answer, type Citation } from '../../api/client'

type State =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'answer'; answer: Answer }
  | { kind: 'failure'; message: string; serviceProblem: boolean }

export default function ResearchView() {
  const [question, setQuestion] = useState('')
  const [yearFrom, setYearFrom] = useState('')
  const [state, setState] = useState<State>({ kind: 'idle' })
  const [selected, setSelected] = useState<Citation | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!question.trim() || state.kind === 'loading') return
    setState({ kind: 'loading' })
    setSelected(null)
    try {
      const filters = yearFrom ? { publication_year_from: Number(yearFrom) } : {}
      const answer = await api.ask({ question: question.trim(), filters, include_debug: false })
      setState({ kind: 'answer', answer })
      setSelected(answer.claims[0]?.citations[0] ?? null)
    } catch (error) {
      const serviceProblem = error instanceof ApiError && error.status >= 500
      setState({ kind: 'failure', message: errorMessage(error), serviceProblem })
    }
  }

  return (
    <section aria-labelledby="research-heading">
      <h2 id="research-heading">Ask the research</h2>
      <form onSubmit={submit} className="stack">
        <label htmlFor="question">Question</label>
        <textarea
          id="question"
          rows={3}
          maxLength={1000}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="What does the research say about recovery in masters cyclists?"
        />
        <div className="row">
          <label htmlFor="year-from">Published from (optional)</label>
          <input
            id="year-from"
            type="number"
            min={1800}
            max={2100}
            value={yearFrom}
            onChange={(event) => setYearFrom(event.target.value)}
          />
          <button type="submit" disabled={state.kind === 'loading' || !question.trim()}>
            {state.kind === 'loading' ? 'Answering…' : 'Ask'}
          </button>
        </div>
      </form>

      <div aria-live="polite">
        {state.kind === 'loading' && <p>Searching the papers and writing an answer…</p>}
        {state.kind === 'failure' && (
          <div className="notice problem" role="alert">
            <strong>{state.serviceProblem ? 'The system could not answer.' : 'The request was not accepted.'}</strong>
            <p>{state.message}</p>
            {state.serviceProblem && <p>This is a service problem, not a finding that the research has no answer.</p>}
          </div>
        )}
      </div>

      {state.kind === 'answer' && <AnswerPanel answer={state.answer} selected={selected} onSelect={setSelected} />}
    </section>
  )
}

function AnswerPanel(props: { answer: Answer; selected: Citation | null; onSelect: (c: Citation) => void }) {
  const { answer, selected, onSelect } = props
  if (answer.status !== 'answered') {
    return (
      <div className="notice" role="status">
        <strong>Not enough evidence.</strong>
        <p>{answer.answer_text}</p>
        <p>
          <a href={`#/retrieval?answer=${answer.query_run_id}`}>Inspect what the search found</a>
        </p>
      </div>
    )
  }
  return (
    <div className="answer-layout">
      <article aria-label="Answer">
        <h3>Answer</h3>
        <ol className="claims">
          {answer.claims.map((claim, index) => (
            <li key={index}>
              {claim.text}{' '}
              {claim.citations.map((citation) => (
                <button
                  key={citation.evidence_id}
                  type="button"
                  className="cite"
                  aria-pressed={selected?.evidence_id === citation.evidence_id}
                  aria-label={`Show evidence ${citation.evidence_id}`}
                  onClick={() => onSelect(citation)}
                >
                  {citation.evidence_id}
                </button>
              ))}
            </li>
          ))}
        </ol>
        {answer.limitations.length > 0 && (
          <>
            <h3>Limitations</h3>
            <ul>
              {answer.limitations.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </>
        )}
        <p className="muted">{answer.note}</p>
        <p>
          <a href={`#/retrieval?answer=${answer.query_run_id}`}>How this answer was built</a>
        </p>
      </article>
      <aside aria-label="Evidence" className="evidence">
        {selected ? <EvidenceCard citation={selected} /> : <p>Select a citation to see its passage.</p>}
      </aside>
    </div>
  )
}

function EvidenceCard({ citation }: { citation: Citation }) {
  const page = citation.page_numbers[0]
  const byline = [citation.authors.slice(0, 3).join(', '), citation.publication_year, citation.doi && `doi:${citation.doi}`]
  return (
    <div>
      <h3>
        {citation.evidence_id}: {citation.document_title ?? 'Untitled document'}
      </h3>
      <p className="muted">
        {byline.filter(Boolean).join(' · ')}
        {citation.metadata_source === 'extracted_unverified' && ' · metadata not verified'}
      </p>
      <p>
        Page {citation.page_numbers.join(', ')}
        {citation.page_labels.some(Boolean) && ` (printed ${citation.page_labels.filter(Boolean).join(', ')})`}
      </p>
      <blockquote className="excerpt">{citation.excerpt}</blockquote>
      {citation.file_url ? (
        <a href={fileUrl(citation.document_id, page)} target="_blank" rel="noopener noreferrer">
          Open the PDF at page {page}
        </a>
      ) : (
        <p className="muted">This document has been deleted.</p>
      )}
    </div>
  )
}
