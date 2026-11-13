import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { stubApi } from '../../test/fakeApi'
import EvaluationsView from './EvaluationsView'

const run = {
  id: 'eval-1',
  split: 'dev',
  status: 'completed',
  dataset_sha256: 'd'.repeat(64),
  corpus_sha256: 'c'.repeat(64),
  code_revision: '3a354b1e',
  config: { modes: ['vector', 'lexical'], candidate_k: 10, embedding_model_id: 'BAAI/bge-small-en-v1.5' },
  metrics: {
    vector: { 'recall@10': 0.82, 'mrr@10': 0.97, 'ndcg@10': 0.88, 'evidence_coverage@10': 0.53 },
    lexical: { 'recall@10': 0.67, 'mrr@10': 0.7, 'ndcg@10': 0.6, 'evidence_coverage@10': 0.4 },
  },
  started_at: '2026-11-10T09:00:00Z',
  finished_at: '2026-11-10T09:01:00Z',
}

test('says when there are no runs yet', async () => {
  stubApi([{ path: '/evaluation-runs', body: { items: [], total: 0, limit: 50, offset: 0 } }])

  render(<EvaluationsView />)

  expect(await screen.findByText(/No test runs yet/)).toBeInTheDocument()
  expect(screen.getByText(/Automatic search scores only/)).toBeInTheDocument()
})

test('compares vector and lexical metrics and opens a run', async () => {
  stubApi([
    { path: '/evaluation-runs', body: { items: [run], total: 1, limit: 50, offset: 0 } },
    {
      path: '/evaluation-runs/eval-1',
      body: {
        ...run,
        results: [
          {
            question_id: 'q001',
            retrieval: {
              question: 'Does recovery slow with age?',
              vector: { hits: [{ rank: 1, corpus_id: 'mcl-003', pages: [4] }] },
              lexical: { hits: [] },
            },
            metrics: { vector: { 'recall@10': 1, 'evidence_coverage@10': 0.5 }, lexical: {} },
          },
        ],
      },
    },
  ])
  const user = userEvent.setup()
  render(<EvaluationsView />)

  const row = (await screen.findByText(/3a354b1/)).closest('tr') as HTMLElement
  expect(within(row).getByText('0.82')).toBeInTheDocument()
  expect(within(row).getByText('/ 0.67', { exact: false })).toBeInTheDocument()

  await user.click(within(row).getByRole('button'))

  expect(await screen.findByText('q001: Does recovery slow with age?')).toBeInTheDocument()
  expect(screen.getByText('1.00 / 0.50')).toBeInTheDocument()
  expect(screen.getByText('not scored')).toBeInTheDocument()
  expect(screen.getByText(/mcl-003 p4/)).toBeInTheDocument()
})

test('shows every mode a run measured, in order', async () => {
  const withHybrid = {
    ...run,
    config: { ...run.config, modes: ['vector', 'lexical', 'hybrid'] },
    metrics: { ...run.metrics, hybrid: { 'recall@10': 0.87 } },
  }
  stubApi([{ path: '/evaluation-runs', body: { items: [withHybrid], total: 1, limit: 50, offset: 0 } }])

  render(<EvaluationsView />)

  const row = (await screen.findByText(/3a354b1/)).closest('tr') as HTMLElement
  expect(within(row).getByText('/ 0.67 / 0.87', { exact: false })).toBeInTheDocument()
  expect(within(row).getByText(/meaning \/ keywords \/ both combined/)).toBeInTheDocument()
})

test('names the scores in plain English and keeps the code as a tooltip', async () => {
  stubApi([{ path: '/evaluation-runs', body: { items: [run], total: 1, limit: 50, offset: 0 } }])

  render(<EvaluationsView />)

  const header = await screen.findByRole('columnheader', { name: 'Expected papers found, top 10' })
  expect(header).toHaveAttribute('title', 'recall@10')
  expect(screen.getByRole('columnheader', { name: 'How high the first right paper ranks, top 10' })).toBeInTheDocument()
  expect(screen.getByRole('columnheader', { name: 'Key passages found, top 10' })).toBeInTheDocument()
})
