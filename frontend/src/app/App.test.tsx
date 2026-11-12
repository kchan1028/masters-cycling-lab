import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import App from './App'

test('reports a reachable API', async () => {
  const fetchMock = vi.fn().mockResolvedValue(Response.json({ status: 'ok' }))
  vi.stubGlobal('fetch', fetchMock)

  render(<App />)

  expect(await screen.findByText('API is reachable.')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/health/live', undefined)
})

test('says so when the API is down', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

  render(<App />)

  expect(await screen.findByRole('status')).toHaveTextContent('API is not reachable')
})
