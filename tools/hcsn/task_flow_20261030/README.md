# HCSN task values, separate observation/flow, and memory mechanisms

This campaign implements the five follow-up research questions authorized on
2026-10-30. Its fixed baseline is
`b1934022821f3fdafd509b43cf0c4d7d45852e6e` from PR #4330. It preserves the
495 historical trainings and the subsequent 148-run campaign, including the
failed joint memory/retrieval criterion and negative financial-shape comparisons.

Three separately scoped modules address those remaining questions:

| Module | New implementation | Scientific question |
| --- | --- | --- |
| `flow/` | Observe once; propagate without a fabricated observation; retain active/refractory probabilities, content and event bookkeeping | Does the declared frozen-coefficient finite model obey subdivision, conservation and gradient/reference contracts? |
| `memory/` | Bounded normalized residual writes, with original learned projections and dynamics; fixed/mass ridge and gate-family controls | Can retaining old associations and overwriting conflicts improve together, and is any gain specific to the financial functions? |
| `control/` | Shared trained content decoder, future-task action values and actual READ/SKIP/FIRE/STOP execution | Does the controller improve realized utility and measured full cost relative to same-information controls? |

Each module freezes its own protocol and source identities before evaluating its
new outcomes. Existing static encoder samples are not relabeled as fresh tests.
Numerical acceptance, successful execution, and comparative quality/cost are
reported separately. These studies do not establish a fully jointly trained
free-boundary multimodal backbone or production Hepta activation.

## Reviewable stages

The dependency order is numerical API and reference validation, memory mechanism
and paired training, task-control execution and cost, then independent review
and evidence integration. Generated checkpoints and receipts are evidence,
not handwritten implementation complexity. Existing `next/` and `third/`
sources are imported without rewriting their historical results.

The final result report and reproduction commands are added after the declared
experiments complete. Interim protocol files do not imply any acceptance pass.
