# E17 — original pretrained Reader answer-information obstruction

**2026-10-15 · DRAFT / SHADOW / DENY_ALL**. Stacked only on E16 #2205,
which inherits E15 #2195 → E14 #2178. No native Worker, NDU, selected
Encoder/Head, Q24/Q32, FinalUse, Artifact CAS, Evidence WAL, release,
existing `blocking-ci` or `main` mutation.

## Original source, question, and answer units

This is an actual historical pretrained ModernBERT + **four trained frozen
Reader** source: successful [workflow 38663684650](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38663684650),
GitHub artifact `11946621518`, entire ZIP SHA-256
`1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17`.
Immutable prelabel observation SHA-256
`c0a7ae08d682349ce8b8ebd3bce14fcfe5203f9c636cea3944a85a10f45f4840`.
There are **4 passages, 8 genuine human-created questions and 33 real
candidate alternatives**. Candidate rows share passages and questions;
**33 is not 33 independent semantic tasks**.

The label-blind source program calls the existing original
`e14_multirc_route.read_prelabel` owner and never opens the scored ZIP
member, its human labels, validation parquet or answer truths. It measures
exact original signed logits, probability spans, identical within-question
margin pairs and hard-label diversity. The **0.001 span** is an existing
*descriptive* threshold, not calibrated uncertainty, task truth, or a
permission to run System 2. No new pretrained Encoder/Reader forwards.

## Actually observed original frozen Reader signal

| Frozen original Reader | Exact same-margin questions / 8 | Probability span <=.001 | Same binary prediction on all answers /8 |
|---|---:|---:|---:|
| conditioned | 4 | 8 | 8 |
| mean_pool_query_fused | 0 | 0 | 8 |
| no_evidence | 0 | 0 | 7 |
| no_query | 8 | 8 | 8 |

In the independently checked historical original human-label score artifact
(matched SHA-256 `3a3fd807585dd09ef4f089391dc68db4b008e87b69060f68f384a07daaa9f8e4`),
**all eight questions contain both true and false human-labeled candidates**.
An action relying *only* on a representation exactly constant across the
candidate answers within a question must output the same class for every
candidate: it is **mathematically impossible** to achieve a completely
correct question when both labels occur. In this specific original panel,
`no_query` indeed has no within-question variation and scored **zero of
eight whole questions fully correct**, even while 19/33 isolated answer
labels were correct by its own fixed-class baseline. A misleading
candidate-level accuracy must not be promoted as evidence of answer reasoning.

The conditioned model's very small nonzero spans in four questions do **not**
prove zero information and are not a mathematical upper bound for all
possible learned nonlinear Heads. Mean-pool and no-evidence have observable
candidate dependence, but that does not prove their predictions encode
correct semantics. E15/E16 may amplify small signals or noise: wait for
independently scored, original human-label source-head/synthetic-merge
results rather than recycling synthetic-target tests.

## Two-phase independent source procedure

1. **Blind**: reacquire the exact original pretrained ZIP, reject changed
   ZIP/member/seal/source, read only frozen prediction and prelabel seal,
   generate a complete eight-question diagnostic and write it **create only**.
2. **Score-stage reviewer**: reopen and recompute original signed-logit and
   probability contrasts with a *separate implementation*; reject any changed
   model identity, arithmetic, action inventory, missing question/passage,
   tampered hash or unauthorized status. **Only after the blind artifact is
   sealed**, read the old historical score aggregate and check its exact
   bytes, eight mixed-label questions and zero full-question correct counts.
   This aggregate is not a freshly authenticated independent human annotation
   or prospective evaluation.

Controls include tampered ZIP, model/candidate mismatch, fake 0.001 span,
self-consistently rehashed false summary, false production flag, copied
prelabel semantics and wrong blind SHA. Ordinary and `python -O` regression
results run on the **actual** pretrained artifact, not generated logits.

## Next positive gate, not implied by E17

Continue E15/E16 **original-human** 4-fold, passage-grouped scoring only
when those distinct hosted jobs really complete. Treat E16 training-fold
scores as **underpowered retrospective** because there are only four
source passages. Reuse the independent P0 MultiRC Reader evidence and actual
pretrained re-forward studies #2080 and #2167; require answer-specific
sensitivity, held-group complete-question success, source-time-disjoint
future panels, proper calibration, old-task retention, full training and
model+Student+Verifier cost before granting any new Stem/Cell benefit.

Never infer that NDU-FBSDE mathematically solving a toy tree repairs the
underlying Reader representation. Even a surprising E15/E16 retrospective
winner must **not** become `CURRENT`, `FinalUse` or production without
original ownership, independent futures and `blocking-ci`.

**All outcomes `DENY_ALL`; `model_selected=false`; `production_accepted=false`.**
