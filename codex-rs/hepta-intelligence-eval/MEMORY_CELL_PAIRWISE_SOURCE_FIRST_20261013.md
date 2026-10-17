# MemoryCell source-first review: pinned Pairwise Shadow, 2026-10-13

## What is actually demonstrated

The source commit `26853d272ccab968c76041bd038caf81c7f4a6bf`
produced completed [native six-arm run 38322463886](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38322463886).
Its immutable artifact `11780340178` has external SHA-256
`213db6fdc9d219988cba19d1c5cc81dbb7f2f1505fd917f03b26f6cc2346382e`;
236 internal manifest members were verified. All six original policies attempted
576/576 with 0 policy failures, but no original learned arm improved frozen
source choice or produced a citation marker. This proves execution completeness,
**not** task superiority.

The final-checkpoint `pairwise_linear` and `pairwise_gated` Shadow arms,
trained with a positive-versus-weak-negative margin and matched frozen Encoder,
changed the same **one test** and **one transfer** source choice. On the test
question, weak native document-support scoring showed +1 supported-source
selection and the actual matched Reader token-F1 delta was +0.052973342447.
On transfer the changed Reader answer had diagnostic F1 delta 0. Both changed
Reader requests used the same pinned original Reader and prompt. No emitted
citation marker has independently verified entailment. These are **two
different questions, not four independent improvements**.

The predeclared held-out set is only 16 questions. `test` is not new source
family relative to retained old-task sessions; `transfer` has one native
source family. Neither an isolated +1 weak-source gain nor a higher token-F1 on
one public development question establishes unseen-family generalization.

## New source-first handoff

`scripts/memory_cell/stem_pairwise_source_first.py` is a read-only exporter.
It requires the exact pinned original ZIP and verifies its SHA-256, entire
internal SHA256SUMS, generating source and Git tree, all 576 original policy
attempts, 192 pre-answer label-blind Shadow decisions, and 32 frozen-matched
Reader controls. It checks canonical Reader identity, prompt, observed
question, source pool, source UTF-8 byte offsets and time eligibility.

The exporter will **reject** missing cases, changed Reader questions, source
tampering and disagreement between the two Shadow arms rather than silently
discarding a question or claiming independent repetitions. The two arms are
identical for each of the 16 registered cases, so each question enters once.

The stage-1 reviewer artifact contains exactly 16 cases: original question,
as-of time, passage A and passage B. It contains **no model answer,
arm identity, post-hoc native gold support label, or F1 score**. Unchanged
question/source pairs are kept to prevent selecting just the apparently
improved cases. A separate owner-side manifest retains the case-to-policy
mapping and answer hashes, but no signed human decisions are invented.

Because deterministic hashed A/B ordering is **not cryptographic blinding**,
the owner must manage reviewer access and independence externally. GitHub
Actions artifacts are not an access-controlled human-review service.
The reviewer must treat source text as untrusted data, assess passage
sufficiency and temporal admissibility first, and seal judgements **before**
seeing source-label mappings or Reader answers. Any later answer/citation review
must use independently authorized reviewers and must remain distinct from
source-first sufficiency. This new task is neither a seventh production Head
nor a production rollout.

## CI and acceptance

`.github/workflows/hepta-memory-stem-source-first.yml` runs 8 synthetic
tamper/census checks, downloads the completed immutable artifact using the
read-only Actions token, repeats SHA verification and source-only export, and
uploads **two separately named** artifacts:

- `memory-stem-source-first-reviewer`: question/passage pairs only.
- `memory-stem-source-first-owner`: source, checksums, logs and sealed mapping.

The stage-1 packet's 16 entries and two unique changed questions are
**candidate review work**, not independently judged source sufficiency.
Until an authenticated independent review exists, set
`signed_source_sufficiency_verdicts=0`,
`citation_precision=null`, `production_accepted=false`.
Do not promote the resulting paper-thin diagnostic gain, choose a new model
using exposed test results, or merge production controls on its basis.
