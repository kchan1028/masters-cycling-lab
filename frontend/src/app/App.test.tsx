import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { stubApi } from '../test/fakeApi'
import App from './App'

afterEach(() => {
  window.location.hash = ''
})

test('reports a reachable API', async () => {
  const fetchMock = vi.fn().mockResolvedValue(Response.json({ status: 'ok' }))
  vi.stubGlobal('fetch', fetchMock)

  render(<App />)

  expect(await screen.findByText('Connected to the server.')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/health/live', undefined)
})

test('says so when the API is down', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

  render(<App />)

  expect(await screen.findByRole('status')).toHaveTextContent("Can't reach the server")
})

test('switches views from the main navigation', async () => {
  stubApi([
    { path: '/health/live', body: { status: 'ok' } },
    { path: '/documents?limit=100', body: { items: [], total: 0, limit: 100, offset: 0 } },
  ])
  const user = userEvent.setup()
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Ask the research' })).toBeInTheDocument()

  await user.click(screen.getByRole('link', { name: 'Papers' }))

  expect(await screen.findByRole('heading', { name: 'Papers' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Papers' })).toHaveAttribute('aria-current', 'page')
  expect(screen.queryByRole('heading', { name: 'Ask the research' })).not.toBeInTheDocument()
})
