import { vi } from 'vitest'
import type { Answer, Citation, Document } from '../api/client'

type Route = { method?: string; path: string; status?: number; body?: unknown }

/** Stubs fetch with fixed JSON responses, matched by method and path. Unmatched requests fail the call. */
export function stubApi(routes: Route[]) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const route = routes.find((r) => (r.method ?? 'GET') === method && `/api/v1${r.path}` === url)
    if (!route) throw new Error(`Unexpected request: ${method} ${url}`)
    if (route.status === 204) return new Response(null, { status: 204 })
    return Response.json(route.body ?? {}, { status: route.status ?? 200 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** The JSON body sent with one of the stubbed requests. */
export function sentJson(fetchMock: ReturnType<typeof stubApi>, call = 0): unknown {
  return JSON.parse(String(fetchMock.mock.calls[call]?.[1]?.body))
}

export function errorBody(code: string, message: string) {
  return { error: { code, message, request_id: 'req-1', details: null } }
}

export function makeDocument(overrides: Partial<Document> = {}): Document {
  return {
    id: 'doc-1',
    original_filename: 'recovery.pdf',
    title: 'Recovery in masters cyclists',
    authors: ['A. Rider'],
    publication_year: 2021,
    doi: null,
    source_url: null,
    license: null,
    access_status: 'open_access',
    metadata_source: 'user_supplied',
    byte_size: 1000,
    sha256: 'a'.repeat(64),
    page_count: 12,
    searchable: true,
    active_index_version_id: 'iv-1',
    latest_job: null,
    created_at: '2026-11-01T10:00:00Z',
    updated_at: '2026-11-01T10:00:00Z',
    ...overrides,
  }
}

export function makeCitation(overrides: Partial<Citation> = {}): Citation {
  return {
    evidence_id: 'E1',
    document_id: 'doc-1',
    document_title: 'Recovery in masters cyclists',
    authors: ['A. Rider'],
    publication_year: 2021,
    doi: null,
    metadata_source: 'user_supplied',
    page_numbers: [3],
    page_labels: ['117'],
    excerpt: 'Older cyclists recovered more slowly after intervals.',
    chunk_id: 'chunk-1',
    index_version_id: 'iv-1',
    file_url: '/api/v1/documents/doc-1/file',
    ...overrides,
  }
}

export function makeAnswer(overrides: Partial<Answer> = {}): Answer {
  return {
    query_run_id: 'run-1',
    question: 'How do older cyclists recover?',
    status: 'answered',
    answer_text: null,
    claims: [],
    limitations: [],
    error_code: null,
    embedding_model_id: 'BAAI/bge-small-en-v1.5',
    llm_model: 'test-model',
    prompt_version: 'answer-v1',
    timings_ms: {},
    created_at: '2026-11-01T10:00:00Z',
    debug: null,
    note: 'Citations show where a claim came from. Check the passage before relying on it.',
    ...overrides,
  }
}
