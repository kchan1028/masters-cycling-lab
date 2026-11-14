# Decision records

Why Masters Cycling Lab is built the way it is. Each record gives the context, the alternatives, the decision,
its consequences, and when to revisit it.

**Labels**

- **Current Design**: the decision is implemented in the code on `main` and the record describes it.
- **Documented Rationale**: the choice was made before it was recorded (for example, fixed by the project spec), and
  the record writes down the reasons the current code supports. It does not claim a comparison that never happened.
- **Proposed**: not implemented yet. None at the moment.

| # | Decision | Label | Date |
|---|---|---|---|
| [0001](0001-stack-and-structure.md) | Stack and code structure: one package, two processes, no RAG framework, OpenAPI as the contract between FastAPI and React | Current Design | 2026-11-12 |
| [0002](0002-embedding-model.md) | Embedding model: `bge-small-en-v1.5` at a pinned revision, 300-token chunks | Current Design | 2026-11-12 |
| [0003](0003-postgres-job-queue-and-index-versions.md) | Ingestion pipeline: PostgreSQL job queue with leases and fencing, versioned indexes switched atomically | Current Design | 2026-11-12 |
| [0004](0004-retrieval-and-citations.md) | Exact vector retrieval, a lexical baseline, and citations resolved on the server | Current Design | 2026-11-12 |
| [0005](0005-pgvector-instead-of-a-vector-database.md) | PostgreSQL with pgvector instead of a dedicated vector database | Documented Rationale | 2026-11-14 |
| [0006](0006-retrieval-evaluation-method.md) | How retrieval changes are evaluated and adopted: dev and held-out splits, targets set before results | Current Design | 2026-11-14 |
| [0007](0007-model-provider-abstraction.md) | One OpenAI-compatible provider interface, optional for everything except answers | Current Design | 2026-11-14 |

Records 0001 to 0004 were written when the decisions were made. Their "Review notes" sections, added on
2026-11-14, list the alternatives, risks and revisit conditions without changing the decisions. Records 0005 to
0007 were written on 2026-11-14 from the code and the evaluation history.

## By topic

- **Storage and search:** [0005](0005-pgvector-instead-of-a-vector-database.md), [0004](0004-retrieval-and-citations.md)
- **Ingestion and retrieval pipeline:** [0002](0002-embedding-model.md), [0003](0003-postgres-job-queue-and-index-versions.md), [0004](0004-retrieval-and-citations.md)
- **Citation grounding and traceability:** [0004](0004-retrieval-and-citations.md)
- **Evaluation:** [0006](0006-retrieval-evaluation-method.md), with the numbers in [evaluation.md](../evaluation.md)
- **FastAPI and React boundary:** [0001](0001-stack-and-structure.md) (OpenAPI is the contract; frontend types are generated)
- **Model providers:** [0007](0007-model-provider-abstraction.md)

## Adding a record

Copy the shape of 0005 to 0007: context, requirements and constraints, alternatives, decision, rationale,
consequences, risks and limits, and when to revisit. Number it next, add it to the table above, and label it
honestly.
