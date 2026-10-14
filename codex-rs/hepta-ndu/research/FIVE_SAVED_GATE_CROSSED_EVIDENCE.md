# Crossed-evidence audit of saved shared-Encoder Heads

2026-10-14. Fixed new DEVELOPMENT comparison. No Head fitting, Reader generation,
new donor choice, external reviewer grade, model promotion or changed threshold.
This does not complete one of the five independent efficacy experiments.

## Identification question

The preceding study scores q_A and q_B on the same donor evidence E_B. A score
f(q)+h(E) can rank q_B higher for every E, including irrelevant E. A nonlinear
question-only lookup can also pass that one-way comparison. Therefore positive
one-way ranking does not by itself identify useful question/evidence interaction.

Keep the already selected questions and their ORIGINAL source bundles E_A,E_B.
Evaluate four corners s_AA,s_AB,s_BA,s_BB on every saved Head and every registered
seed. No source rewrite, label repair, donor re-selection or target text in the
Encoder. Dates, positions, full source bodies and local citation names stay.
The old pair consists of BB and AB; AA and BA are the additional corners.

I=s_AA-s_AB-s_BA+s_BB cancels arbitrary additive question and evidence main
effects algebraically. It does NOT cancel all superficial nonlinear cues and
is not semantic accuracy. Also report BOTH question rankings (AA>BA,BB>AB),
BOTH evidence rankings (AA>AB,BB>BA), and all four fixed-threshold signs
(AA>0,BB>0,AB<0,BA<0). Positive I alone implies none of those conjunctions.
All missing recipients stay; means are conditional on observed pairs, family
macro results are separate and no confidence interval/significance is fabricated.
The reverse crossing is still only a weak negative, not certified insufficiency.

## Exact upstream and read-only ownership

The original b531b26 run38522429524 failed before any model load because its
direct CLI could not import experiments. Its217 passing tests are not a model
result. The separately pushed CLI-only correction is
592b5b645ada09c335f942ce7ca11561d5eb2cf1/run38526481788.
This audit accepts ONLY that exact successful source/run and one authenticated
named artifact with SHA256. Failure/queue gives an explicit deferred result;
no old candidate substitution, retry, refit or polling occurs. Archived Python
is never imported. Default original study science remains byte-compatible.

Whole result archive/member checks, original scientific plan and raw seals,
all five arms/three seeds, each safe Head checkpoint and receipt are validated.
The original TRAIN/SELECT public feature plan is rebuilt from its prior pinned
manifests. No SELECT fitting, seed selection, threshold calibration or optimizer
is present. Only the strict existing archived Encoder supplies features.

The first study did NOT export its feature tensors. Accordingly this audit
pays once to reconstruct its exact original scope/batch input groups, checks
saved Head logits against all original available pairs (fixed replay atol1e-6,
rtol1e-5), and stops if replay fails. This is a newly registered read-only replay
check, NOT a change to the FAILED assistant-projection weight tolerance.
There is no tolerance tuning or retry. New own-evidence vectors are encoded only
where absent from that reconstructed scoped cache. Full token preflight of all
old/new components precedes any Encoder model load, with no truncation/fallback.

Historical BB/AB logit numbers are then reused unchanged; only AA/BA are newly
predicted. There is one Encoder owner and independent frozen saved Head objects,
not a new Encoder per Cell. Feature tensor identities are checked throughout,
and this audit exports its frozen features with a hash for future read-only
reuse. The representation is still mean pooling and independent per-vector L2,
not normalization fitted on SELECT. Model/feature/cost outputs are diagnostic
artifacts, not access authorization for production cache or Reader skipping.

Reconstructed old feature work, extra encoding, saved-head replay, new prediction,
loads and archive checks all remain paid costs. No total-RSS/energy/FLOP/speedup
claim follows from tensor counts. Seeds and reused donors are not independent
tasks. No new task-quality equivalence with421M models is asserted.

## Validation and execution status at publication

35 new synthetic test definitions cover exact rectangles, old-score references,
source identity/partition/date preservation, missingness, arbitrary additive
cancellation, fixed-threshold distinctions, actual linear/gated arithmetic,
unchanged parameter state, family weighting and strict dependency metadata.
These are submitted, not claimed passing: local container/Python probes failed.
The dedicated workflow requires these and targeted inherited tests before any
pretrained material acquisition. It records execution-disposition.json so a green
contract-only/deferred run cannot be called a completed model comparison.

The CLI correction separately adds4 subprocess tests and retains all217 old
tests. Neither this additive audit nor its pushes start the parent Head training
again, and neither touches Reader LoRA recovery or the original SELECT runner.
Files: shared_gate_crossed_evidence.py, shared_gate_crossed_trial.py,
test_shared_gate_crossed.py, hepta-shared-gate-crossed.yml.
