import type { components } from './generated/schema'

type Schemas = components['schemas']
export type ErrorBody = Schemas['ErrorBody']
export type LiveStatus = Schemas['LiveStatus']

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

export const api = {
  live: () => request<LiveStatus>('/health/live'),
}
