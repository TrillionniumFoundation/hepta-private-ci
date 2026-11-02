# Observation-law reliability follow-up

This additive round preserves every R1 failure and checkpoint. Read
`LAW_AUDIT.md` for the observable conditional law, information boundaries,
correlated-query qualification, and scope exclusions. The source/protocol,
single fitted mixture parameter, and development result were frozen remotely
before opening a new confirmation stream. No development threshold search is
performed.

The new readout is an ordinary streaming parser with an explicit task-law
prior. It uses raw typed observations and bypasses the learned neural content
state. The same readout is attached to every Flow/Diagonal pair; outputs are
shared across their three historical model seeds. An exact-law ordinary parser
is the strong comparator. A finite-interface success cannot establish a neural
uncertainty repair or analytical-core gain.

`posterior.py` accepts only `x`, `dt`, and `observed`. The declared task is fixed
at construction. Query answers, teacher posteriors, dependency indices,
availability flags, sample IDs, row numbers, split identity, and future queries
are absent from inference. The acceptance hash uses visible semantic state and
the current query, and is invariant to row order and inserted typed distractors.

The original reliability gate remains accepted-answer accuracy at least95%
and known-answer coverage at least80%. The final-update ambiguity branch has
maximum class probability about2/3. Accepting its fixed quarter subset can meet
the **aggregate** gate when mixed with certain answers; it is not a claim of
95% reliability per answer or within that ambiguity branch. Conditional branch
counts and errors remain visible.

The implementation is scoped to the frozen four-key/eight-value task law,
fixed observable prelude/update stages, visible bridges, and zero or one erased
WRITE. It is not resampling-qualified: an unobserved slot is interpreted as an
erasure rather than a clock-subdivision placeholder. It does not cover unknown
generators, multiple erasures, open-domain memory, or a production interface.

Run from the repository root with Python3.12, NumPy, SciPy and CPU PyTorch,
using one OpenMP/BLAS thread. Choose a new output directory:

```sh
python -m experiments.hcsn_missing_reliability_r2_20261101.campaign freeze --out NEW_RUN
python -m experiments.hcsn_four_stage_flow_20261031.meter --out FIT_METER -- \
  python -m experiments.hcsn_missing_reliability_r2_20261101.campaign fit --out NEW_RUN
python -m experiments.hcsn_four_stage_flow_20261031.meter --out DEV_METER -- \
  python -m experiments.hcsn_missing_reliability_r2_20261101.campaign development --out NEW_RUN
# Publish/read back all source, protocol, candidate and development identities.
python -m experiments.hcsn_four_stage_flow_20261031.meter --out CONFIRM_METER -- \
  python -m experiments.hcsn_missing_reliability_r2_20261101.campaign confirmation \
    --out NEW_RUN --candidate-sha EXACT_CANDIDATE_SHA --publication EXACT_COMMIT
```

The source, R1 checkpoint manifest and R1 calibration manifest are hash-bound.
R1 checkpoints and calibrations remain at their original relative paths; they
are not refitted or selected. The new `CANDIDATE.json` fits one scalar q from
4096 training episodes; its correlated ambiguous-query count is not an
independent-binomial sample size. Development and confirmation use different,
previously unused source seed namespaces.

Raw shared probabilities, exact ordinary reference probabilities, labels,
scoring availability, groups, visible old values and acceptance masks are saved
once per task/condition. Each neural baseline saves only query logits; its
frozen temperature/threshold reconstructs probabilities. Shared readout rows
reference the same raw arrays instead of claiming independent copies.

Outer wait4 receipts account for fit, development and confirmation startup,
imports and writes. Inner timers are nested and are not added again. Historical
training/preparation, source publication, supplemental fixture checks and
independent audit preparation remain outside these measured components.
Energy and full process-family memory are unknown.
