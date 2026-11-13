import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import type { Job } from '../../api/client'
import { errorBody, makeDocument, stubApi } from '../../test/fakeApi'
import DocumentsView from './DocumentsView'

function makeJob(overrides: Partial<Job>): Job {
  return {
    id: 'job-1',
    document_id: 'doc-1',
    status: 'succeeded',
    stage: null,
    progress_done: 0,
    progress_total: null,
    attempt_count: 1,
    max_attempts: 3,
    error_code: null,
    error_message: null,
    index_version_id: null,
    created_at: '2026-11-01T10:00:00Z',
    started_at: null,
    finished_at: null,
    ...overrides,
  }
}

function list(items: ReturnType<typeof makeDocument>[]) {
  return { path: '/documents?limit=100', body: { items, total: items.length, limit: 100, offset: 0 } }
}

test('lists documents with their indexing status', async () => {
  stubApi([
    list([
      makeDocument(),
      makeDocument({
        id: 'doc-2',
        title: null,
        original_filename: 'scan.pdf',
        searchable: false,
        latest_job: makeJob({ status: 'failed', error_code: 'OCR_REQUIRED', error_message: 'No text layer.' }),
      }),
      makeDocument({
        id: 'doc-3',
        title: 'Sleep and age',
        searchable: false,
        latest_job: makeJob({ status: 'running', stage: 'embedding', progress_done: 2, progress_total: 5 }),
      }),
    ]),
  ])

  render(<DocumentsView />)

  expect(await screen.findByRole('link', { name: 'Recovery in masters cyclists' })).toHaveAttribute(
    'href',
    '/api/v1/documents/doc-1/file',
  )
  expect(screen.getByText('Ready to search')).toBeInTheDocument()
  expect(screen.getByText('Failed: OCR_REQUIRED')).toBeInTheDocument()
  expect(screen.getByText('No text layer.')).toBeInTheDocument()
  expect(screen.getByText('Processing (building search index 2/5)')).toBeInTheDocument()
})

test('shows an empty state', async () => {
  stubApi([list([])])

  render(<DocumentsView />)

  expect(await screen.findByText(/No papers yet/)).toBeInTheDocument()
})

test('uploads a PDF and refreshes the list', async () => {
  const fetchMock = stubApi([
    list([]),
    { method: 'POST', path: '/documents', status: 201, body: { document: makeDocument(), duplicate: false } },
  ])
  const user = userEvent.setup()
  render(<DocumentsView />)
  await screen.findByText(/No papers yet/)

  await user.upload(screen.getByLabelText('Upload a research paper (PDF)'), new File(['%PDF-1.7'], 'recovery.pdf'))
  await user.click(screen.getByRole('button', { name: 'Upload' }))

  expect(await screen.findByText('recovery.pdf uploaded. Getting it ready to search.')).toBeInTheDocument()
  const [url, init] = fetchMock.mock.calls[1] ?? []
  expect(url).toBe('/api/v1/documents')
  expect((init?.body as FormData).get('file')).toBeInstanceOf(File)
  expect(fetchMock).toHaveBeenCalledTimes(3)
})

test('deletes only after confirmation', async () => {
  const fetchMock = stubApi([list([makeDocument()]), { method: 'DELETE', path: '/documents/doc-1', status: 204 }])
  const confirm = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true)
  vi.stubGlobal('confirm', confirm)
  const user = userEvent.setup()
  render(<DocumentsView />)

  await user.click(await screen.findByRole('button', { name: 'Delete' }))
  expect(fetchMock).toHaveBeenCalledTimes(1)

  await user.click(screen.getByRole('button', { name: 'Delete' }))
  expect(await screen.findByText('Paper deleted.')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/documents/doc-1', { method: 'DELETE' })
})

test('keeps the edit form open when saving fails', async () => {
  stubApi([
    list([makeDocument()]),
    { method: 'PATCH', path: '/documents/doc-1', status: 422, body: errorBody('VALIDATION_ERROR', 'Year is out of range.') },
  ])
  const user = userEvent.setup()
  render(<DocumentsView />)

  await user.click(await screen.findByRole('button', { name: 'Edit' }))
  await user.click(screen.getByRole('button', { name: 'Save' }))

  expect(await screen.findByText('Year is out of range. (VALIDATION_ERROR)')).toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: 'Title' })).toHaveValue('Recovery in masters cyclists')
})
