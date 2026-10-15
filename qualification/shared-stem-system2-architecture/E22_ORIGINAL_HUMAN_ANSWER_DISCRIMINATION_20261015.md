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
