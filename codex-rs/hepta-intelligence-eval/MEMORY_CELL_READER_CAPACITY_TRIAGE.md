# MemoryCell — strict Oct 12 Reader evidence-capacity triage

**Status: independent archived-artifact audit only, not model performance admission.**

This control uses exactly the 2026-10-12 pinned strict 576-attempt experiment:
GitHub Actions run [38202116864](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38202116864), generating commit
`d0f69d7b94f65730fa1e093dee6989916f01898e`, archived ZIP SHA-256
`07b0f15ec150cc9817db6bfc9b4bae1e2c06a5296ca2ba3c4c7895da18b99e2f`.

The read-only Python auditor validates the externally fixed ZIP hash, all
**151 SHA256SUMS members**, generating commit and tree, exactly 576 original
policy identities, and all **32** preregistered evaluation question identities.
It then compares the following *already generated*, frozen-model conditions:

* Original frozen selector and its one delivered Reader evidence window.
* A separate byte-identical Reader given the same original question and
  **zero evidence**; cached answers and execution receipts remain separate.
* An original post-policy answer-dependent **literal-span privileged oracle**,
  when such a native source span can actually be constructed.

All three Reader weight/prompt/query identities must match. The auditor never
loads an Encoder/Reader, does not perform optimization, and never copies the
original raw answer text, source excerpts or private gold into its result.

## Observed facts from original archived output

The strict original run completed **576/576** logical six-arm attempts,
with **1162 Python regressions** and an independent successful nonpromotion
audit. The privileged post-policy comparator has 32 rows:

| Archived post-policy condition | Count |
| --- | ---: |
| One answer-conditioned literal source span available | 8 |
| No admitted literal reference span available | 17 |
| Native annotated-unanswerable control | 7 |

For the eight literal-source rows, paired original diagnostic token-F1
against the zero-evidence Reader was approximately **+0.107**, with no
guarantee of independently verified answer correctness or citation entailment.

The **17 missing literal spans are unavailable oracles, not Reader
execution failures**. Twelve of these 17 had a weakly annotated native
support source in the frozen candidate pool, underscoring that *source
presence* does not prove the exact answer string appears in an eligible
verbatim span. Conversely, a privileged answer-conditioned span is not a
blinded reference context or independent human-certified sufficient
evidence. It is unsuitable for training, hyperparameter selection or a
production admission claim.

The material also reports that the native test cut missed two of six
annotated answerable sources at retrieval, while transfer retrieved all
seven annotated answerable sources, with weak native document-level
support only, not window-level entailment. The fixed Reader rarely emitted
a valid source citation marker.

## Output and go/no-go interpretation

`scripts/memory_cell/stem_oct12_reader_capacity_triage.py` plus its exact
source CI workflow
`.github/workflows/hepta-memory-stem-reader-capacity-triage.yml` will
write one SHA256-manifested record showing all 32 question-level matched
conditions without source text or answers. Fail-closed synthetic tests reject
missing/duplicate questions, Reader weights/prompt/question drift, forged
oracle evidence, oracle absence promoted to model failure, label
disagreement, leaked targets in no-evidence input, and nonfinite scores.

**Not yet established:** whether an independently assembled and manually
confirmed sufficient evidence context enables a stronger Reader to solve
the task; whether a learned Cell improves support retrieval on untouched
source families; semantic citation entailment/precision; independently
observed future-window retention; per-Cell p95, dollar and energy TCO; or
a production rollout. `production_accepted=false`, and Cell scale-out
remains prohibited.

The natural next controlled experiment is a *blinded* sufficient-evidence
review and strong Reader benchmark on the new pre-registered LoCoMo
family-separated retrieval cohort. It must keep selection labels separate
from evaluation labels and must not count post-hoc answer-conditioned Oracle
spans as an independent gold reference.
