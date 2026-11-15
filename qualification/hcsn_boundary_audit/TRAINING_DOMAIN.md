# Strict retained-training-law continuation audit

The hosted pilot's existing numerical gate is **HOLD**. Every one of its
14,336 recorded valid probability positions exceeds the unchanged 1% scaled
continuation-value error threshold. Probability conservation, recorded event
replay and analytic continuum-basis gradients satisfy their existing limits.

This is a measured failure of a particular numerical comparison. The value
probe repeats each recorded interval indefinitely, without future observations,
from the same reconstructed recorded posterior. Its error is not the error of
the actual asynchronous task loss or its actual finite future gap sequence.

## Source and journal lineage

The input is the completed three-seed, four-arm hosted pilot at training source
head `5578bd1931afcb6facbf72176cf479b902301feb`, Actions run
`43127560720`, job `130883401533`. SUMMARY SHA256 is
`c60378ffc2a51f580a9b7cfd11a09cec5f53d9a9cc37c03b81605bedc54b8715`.

`audit_training_domain.py` is a post-training adapter. The original factorial
journal does not use the TrainingDomainRecorder envelope. The adapter verifies
the original SUMMARY, PLAN, DATA, all 23 recorded source hashes, arm results,
and all 12 full training-journal hashes before deriving separate sidecars.
Original artifacts and numerical sources remain unchanged.

The exact declared seeds crossed with all four arms are required. Each
journal must cover its full training schedule in order. Every row's step,
episode, time intervals, complete valid mask, state count and original line
SHA256 are bound to its sidecar visits. Each arm contains 1,184 or 1,200
positions, so the existing 4,096-record audit limit remains unchanged.
There is no dropped-record sample or prefix presented as full coverage.

Each original training forward starts a new episode. The initial prior is
reconstructed by the unchanged operator from the source-declared
`absolute_initial=exp(.55)` and that row's recorded physical boundary.
Subsequent priors are the immediately preceding recorded posterior within that
episode. The original prior and interval determine replayed expected events;
the recorded posterior determines the continuation comparison.

The header's numerical-source identities are the exact eight-file subset of
the original source-bound training summary. They match the current auditor.
The sidecar explicitly states that its model hash is the original
`factorial.run.tensor_digest(FactorialModel.state_dict)`, not
`TrainingDomainRecorder.model_digest(network)`. Historical weights are not
available and are not claimed to have been reconstructed or replayed. A
separate postprocessing check confirmed all 12 first-row model hashes equal
their recorded initialization hashes.

## Unchanged oracle and thresholds

The adapter calls the existing
`qualification.hcsn_differentiable.training_domain_audit.audit_trace` with
`max_records=4096` for each arm. It changes neither its numerical algorithm nor
its thresholds:

| Comparison | Existing limit |
| --- | ---: |
| Scaled continuation-value discrepancy | 0.01 |
| Probability mass discrepancy | 5e-11 |
| Recorded expected-event replay discrepancy | 5e-11 |
| Scaled continuum-gradient discrepancy | 2e-9 |
| Maximum absolute continuum-basis gradient discrepancy | 2e-9 |

The value reference analytically integrates the continuum perpetual value over
every fixed active, tail and remaining-refractory basis at 80 digits.
The projected comparator uses its own repeated fixed-gap transition operator.
Gradient comparisons concern the analytic continuum basis coefficients, with
recorded posterior weights held fixed; they are distinct from the task-loss
gradient audit described in README.md.

The candidate uses 16 active cells, one tail coefficient and eight refractory
phase cells, for 25 probability coefficients. Physical sigma stayed at 0.35
and refractory duration at 0.2. The observed positive intervals were
0.001, 0.003, 0.02, 0.04, 0.08 and 0.16. No low-noise training or rare-tail
relative-precision qualification follows from this run.

## Complete result

All 12 arms and all 384 retained training forwards were processed. These are
384 update opportunities, comprising 288 actual Adam updates and the frozen
control forwards. All 14,336 valid positions were audited, with no truncation,
no source mismatch, no changed input and no audit exception.

| Check | Maximum observed discrepancy | Failed positions |
| --- | ---: | ---: |
| Continuation value, scaled | 0.731420170595066 | 14,336 / 14,336 |
| Probability mass | 6.661338147750939e-16 | 0 |
| Expected-event replay | 2.157562323246154e-17 | 0 |
| Continuum basis gradient, absolute | 3.552713678800501e-14 | 0 |
| Posterior-weighted continuum gradient, scaled | 1.808490479943470e-15 | 0 |

The minimum value discrepancy was 0.06979768892242026; its median was
0.17793795960956857. Grouping the existing results by recorded interval gives:

| Repeated interval | Positions | Median scaled value discrepancy | Maximum |
| --- | ---: | ---: | ---: |
| 0.001 | 2,056 | 0.69775956 | 0.73142017 |
| 0.003 | 2,400 | 0.46456568 | 0.52076723 |
| 0.02 | 1,936 | 0.23194979 | 0.27045461 |
| 0.04 | 2,668 | 0.17380146 | 0.19877232 |
| 0.08 | 3,080 | 0.12028197 | 0.13585703 |
| 0.16 | 2,196 | 0.07501663 | 0.08184855 |

The worst visit was seed 37, arm c0_b1, training row 30, visit index 1,152,
in `pair_composition/train/00002`. At interval 0.001, projected continuation
was 7.927324691449992 versus continuum reference 4.5785100728758845. Its
recorded tail mass was only 5.411341172761698e-11 and refractory mass was
0.04283341820940119. Large tail mass is therefore not necessary for this
observed failure. The short-interval pattern motivates a controlled
spatial/phase/quadrature refinement study; it does not by itself identify a
unique cause.

The process used 149.478878774 seconds wall time and 146.909961286 seconds
CPU time, including imports, input verification, conversion and all audits.
Wrapper wall time was 150.276991518 seconds. It terminated with exit code 1
because the complete retained-state audit was HOLD.

The unchanged original SUMMARY is retained in
`evidence/hosted-training-domain-43127560720.json` (SHA256
`12fa561e6b5e6f710d1239d2a00bcf596da9d0060bf4691473ff337b7b5d0822`).
It binds all original and derived trace hashes and all 12 raw audit-report
hashes. The adjacent diagnostics JSON records the above aggregation without
new model evaluations. Complete raw sidecars, reports, command and logs were
retained as a separate audit package.

## Reproduction and negative controls

Use the exact retained source tree and a CPU FP64 Torch environment with
mpmath installed:

```bash
python -B -m unittest qualification.hcsn_boundary_audit.test_training_domain -v

PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES='' \
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
python -B -m qualification.hcsn_boundary_audit.audit_training_domain \
  --pilot /path/to/experiment \
  --summary-sha256 c60378ffc2a51f580a9b7cfd11a09cec5f53d9a9cc37c03b81605bedc54b8715 \
  --output-dir /new/path/training-domain-audit
```

The three focused tests passed. They verify rejection of an altered original
trace before JSON parsing, rejection of an incorrect step or episode order,
and correct event replay from a real two-step network trace. Exchanging only
the two recorded posteriors in that last fixture makes the existing auditor
report a replay failure and HOLD. The original first test invocation had a
fixture-name collision with unittest.run before tests started; its source and
observed failure were preserved, then the fixture attribute was renamed.
No numerical tolerance changed.

Passing the adapter integrity tests does not make the candidate pass its
numerical gate. Numerical qualification, true continuum filtering,
whole-training-trajectory qualification, rare-tail relative precision and
formal confirmation remain false. The existing actual-gap finite-horizon
shadow oracle was not invoked by this particular audit.

