# Equal evidence count under an exact frozen-input token ceiling

Parent: `0dd282d66896c4c5f720db83d4c6ac9946077dbf`, existing research PR #1546.
This is an evidence-selection diagnostic on the SAME 48 evaluated questions.
There are no new independent queries, source families or human adjudications.

## Question fixed before this stage's execution

The original candidate selected at most one window, whereas ranked3 delivered
up to three. The completed original run 38189628380 remains immutable under
source `920aede3...` and artifact 11721757214, ZIP SHA256
`53dff155f79d4b333ba30060022cc38d351807993f09812ee94e0d8f5f24aee3`.
The prior result did not qualify the end-to-end candidate. It is not relabelled
as a token-matched experiment by this patch.

Use exactly the same twelve fixed support IDs, six family Cells, cached prior
training cut, losses, regularization, Encoder, Reader, evaluation questions and
counterbalanced arm order. Do not replace uninformative supports. In the new
explicit `--evidence-mode matched3` mode, all SEVEN evidence-bearing arms select
exactly min(3, pool size) windows from the SAME frozen top-four proposal.
No-evidence remains a separate zero-evidence control. This deliberately removes
the old stop decision from evidence arms: it is fixed-cardinality selection,
NOT a newly calibrated refusal strategy. The original single mode stays default.

For each query, compile the original frozen top-three bundle with the actual
Reader tokenizer. Its COMPLETE input token count is the ceiling for every arm,
subject to the existing 4096 absolute limit. Enumerate all at most four admissible
three-window subsets; preserve frozen rank order within each bundle. Pick the
feasible subset maximizing the sum of that arm's already-frozen candidate scores.
Prefer the frozen set on a tie, then candidate IDs. This is additive subset
ranking, not learned joint sufficiency, combinatorial reasoning or FBSDE utility.

An alternative with more input tokens than the frozen reference is excluded even
if it scores higher. Evidence is never shortened. A baseline prompt above the
absolute cap fails rather than shrinking its set. Each alternative is rendered
as a complete prompt: fragment lengths are not assumed to add exactly through
chat templates/tokenizer boundaries. Before success, actual generation receipts
must match the selected input digest, token count and evidence cardinality.
Equal count and no-greater input tokens are NOT equal FLOPs, generated tokens,
wall time, training cost or full lifecycle resource usage.

## Execution and observations

This patch does not claim local execution: both the container and Python runtime
returned service errors before any tests could run. The new twelve pure selection
tests and two native-entry fixture tests require hosted execution. They cover
budget blocking, actual full-prompt counting, frozen ordering/ties, constant-score
offsets, small/empty pools, fixed proposal bounds, malformed measurements,
post-selection token drift, snapshot phase ordering and retained failure answers.
Existing regression tests remain in the full hosted discovery; no CI is waived.

The existing new-question workflow now explicitly requests matched3 and uses a
DISTINCT artifact name, `hepta-system2-matched-evidence`. It does not run a second
unrequested single-mode model trial. The separate historical replay and immutable
old-outcome audit workflows are unchanged. Successful generation would provide
384 actual Reader calls, not 384 independent or correct answers. Planning counts
must not be reported as completed work before reading the run result.

A post-execution check compares all 36 fitted state tensors exactly against the
pinned original trial and checks 96 no-evidence/ranked3 reference answers and
Reader input/output digests. Any divergence fails qualification and keeps the
raw files. Re-encoding and refitting are real work; old evaluation features were
not exported for direct reuse. Every prompt-probe attempt, including errors,
is journalled. Snapshots freeze before evaluation and outcomes are scored only
after the full raw-answer journal is sealed. F1 and weak-source membership retain
their separate unknown-value denominators and existing strict progression gate.

No serving policy, old score, benchmark annotation, NDU interface, human review
or production acceptance changes. A positive result would still need independent
semantic review, fresh source/time-separated confirmation, retention and task-cost
validation. New supervision or a larger Head is a separate factor, not bundled
into this resource-control experiment.

```sh
HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD) \
  python scripts/memory_cell/system2_new_questions.py \
  /path/to/memory-inputs /path/to/pinned-ranker /path/to/content.zip \
  /new/output --evidence-mode matched3
```
