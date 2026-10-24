# One-hop Reader paired cardinality audit (immutable outcomes)

Research-only continuation of draft PR #1546. This is a **post-seal** evaluation
and source-integrity check, not a new Reader, benchmark, training run, learned
System2/NDU head or deployment.

## Motivation and registered contrasts

The previously completed 80-answer one-hop frozen Reader test showed a
specific output degradation: with exactly one relevant fact 18/20 outputs
mention the target literal but none meets full cited-answer requirements;
with one relevant fact plus two unrelated token facts 20/20 outputs merely
list `E1 E2 E3`, and the no-evidence arm returns `E1` in all 20 cases
instead of the prescribed refusal. These are actual model outputs in
[run 38254837899](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38254837899),
not proof of causal source-cardinality effects on other tasks.

The registered follow-up uses the **same 20 synthetic questions** and frozen
Reader to execute seven new arms (140 planned, not yet completed when this
increment was authored). It changes (1) relevant fact position with identical
documents, (2) type of distractor at identical cardinality, and (3) irrelevant
source count with no relevant fact. Five paired contrasts are fixed:
- same two original facts, relevant one first versus last;
- historical three-source reference (relevant first) versus the exact same
  sources with relevant last;
- two sources: token competitor versus non-token context;
- three sources: two token competitors versus two non-token context facts;
- one versus two irrelevant token facts, with no relevant source.

These are repeated, correlated synthetic questions, NOT independent test tasks.
The contrasts are read-only and executed only after original Reader outputs
have already been sealed. They cannot change the prompt, tokenizer,
generation procedure, sources or model weights.

## Strict provenance before interpreting any apparent gain

`scripts/memory_cell/system2_onehop_cardinality_audit.py`:

1. Reopens the original pinned archive via the pre-existing `load_parent`,
   including the outer SHA256, all inner file hashes, 80 raw answer records,
   generating source/tree, question IDs, model identity and all old scores.
2. Checks the new trial's generating commit, predeclared 140 (20x7) positions,
   64-token decoder/1024-token input bounds, source-plan and original archive
   identity; compares every `starts.jsonl` position to its result.
3. Verifies the SHA256 of the entire new `raw-answers.jsonl` **before**
   evaluating it and disallows duplicated, missing or invented conditions.
4. For every successful attempt, reconstructs exact question and source
   excerpts, evidence bundle digest, delivered source labels, tokenizer
   input/output digests, Reader profile and execution cost. Re-evaluates all
   original scoring columns and separately computes the essential citation,
   exact-target, refusal, label-echo and unsupported-copy verdicts.
5. Verifies every original summary value against raw completed attempts,
   including the immutable old-control rows. A changed original result or
   relabelled failure is an error, not a different outcome.
6. Publishes paired up/down/tied counts and the actual input/output-token
   and elapsed-time aggregates. On failed calls it retains the **planned**
   denominator, reports metric bounds [confirmed, confirmed + unknown], and
   never interprets absent CPU/token work as zero.

Successful numeric target mentions are NOT valid proof/citation; label echoes
are NOT answers; system-composed citations would not be model output. No
independent semantic human reviewer was used.

## Tests, visibility and limitations

Fourteen new hermetic tests passed locally, including source tampering,
score tampering, forged token hashes, missing/duplicate rows, invalid source
order, partial failures and correct unknown bounds. Combined with inherited
research tests, the local source slice ran 53 tests: **52 passed, one
historical-archive integration test skipped**. The downloaded local 297 MB
copy of the historical ZIP did not match the externally pinned 376 MB
artifact, so a full local archive-verification success is explicitly NOT
claimed; the hosted pinned original ZIP remains a mandatory fail-closed
prerequisite. The local tests used a fake Reader for journal mechanics
only and never made new pretrained-model predictions.

The existing CI workflow keeps all inherited MemoryCell regressions and
F/E9 lint, the full 140-call original experiment and its original scoring,
then adds this post-seal read-only check as an `always()` step where sealed
outputs exist. If original model work aborts before sealing, audit is marked
unavailable, not accepted; the model step remains failed. The full evidence
archive and source hashes are retained.

The historical 80 calls are immutable, not 80 additional calls; the seven-arm
study remains 140 planned new calls. No confidence intervals, label-tuned
prompt selection, cross-domain language generalization, operational
CPU/FLOPs equality, Reader adequacy, semantic citation verification,
NDU/FBSDE reasoning emergence or production qualification is claimed.

Reproduce after the exact-head original trial using the same verified
historical archive:

```sh
export HEPTA_MEMORY_TESTED_COMMIT="$(git rev-parse HEAD)"
python scripts/memory_cell/system2_onehop_cardinality_audit.py \
  /tmp/frozen-onehop-original.zip \
  /tmp/onehop-cardinality/trial \
  /tmp/onehop-cardinality/paired-audit
```

`production_accepted=false`, `semantic_human_review=false`,
`independent_reader_generalization=false`.
