import type { components } from './generated/schema'

type Schemas = components['schemas']
export type ErrorBody = Schemas['ErrorBody']
export type LiveStatus = Schemas['LiveStatus']
export type Document = Schemas['DocumentOut']
export type DocumentList = Schemas['DocumentList']
export type UploadResult = Schemas['UploadOut']
export type MetadataPatch = Schemas['MetadataPatch']
export type Job = Schemas['JobOut']
export type Page = Schemas['PageOut']
export type SearchRequest = Schemas['SearchRequest']
export type SearchResponse = Schemas['SearchResponse']
export type AnswerRequest = Schemas['AnswerRequest']
export type Answer = Schemas['AnswerOut']
export type Citation = Schemas['CitationOut']
export type AnswerDebug = Schemas['AnswerDebugOut']
export type EvaluationRun = Schemas['EvaluationRunOut']
export type EvaluationRunDetail = Schemas['EvaluationRunDetail']
export type EvaluationRunList = Schemas['EvaluationRunList']

/** A non-2xx response. `body` is the server's error envelope when it sent one. */
export class ApiError extends Error {
  status: number
  body: ErrorBody | null

  constructor(status: number, body: ErrorBody | null) {
    super(body?.message ?? `Request failed with status ${status}`)
    this.status = status
    this.body = body
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, init)
  if (!response.ok) {
    throw new ApiError(response.status, await readErrorBody(response))
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

async function readErrorBody(response: Response): Promise<ErrorBody | null> {
  try {
    const data = (await response.json()) as Partial<Schemas['ErrorResponse']>
    return data.error ?? null
  } catch {
    return null
  }
}

function sendJson<T>(method: string, path: string, body: unknown): Promise<T> {
  return request<T>(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
}

export const api = {
  live: () => request<LiveStatus>('/health/live'),
  documents: () => request<DocumentList>('/documents?limit=100'),
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request<UploadResult>('/documents', { method: 'POST', body: form })
  },
  updateDocument: (id: string, patch: Partial<MetadataPatch>) => sendJson<Document>('PATCH', `/documents/${id}`, patch),
  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: 'DELETE' }),
  reindex: (id: string) => request<Job>(`/documents/${id}/ingestions`, { method: 'POST' }),
  page: (id: string, pageNumber: number) => request<Page>(`/documents/${id}/pages/${pageNumber}`),
  search: (body: SearchRequest) => sendJson<SearchResponse>('POST', '/retrieval/search', body),
  ask: (body: AnswerRequest) => sendJson<Answer>('POST', '/answers', body),
  answerDebug: (id: string) => request<AnswerDebug>(`/answers/${id}/debug`),
  evaluationRuns: () => request<EvaluationRunList>('/evaluation-runs'),
  evaluationRun: (id: string) => request<EvaluationRunDetail>(`/evaluation-runs/${id}`),
}

/** The original PDF, opened at a physical page (1-based) by the browser's PDF viewer. */
export function fileUrl(documentId: string, page?: number): string {
  return `/api/v1/documents/${documentId}/file${page ? `#page=${page}` : ''}`
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.body ? `${error.body.message} (${error.body.code})` : error.message
  }
  return 'Could not reach the API. Is it running?'
}
