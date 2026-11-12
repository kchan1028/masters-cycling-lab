import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, errorMessage, fileUrl, type Document, type Page } from '../../api/client'

const POLL_MS = 3000

function isActive(document: Document): boolean {
  return ['queued', 'running'].includes(document.latest_job?.status ?? '')
}

function statusText(document: Document): string {
  const job = document.latest_job
  if (job && isActive(document)) {
    const progress = job.progress_total ? ` ${job.progress_done}/${job.progress_total}` : ''
    return job.status === 'queued' ? 'Queued' : `Indexing (${job.stage ?? 'starting'}${progress})`
  }
  if (job?.status === 'failed') return `Failed: ${job.error_code}`
  return document.searchable ? 'Searchable' : 'Not indexed'
}

export default function DocumentsView() {
  const [documents, setDocuments] = useState<Document[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState('')

  const load = useCallback(
    () =>
      api.documents().then(
        (list) => {
          setDocuments(list.items)
          setError(null)
        },
        (caught) => setError(errorMessage(caught)),
      ),
    [],
  )

  useEffect(() => {
    void load()
  }, [load])

  // Poll only while something is queued or indexing, and stop as soon as nothing is.
  const inProgress = documents?.some(isActive) ?? false
  useEffect(() => {
    if (!inProgress) return
    const timer = window.setInterval(() => void load(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [inProgress, load])

  /** Runs one action at a time and reports the outcome. Resolves to false when it failed. */
  async function run(key: string, action: () => Promise<string>): Promise<boolean> {
    setBusy(key)
    try {
      setMessage(await action())
      await load()
      return true
    } catch (caught) {
      setMessage(errorMessage(caught))
      return false
    } finally {
      setBusy(null)
    }
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const input = event.currentTarget.elements.namedItem('pdf') as HTMLInputElement
    const file = input.files?.[0]
    if (!file) return
    await run('upload', async () => {
      const result = await api.upload(file)
      return result.duplicate ? 'This file is already in the corpus.' : `${file.name} uploaded and queued.`
    })
    input.value = ''
  }

  function remove(document: Document) {
    const name = document.title ?? document.original_filename
    if (window.confirm(`Delete "${name}", its index and any answers that quoted it? This cannot be undone.`)) {
      void run(document.id, async () => {
        await api.deleteDocument(document.id)
        return 'Document deleted.'
      })
    }
  }

  return (
    <section aria-labelledby="documents-heading">
      <h2 id="documents-heading">Documents</h2>
      <form onSubmit={upload} className="row">
        <label htmlFor="pdf">Upload a PDF</label>
        <input id="pdf" name="pdf" type="file" accept="application/pdf,.pdf" />
        <button type="submit" disabled={busy !== null}>
          {busy === 'upload' ? 'Uploading…' : 'Upload'}
        </button>
      </form>
      <p role="status" aria-live="polite">
        {message}
      </p>
      {error && (
        <p className="notice problem" role="alert">
          {error}
        </p>
      )}
      {documents === null && !error && <p>Loading documents…</p>}
      {documents?.length === 0 && <p>No documents yet. Upload a research PDF to start.</p>}
      {documents && documents.length > 0 && (
        <table>
          <caption className="visually-hidden">Documents in the corpus</caption>
          <thead>
            <tr>
              <th scope="col">Document</th>
              <th scope="col">Year</th>
              <th scope="col">Pages</th>
              <th scope="col">Status</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((document) => (
              <DocumentRow
                key={document.id}
                document={document}
                disabled={busy !== null}
                onReindex={() =>
                  void run(document.id, async () => {
                    await api.reindex(document.id)
                    return 'Rebuild queued. The current index stays searchable until it is ready.'
                  })
                }
                onDelete={() => remove(document)}
                onSave={(patch) =>
                  run(document.id, async () => {
                    await api.updateDocument(document.id, patch)
                    return 'Metadata saved.'
                  })
                }
              />
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

type RowProps = {
  document: Document
  disabled: boolean
  onReindex: () => void
  onDelete: () => void
  onSave: (patch: { title?: string; publication_year?: number | null }) => Promise<boolean>
}

function DocumentRow({ document, disabled, onReindex, onDelete, onSave }: RowProps) {
  const [editing, setEditing] = useState(false)
  const [showPages, setShowPages] = useState(false)

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const year = String(form.get('year') ?? '')
    const saved = await onSave({
      title: String(form.get('title') ?? '').trim(),
      publication_year: year ? Number(year) : null,
    })
    if (saved) setEditing(false)
  }

  return (
    <>
      <tr>
        <td>
          <a href={fileUrl(document.id)} target="_blank" rel="noopener noreferrer">
            {document.title ?? document.original_filename}
          </a>
          {document.metadata_source === 'extracted_unverified' && <span className="muted"> (title not verified)</span>}
        </td>
        <td>{document.publication_year ?? '—'}</td>
        <td>{document.page_count ?? '—'}</td>
        <td>
          {statusText(document)}
          {document.latest_job?.status === 'failed' && <div className="muted">{document.latest_job.error_message}</div>}
        </td>
        <td className="actions">
          <button type="button" onClick={() => setEditing(!editing)} aria-expanded={editing}>
            Edit
          </button>
          <button
            type="button"
            onClick={() => setShowPages(!showPages)}
            aria-expanded={showPages}
            disabled={!document.searchable}
          >
            Pages
          </button>
          <button type="button" onClick={onReindex} disabled={disabled || isActive(document)}>
            Reindex
          </button>
          <button type="button" onClick={onDelete} disabled={disabled}>
            Delete
          </button>
        </td>
      </tr>
      {editing && (
        <tr>
          <td colSpan={5}>
            <form onSubmit={save} className="row">
              <label>
                Title <input name="title" defaultValue={document.title ?? ''} required maxLength={500} />
              </label>
              <label>
                Year{' '}
                <input name="year" type="number" min={1800} max={2100} defaultValue={document.publication_year ?? ''} />
              </label>
              <button type="submit" disabled={disabled}>
                Save
              </button>
            </form>
          </td>
        </tr>
      )}
      {showPages && (
        <tr>
          <td colSpan={5}>
            <PageViewer document={document} />
          </td>
        </tr>
      )}
    </>
  )
}

function PageViewer({ document }: { document: Document }) {
  const [number, setNumber] = useState(1)
  const [page, setPage] = useState<Page | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .page(document.id, number)
      .then((loaded) => {
        if (cancelled) return
        setPage(loaded)
        setError(null)
      })
      .catch((caught) => {
        if (cancelled) return
        setPage(null)
        setError(errorMessage(caught))
      })
    return () => {
      cancelled = true
    }
  }, [document.id, number])

  return (
    <div className="stack">
      <label>
        Page{' '}
        <input
          type="number"
          min={1}
          max={document.page_count ?? 1}
          value={number}
          onChange={(event) => setNumber(Number(event.target.value) || 1)}
        />{' '}
        of {document.page_count}
      </label>
      {error && <p className="notice problem">{error}</p>}
      {!page && !error && <p>Loading page…</p>}
      {page && (
        <>
          {page.warnings.length > 0 && (
            <ul className="warnings" aria-label="Extraction warnings">
              {page.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
          <pre className="page-text">{page.text || '(no text on this page)'}</pre>
        </>
      )}
    </div>
  )
}
