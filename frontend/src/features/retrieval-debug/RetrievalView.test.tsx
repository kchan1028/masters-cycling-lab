import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test } from 'vitest'
import { sentJson, stubApi } from '../../test/fakeApi'
import RetrievalView from './RetrievalView'

afterEach(() => {
  window.location.hash = ''
})

test('shows ranked passages with distance and similarity', async () => {
  const fetchMock = stubApi([
    {
      method: 'POST',
      path: '/retrieval/search',
      body: {
        query: 'recovery',
        mode: 'vector',
        candidate_k: 10,
        searched_documents: 20,
        embedding_model_id: 'BAAI/bge-small-en-v1.5',
        embedding_model_revision: '5c38ec7c405ec4b44b94cc5a9bb96e735b38267a',
        query_instruction: null,
        timings_ms: { embed: 12.4, search: 3.1 },
        score_note: 'Scores only order the results.',
        results: [
          {
            rank: 1,
            chunk_id: 'chunk-1',
            document_id: 'doc-1',
            index_version_id: 'iv-1',
            document_title: 'Recovery in masters cyclists',
            publication_year: 2021,
            pages: [{ page_number: 3, page_label: '117', start_offset: 0, end_offset: 40 }],
            excerpt: 'Older cyclists recovered more slowly.',
            cosine_distance: 0.1234,
            similarity: 0.8766,
            lexical_score: null,
          },
        ],
      },
    },
  ])
  const user = userEvent.setup()
  render(<RetrievalView />)

  await user.type(screen.getByLabelText('Query'), 'recovery')
  await user.click(screen.getByRole('button', { name: 'Search' }))

  expect(await screen.findByText('0.123')).toBeInTheDocument()
  expect(screen.getByText('0.877')).toBeInTheDocument()
  expect(screen.getByText('Recovery in masters cyclists (2021)')).toBeInTheDocument()
  expect(screen.getByText(/1 results from 20 searchable documents/)).toBeInTheDocument()
  expect(sentJson(fetchMock)).toEqual({
    query: 'recovery',
    mode: 'vector',
    candidate_k: 10,
  })
})

test('hybrid results show the distance and the keyword score', async () => {
  stubApi([
    {
      method: 'POST',
      path: '/retrieval/search',
      body: {
        query: 'recovery',
        mode: 'hybrid',
        candidate_k: 10,
        searched_documents: 20,
        embedding_model_id: 'BAAI/bge-small-en-v1.5',
        embedding_model_revision: '5c38ec7c405ec4b44b94cc5a9bb96e735b38267a',
        query_instruction: null,
        timings_ms: {},
        score_note: 'Scores only order the results.',
        results: [
          {
            rank: 1,
            chunk_id: 'chunk-1',
            document_id: 'doc-1',
            index_version_id: 'iv-1',
            document_title: 'Recovery in masters cyclists',
            publication_year: 2021,
            pages: [{ page_number: 3, page_label: null, start_offset: 0, end_offset: 40 }],
            excerpt: 'Older cyclists recovered more slowly.',
            cosine_distance: 0.1234,
            similarity: 0.8766,
            lexical_score: 0.4,
          },
        ],
      },
    },
  ])
  const user = userEvent.setup()
  render(<RetrievalView />)

  await user.type(screen.getByLabelText('Query'), 'recovery')
  await user.selectOptions(screen.getByLabelText('Mode'), 'hybrid')
  await user.click(screen.getByRole('button', { name: 'Search' }))

  expect(await screen.findByRole('columnheader', { name: 'Lexical score' })).toBeInTheDocument()
  expect(screen.getByRole('columnheader', { name: 'Distance' })).toBeInTheDocument()
  expect(screen.queryByRole('columnheader', { name: 'Similarity' })).not.toBeInTheDocument()
  expect(screen.getByText('0.400')).toBeInTheDocument()
})

test('opens the passages behind an answer from its link', async () => {
  window.location.hash = '#/retrieval?answer=run-1'
  stubApi([
    {
      path: '/answers/run-1/debug',
      body: {
        query_run_id: 'run-1',
        retrieval_config: {},
        generation_config: null,
        embedding_model_id: 'BAAI/bge-small-en-v1.5',
        embedding_model_revision: '5c38ec7c405ec4b44b94cc5a9bb96e735b38267a',
        llm_model: null,
        prompt_version: null,
        timings_ms: {},
        usage: null,
        candidates: [
          {
            rank: 1,
            evidence_id: null,
            selected: false,
            reason: 'closest passage is above the distance limit',
            document_id: 'doc-1',
            document_title: 'Recovery in masters cyclists',
            page_numbers: [3],
            cosine_distance: 0.61,
            similarity: 0.39,
            excerpt: 'Older cyclists recovered more slowly.',
          },
        ],
      },
    },
  ])

  render(<RetrievalView />)

  expect(await screen.findByText('closest passage is above the distance limit')).toBeInTheDocument()
  expect(screen.getByLabelText('Answer ID')).toHaveValue('run-1')
  expect(screen.getByText(/Model: not called/)).toBeInTheDocument()
})
