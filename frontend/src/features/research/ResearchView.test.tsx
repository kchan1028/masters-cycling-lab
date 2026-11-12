import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import { errorBody, makeAnswer, makeCitation, sentJson, stubApi } from '../../test/fakeApi'
import ResearchView from './ResearchView'

async function ask(question = 'How do older cyclists recover?') {
  const user = userEvent.setup()
  render(<ResearchView />)
  await user.type(screen.getByLabelText('Question'), question)
  await user.click(screen.getByRole('button', { name: 'Ask' }))
  return user
}

test('shows cited claims and the passage behind each citation', async () => {
  const second = makeCitation({
    evidence_id: 'E2',
    document_id: 'doc-2',
    document_title: 'Training load after 50',
    page_numbers: [4],
    page_labels: [null],
    excerpt: 'Weekly load was reduced by a fifth.',
  })
  const fetchMock = stubApi([
    {
      method: 'POST',
      path: '/answers',
      body: makeAnswer({
        claims: [
          { text: 'Recovery took longer in older riders.', citations: [makeCitation()] },
          { text: 'Coaches reduced weekly load.', citations: [second] },
        ],
        limitations: ['Small samples.'],
      }),
    },
  ])

  const user = await ask()

  expect(await screen.findByText('Recovery took longer in older riders.')).toBeInTheDocument()
  const evidence = screen.getByRole('complementary', { name: 'Evidence' })
  expect(within(evidence).getByText(/Older cyclists recovered more slowly/)).toBeInTheDocument()
  expect(within(evidence).getByText('Page 3 (printed 117)')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: 'Show evidence E2' }))

  expect(within(evidence).getByText('Weekly load was reduced by a fifth.')).toBeInTheDocument()
  expect(within(evidence).getByRole('link', { name: 'Open the PDF at page 4' })).toHaveAttribute(
    'href',
    '/api/v1/documents/doc-2/file#page=4',
  )
  expect(screen.getByText('Small samples.')).toBeInTheDocument()
  expect(sentJson(fetchMock)).toEqual({ question: 'How do older cyclists recover?', filters: {}, include_debug: false })
})

test('says when there is not enough evidence', async () => {
  stubApi([
    {
      method: 'POST',
      path: '/answers',
      body: makeAnswer({
        status: 'insufficient_evidence',
        answer_text: 'The indexed papers do not contain enough evidence to answer this question.',
        llm_model: null,
      }),
    },
  ])

  await ask()

  expect(await screen.findByText('Not enough evidence.')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Inspect what the search found' })).toHaveAttribute(
    'href',
    '#/retrieval?answer=run-1',
  )
})

test('treats a provider outage as a system failure, not as missing evidence', async () => {
  stubApi([
    {
      method: 'POST',
      path: '/answers',
      status: 503,
      body: errorBody('LLM_NOT_CONFIGURED', 'Answer generation is not configured.'),
    },
  ])

  await ask()

  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('The system could not answer.')
  expect(alert).toHaveTextContent('Answer generation is not configured. (LLM_NOT_CONFIGURED)')
  expect(alert).toHaveTextContent('not a finding that the research has no answer')
  expect(screen.queryByText('Not enough evidence.')).not.toBeInTheDocument()
})
