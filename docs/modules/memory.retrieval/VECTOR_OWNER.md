# Generation-bound vector owner contract

Status: source implementation and tests only. This document does not claim that a text encoder, durable vector service, product caller, calibrated embedding model, deployment, activation or release exists.

## Purpose

`codex-hepta-memory-retrieval::GenerationBoundVectorOwnerV1` is the deterministic immutable index owner for one already encoded generation. It prevents lexical/RRF scores, generic graph evidence or an unrelated learned ranker from being relabelled as vector evidence. The owner emits exactly one `EncoderVector` generator batch that can join the existing generated-candidate union only after a trusted product composition supplies it.

The owner deliberately does **not** tokenize or encode text. A separately qualified encoder must produce `VectorEmbeddingV1` values. Each embedding binds:

- the exact query digest or record content digest represented by the vector;
- the complete Lane C generation-vector digest;
- model digest;
- encoder/preprocessor digest;
- bounded Q32 components;
- a canonical embedding digest.

An index record is valid only when its embedding subject equals the record content digest and its generation/model/encoder identities match the immutable index snapshot. A query is valid only when its embedding subject equals the request digest and the same identities match. These checks make copied vectors from another text, model, preprocessor or generation fail closed.

## Bounds and scoring

The source contract accepts at most 4096 dimensions and 16384 unique live indexed revisions. Product recall remains bounded by `MAX_GENERATION_BOUND_CANDIDATES` (512). Components are in `[-1, 1]` Q32. Ranking uses deterministic average L1 similarity mapped monotonically into `[0, 1]`; ties use record identity/revision. The support digest binds the index, query embedding, record, record embedding, score and calibrated OOD value.

The owner filters by the query's approved maximum OOD before the candidate capacity. It reports `LimitReached` only when an admitted vector result was truncated by capacity; otherwise it reports `Exhausted` relative to the immutable supplied index snapshot. That is not proof that an external durable service indexed every authorized record.

## Product composition requirements

Before enabling `RetrievalChannelV1::Vector`, product composition must additionally prove:

1. a real text encoder executes under the model/tokenizer/encoder identities in the Lane C vector;
2. every indexed revision is generated from the exact current content digest and scope;
3. index publication, rotation, rollback, deletion and recovery are durable and independently current;
4. the query vector is produced from the exact request digest and same generation;
5. OOD and score calibration pass approved holdouts;
6. Agentd appends the returned `EncoderVector` batch before generation-bound union construction and revalidates selected records at final use;
7. exact-head tests, contention measurements and independent acceptance are green.

Until those gates exist, the SQLite seven-channel product adapter remains unchanged and the Vector policy channel must remain disabled. The source owner is a fail-closed contract and testable index core, not a synthetic encoder or product-composition receipt.
