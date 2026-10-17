# Associative frozen-vector shadow gate (research only)

This gate extends the experimental associative MemoryCell in PR #2365 without
modifying the production selected model, runtime owner, registries or normal CI.

## Input contract

The experiment accepts strict UTF-8 JSONL records with exactly:

`split, identity, scope, family, root, kind, encoder_identity,
observed_at, cue, value`

- Splits: `train` and `future`; both must be nonempty.
- Kinds: `semantic`, `procedural`; both required for vector comparison.
- `cue` and `value` are caller-provided, finite, bounded, equal-dimensional
  **frozen vectors**, **not raw source text**.
- Train examples must not exceed the declared `train_through` clock.
- Future examples must occur strictly after `future_after` and
  `train_through < future_after`.
- Source roots and correlated families must be disjoint across train/future.
- Exact identical (kind, cue, value) copies across the cuts are rejected.
- The caller provides an explicit training admission digest. This is
  **self-attested**: the code cannot authenticate provenance or permissions.

## What is compared

`compare()` trains a candidate from the existing `AssociativeCell`, leaving
the starting parent untouched, and evaluates four vector-only arms:
frozen/untrained parameter memory; trained parameter memory; cosine nearest
neighbor over the retained training vectors; and same-kind cosine neighbor.

All outputs are scored against held-out value vectors **after** inference.
The retrieval controls retain their source vectors; the parametric inference
path does not receive training rows. These are not text RAG systems, not
semantic judges, not natural-language Reader runs and not equal-storage
controls. Full lifecycle costs and provenance remain unmeasured.

This gate does not demonstrate specialization, graph emergence, superiority
over strong RAG, independent future windows, accepted citations or model
promotion. `production_qualified` and `superiority_claim` are false.

## Run

From the repository root, with the pinned PyTorch CPU research environment:

```sh
PYTHONPATH=scripts/memory_cell python3 -m unittest \
  scripts/memory_cell/test_associative_shadow_gate.py -v
```

Actual corpus experiments must supply independently sourced, frozen, admitted
vectors and compare against a tuned, indexed text RAG and real Reader, with
source-family independence and independent semantic evaluation, before claims
of end-to-end memory benefit are possible.
