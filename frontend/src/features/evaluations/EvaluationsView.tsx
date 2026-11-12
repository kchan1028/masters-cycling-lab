import { useEffect, useState } from 'react'
import { api, errorMessage, type EvaluationRun, type EvaluationRunDetail } from '../../api/client'

const HEADLINE = ['recall@10', 'mrr@10', 'ndcg@10', 'evidence_coverage@10']
const ALL_METRICS = [5, 10].flatMap((k) =>
  ['recall', 'mrr', 'ndcg', 'evidence_coverage', 'unjudged'].map((name) => `${name}@${k}`),
)

type Scores = Record<string, number | null | undefined>
type Hit = { corpus_id: string | null; pages: number[] }
type ModeOutput = { hits?: Hit[] }

function modeScores(metrics: Record<string, unknown>, mode: string): Scores {
  return (metrics[mode] ?? {}) as Scores
}

function format(value: number | null | undefined): string {
  return value == null ? '—' : value.toFixed(2)
}

export default function EvaluationsView() {
  const [runs, setRuns] = useState<EvaluationRun[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    api
      .evaluationRuns()
      .then((list) => setRuns(list.items))
      .catch((caught) => setError(errorMessage(caught)))
  }, [])

  return (
    <section aria-labelledby="evaluations-heading">
      <h2 id="evaluations-heading">Evaluations</h2>
      <p className="notice">
        Automated retrieval metrics only. They measure whether the labelled papers and passages were found, not whether
        an answer is right. Check the label status in <code>research/evaluation</code> before relying on them.
      </p>
      {error && (
        <p className="notice problem" role="alert">
          {error}
        </p>
      )}
      {runs === null && !error && <p>Loading runs…</p>}
      {runs?.length === 0 && (
        <p>
          No evaluation runs yet. Run <code>make evaluate</code> once the corpus is ingested.
        </p>
      )}
      {runs && runs.length > 0 && <p className="muted">Each cell shows vector search / the lexical baseline.</p>}
      {runs && runs.length > 0 && (
        <table>
          <caption className="visually-hidden">Evaluation runs, vector then lexical</caption>
          <thead>
            <tr>
              <th scope="col">Run</th>
              {HEADLINE.map((name) => (
                <th scope="col" key={name}>
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id}>
                <td>
                  <button
                    type="button"
                    className="link"
                    aria-pressed={selected === run.id}
                    onClick={() => setSelected(run.id)}
                  >
                    {new Date(run.started_at).toLocaleString()}
                  </button>
                  <div className="muted">
                    {run.split} split · {run.code_revision?.slice(0, 7) ?? 'no revision'}
                  </div>
                </td>
                {HEADLINE.map((name) => (
                  <td key={name}>
                    {format(modeScores(run.metrics, 'vector')[name])}
                    <span className="muted"> / {format(modeScores(run.metrics, 'lexical')[name])}</span>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {selected && <RunDetail key={selected} id={selected} />}
    </section>
  )
}

function RunDetail({ id }: { id: string }) {
  const [run, setRun] = useState<EvaluationRunDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .evaluationRun(id)
      .then(setRun)
      .catch((caught) => setError(errorMessage(caught)))
  }, [id])

  if (error) return <p className="notice problem">{error}</p>
  if (!run) return <p>Loading run…</p>

  const modes = (run.config.modes as string[] | undefined) ?? ['vector']
  const labels = run.config.labels as { reviewed: number; provisional: number } | undefined
  return (
    <article aria-labelledby="run-heading" className="stack">
      <h3 id="run-heading">
        Run on {new Date(run.started_at).toLocaleString()} ({run.split} split)
      </h3>
      <p className="muted">
        {String(run.config.embedding_model_id)} · top {String(run.config.candidate_k)} ·{' '}
        {String(run.config.searchable_corpus_documents)} documents · dataset {run.dataset_sha256.slice(0, 8)} · corpus{' '}
        {run.corpus_sha256.slice(0, 8)}
        {labels && ` · labels: ${labels.reviewed} reviewed by a person, ${labels.provisional} provisional`}
      </p>
      <table>
        <caption className="visually-hidden">Mean scores by retrieval mode</caption>
        <thead>
          <tr>
            <th scope="col">Metric</th>
            {modes.map((mode) => (
              <th scope="col" key={mode}>
                {mode}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {[...ALL_METRICS, 'latency_ms_mean', 'latency_ms_p95'].map((name) => (
            <tr key={name}>
              <th scope="row">{name}</th>
              {modes.map((mode) => (
                <td key={mode}>
                  {name.startsWith('latency')
                    ? `${modeScores(run.metrics, mode)[name]?.toFixed(0) ?? '—'} ms`
                    : format(modeScores(run.metrics, mode)[name])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      <h4>Per question</h4>
      <table>
        <caption className="visually-hidden">Scores and top results for each question</caption>
        <thead>
          <tr>
            <th scope="col">Question</th>
            {modes.map((mode) => (
              <th scope="col" key={mode}>
                {mode} recall@10 / evidence@10
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {run.results.map((result) => (
            <tr key={result.question_id}>
              <td>
                <details>
                  <summary>
                    {result.question_id}: {String(result.retrieval.question)}
                  </summary>
                  {modes.map((mode) => (
                    <p key={mode} className="muted">
                      {mode} top 5:{' '}
                      {((result.retrieval[mode] as ModeOutput | undefined)?.hits ?? [])
                        .slice(0, 5)
                        .map((hit) => `${hit.corpus_id ?? 'other'} p${hit.pages.join(',')}`)
                        .join(' · ')}
                    </p>
                  ))}
                </details>
              </td>
              {modes.map((mode) => {
                const scores = modeScores(result.metrics, mode)
                return (
                  <td key={mode}>
                    {scores['recall@10'] === undefined
                      ? 'not scored'
                      : `${format(scores['recall@10'])} / ${format(scores['evidence_coverage@10'])}`}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </article>
  )
}
