# MemoryCell — frozen retrieval on separate published LoCoMo conversation families

**Research-only source-recall diagnostic.** This protocol does not execute an LLM,
train a Cell, establish semantic citation entailment, or qualify production.
It advances beyond the 8 repeatedly exposed authored event tasks by preparing
retrieval against the exact published LoCoMo family split, without promoting
its published histories to real future independently authenticated sources.

## Original source and split

The source is the pinned LoCoMo 10-conversation input SHA-256
`79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`
from revision `3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376`.
The existing `external_locomo_pilot.py` cuts the original conversation-family
proxies **6 train / 2 selection / 2 evaluation**, with **48 / 16 / 16**
public questions chosen by a fixed label-blind hash rule. LongMemEval is
quarantined from this LoCoMo-only source pilot, not artificially counted as
additional independent families.

## Strict execution barriers

The source preparation job uses the original native adapter to export exact
text-history byte content, source roots, observation timestamps and source IDs
into a **public reader-only artifact**, validated against each question's
precommitted SHA-256 source census. No original QA target or scoring record is
copied to the reader artifact. Sources are original published conversation
turns and optionally provided captions, not authenticated image observations.

A separate `retrieve` job downloads **only the public artifact** and saves a
full immutable decision journal: 80 questions × 6 fixed source-only arms
(lexical BM25 and recency, each top-2/top-4/top-8) = 480 decisions. All original
source excerpts remain unchanged. BM25 and recency are **simple non-neural
controls**, not a dense hybrid RAG competitor or a reader success claim.
Selected source byte totals are measured; they are not Qwen tokenizer counts.

Only after all 480 selections have been saved and sha256-pinned does a distinct
`select` job receive **selection-family targets only**, to pick an arm by
highest exact published support-source coverage, then lower source bytes. The
held-out evaluation targets are a **different GitHub Actions artifact** and are
not mounted in the selection job. A later `evaluate` job opens only the original
evaluation-family target subset after verifying that the selected policy and
entire raw retrieval journal are frozen. The independent scorer recomputes
all 480 selections without using gold, then reports annotated source-ID
coverage and unknown/unanswerable bounds at the original family-proxy level.
No invalid/unresolved or absent support is silently counted as covered.

This split permits a narrow, held-out **retrieval/source-ID coverage** measure
on two published LoCoMo conversation-family proxies. It does not establish
independent semantic sufficiency, reader factual accuracy, representative
confidence intervals, trusted human provenance, unseen future observations,
>=99% citation entailment, or end-to-end retention/recovery lifecycle costs.
The parent two-corpus admission gate and production acceptance remain closed.

**Run:** `.github/workflows/hepta-memory-locomo-frozen-retrieval.yml` on exact
source changes. Inspect its four jobs `publish -> retrieve -> select -> evaluate`,
original receipts, tested commit and SHA256SUMS; do not use model/parameter claims
from a source-only run.
