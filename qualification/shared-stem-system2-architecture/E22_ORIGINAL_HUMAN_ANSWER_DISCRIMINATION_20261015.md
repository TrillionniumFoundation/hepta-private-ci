# E22: answer-information obstruction on original human MultiRC

**Research / Draft / DENY_ALL.** This is an additive child of E21 [PR #2252](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2252), exact starting commit `78aa6df0d5fe8ab2f3240748dbee02b10dc4937f`. It does not mutate source original model bytes, E21/E15 scoring, production Reader, NDU, CNS, Neuron, CAS/WAL, FinalUse or main.

## Why E22 is a different scientific question

E21 counts candidate accuracy, Brier, and *complete* questions. But a Cell/NDU planner cannot manufacture an answer-distinguishing signal if the only admitted Reader output is identical across alternatives. In the original archived MultiRC research, the no-query arm has **exactly invariant candidate probabilities within all eight original questions**; the conditioned Reader is near-invariant in the prior audit, which is *a diagnosis rather than an information-theoretic impossibility theorem*.

E22 audits the actual **same six original frozen/learned Reader arms**, with the original pre-score SHA-pinned ModernBERT archive and E15 four held-fold model predictions already consumed by E21:

- Blind, prelabel phase: for each of the eight real questions and six unchanged arms, measure probability span, exact constant score, number of emitted binary classes and <=0.001 span as explicitly *descriptive* geometry. Retain SHA of original serialized blind E21 source and seal E22 geometry **before human labels**.
- Independent original-human postseal phase: reopen publisher-pinned MultiRC validation parquet ONLY after checking both E21 and E22 blind artifacts. For every within-question positive-vs-negative candidate pair, report correct ordering, reverse ordering or exact tie. Also report mixed-question classification success, whole-passage success and per-question constant-score/constant-hard-class obstruction.
- Independently recompute E21 per-arm accuracy, two-class Brier, passage vectors, 0–8 complete questions and 0–4 complete passages; refuse any mismatch to the completed original independent E21 scorer, itself required to reconcile **both** original E15 source/merge human-score archives.
- Preserve deterministic tie policies: frozen original logits select binary 0 on exactly 0.5; learned logistic Heads use >=0.5. A constant *hard class* necessarily fails any mixed-label question, while an **exactly identical score** cannot be separated by a downstream deterministic function receiving that score alone. Small nonzero probability differences may still contain useful information; none is automatically called impossible.
- Keep human labels out of blind artifacts and out of CLI input in the blind job. Seal outputs create-only; reject malformed/duplicate JSON, changed source/model generations, forged results, incomplete answer candidates, false newly-run models, and premature authority flags.

## Actual executable regression evidence

`e22_answer_discrimination.py` plus `test_e22_answer_discrimination.py` were physically executed locally under both normal and optimized Python: **12/12 and 12/12** with strictly *synthetic* 33-row MultiRC-shaped labels. The two uploaded Git blob IDs must equal the locally tested object bytes, and the hosted run must execute the exact original E21 archival ZIP/held-human scoring dependency: source-only synthetic tests **do not** count as real-human model efficacy.

The existing `.github/workflows/hepta-e21-original-human-question-complete.yml` is extended rather than replaced: the first job loads E21's byte-pinned original pretrained source/four genuine E15 held-fold ZIPs, runs all retained tests, creates the original E21 seal, then creates an E22 blind seal. The independent second job checks BOTH seals before downloading human labels; runs the retained E21 original E15 human-score reconciliation; and executes the E22 original-human rank/obstruction scorer. Source HEAD and synthetic merge remain distinct; every required step must finish at the new exact commit. Host comments, SHA fields and same-run process boundaries do not authenticate external publishers beyond their actual verified provenance.

## Decision boundary

E22 *does not* solve Reader insufficiency; it makes the bottleneck harder to bypass. Genuine P0 GO still requires independently collected additional passages, candidate-specific evidence sensitivity, removed/perturbed premise controls, source-group uncertainty, lower and upper resource profiles, and held-out answer/classification improvements over frozen/professional baselines. An observed positive logit span alone is NOT proof of correctness, and 33 dependent candidates are NOT 33 independent problems.

All E22 outputs retain `reader_sufficiency_certified=false`, `answer_information_support_for_full_ndu_system2=false`, `ndu_system2_admitted=false`, `model_selected=false`, `production_accepted=false`, `DENY_ALL`. No production promotion, main merge, new authorization, active Cell Split or large-model equivalence claim.


## Retained real-original pretrained **blind** execution, not synthetic evidence

Downloaded the exact original successful GitHub Actions pretrained ZIP artifact `11946621518` (outer SHA-256 `1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17`) and the actual **four** E15 held-fold prediction ZIPs, verified each original external ZIP, original held-prediction member SHA, original E15 training source HEAD, E21 original prelabel COMMITTED observation and exact case/group/answer identity. Physically rejoined 33 original candidate probabilities from the four frozen ModernBERT Reader controls and two **actually trained historical E15** Heads; **zero new pretrained forwards or Head updates**. The true original human label ZIP members and parquet were *not* read in this blind computation. The complete original-model E22 prelabel observation is retained as `E22_REAL_ORIGINAL_BLIND_OBSERVATION_20261015.json` (no raw candidate probabilities, media or labels) and independently re-counted using a second algorithm over the actual source output.

| Actual archived Reader arm | Questions with exactly identical scores | Questions predicting one hard class | Questions with score span <=0.001 (diagnostic) |
| --- | ---: | ---: | ---: |
| conditioned | 4 / 8 | **8 / 8** | 8 / 8 |
| mean_pool_query_fused | 0 / 8 | **8 / 8** | 0 / 8 |
| no_evidence | 0 / 8 | **7 / 8** | 0 / 8 |
| no_query | **8 / 8** | **8 / 8** | 8 / 8 |
| learned_linear_5 | 0 / 8 | **8 / 8** | 2 / 8 |
| learned_gated_3 | 0 / 8 | **8 / 8** | 0 / 8 |

This is a **real pretrained archived numerical replay with label-blind outputs**, not an original-human E22 scored result, not three future datasets, and not an independent new model-training experiment. Exact held human-label rankings and complete-question results still require the hosted E22 scorer after the original E21 two-artifact reconciliation, and ordinary candidate correctness should never be mistaken for complete mixed-label question success. The new E21/E22 blind workflow independently checks the frozen six-arm numeric *counts* against the sanitized actual original ZIP observation, without assuming identical floating-point serialized SHA across Python/OS versions. The numerical observation is a **negative bottleneck finding**, not a new benchmark winner or model-selection authority.
