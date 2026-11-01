# Independent model-to-runner review

## Disposition

The reviewed current source has no remaining must-fix causal or terminal-value
defect in the inspected path. This review does not qualify scientific benefit,
continuous-time efficacy, production adoption, physical energy or all-repository
CI. Its code scope is `execution.py`, `training.py`, `run_study.py` and
`launch.py`, with the model/task interfaces inspected for consistency.

Two concrete execution-cost defects were identified and reported before fresh
confirmation. The author corrected both while retaining the failed development
attempts and their process receipts:

| Finding | Original consequence | Current-source resolution |
| --- | --- | --- |
| One Runtime used for fixed and then value | Fixed paid cold table preparation; value inherited its cache | A fresh Runtime is constructed for each candidate/controller pair |
| Episode timer began after metadata/setup and ended before terminal scoring | The inner-loop CPU number omitted real deployment operations | Timer now starts before public-file loading and includes owner/RNG setup and terminal evaluation |

The original development failure caused by NumPy Boolean JSON serialization
was separately fixed by the author. Current wrong-submission/sign diagnostic
fields explicitly become Python Boolean values. Earlier source/logs remain
under `digital-runs/development` and `development_source_v1`; their failures do
not become successful confirmation observations.

## Executed numerical interface checks

The read-only numerical audit used Python 3.12.14, NumPy 2.3.5 and
PyTorch 2.15.0+cpu. Source hashes were checked before imports and again after
the numerical checks to reject concurrent source drift.

| Check | Observed result | Exact scope |
| --- | --- | --- |
| NumPy Runtime versus Torch policy | 2,790 rows; maximum output error `8.881784197001252e-16` | 24 candidate configurations plus nine already-written development models, six causal task states, every latent row |
| Legal greedy action consistency | Zero mismatches | Same 2,790 rows; no claim over all possible floating-point states |
| Runtime transition sampling | 1,377 matching sampled destinations | Independently sampled CDF of the returned normalized transition rows; not an independent physical-kernel oracle |
| Realized on-policy supervised loss | Exact agreement with a manual single-state loss | Recorded latent index 8, masked six-action Q loss, belief BCE and raw regularizer |
| Conditional-prefix misuse countercheck | A deliberately invalid prefix was never inspected | The one-hot visited-state row completed loss/backward with finite gradients |

The seven expanded structured outputs agree with the NumPy deployment formula
and the inherited action order. The terminal signed values are derived from
the same belief used by the fixed controller.

The earlier model suite passed 11/11 checks, zero skipped, in 0.141 seconds.
That suite was not rerun in this review. Its model and test source identities
are retained with the audit; the numerical interface checks above are new
focused checks addressing the runner risk.

The first ad hoc review command had a Python token typo (`else0`) and stopped
at parsing before imports or execution. The corrected command produced the
recorded audit. This was a review-script failure, not a study execution or
scientific outcome.

## Causal and objective findings

- `run_episode` chooses the action before `Owner.step` opens any newly due
  packet. Context construction uses the pre-interval symbol and adds only a
  successfully completed observation. Impulse propagation applies its neutral
  interval transition before the completion injection, matching training.
- `extend_behavior` reconstructs full prefixes from each original actual-read
  receipt. It preserves observation order and never interprets request time as
  completion time.
- Fixed-behavior rows use the complete conditional cell distribution. Realized
  greedy-state records use a one-hot recorded cell index with detached
  occupancy. The latter is supervised dataset aggregation; it does not acquire
  a policy-gradient interpretation.
- A halfway occupancy snapshot can become stale after further updates. This
  is disclosed in the protocol, and final selected-Q errors, margins and
  coarse occupancy coverage are recorded. The coarse key omits exact history,
  timings, prices and latent state, so covered keys do not prove full support.
- Legal actions mask both training Q loss and deployed selection. Illegal Q
  targets are stored as finite placeholders and receive zero loss weight.
  Terminal targets are remaining utility, while terminal scoring subtracts
  accumulated task charges exactly once.
- Teacher Q values are the fitted-law optimal-continuation reference. They
  are not automatically the actual return of the eventual imperfect greedy
  policy. Actual terminal task utility remains the efficacy endpoint.
- Private evaluator labels are opened only after task termination in the
  inspected execution path. Fitted-oracle diagnostics occur after the chosen
  action and are not inputs to later learned decisions.
- Final optimizer update selection and common paired initializations are
  explicit. On-policy arms receive an additional supervised visited-state
  distribution, and their collection/teacher computations consume the stated
  learning CPU allowance and remain in total cost.
- Confirmation verifies source/protocol, training-data and all-model hashes
  before generating new IID/OOD worlds. The nonempty published-commit field is
  a provenance receipt requirement, not an independent remote-Git verifier;
  actual remote publication/readback must be performed by the delivery work.

## Cost interpretation retained

The corrected episode CPU metric includes metadata, task owner/RNG setup,
actual content work, finite-table preparation, model decisions and terminal
scoring. Oracle diagnostics are separately timed. Runtime array construction
is outside an episode but has its own candidate/controller receipt. Aggregate
statistics, serialization, imports, global model/content setup and shutdown
remain in stage or OS-child totals. Nested scopes must not be summed twice.

The CPU-limited training panel starts its allowance after model/optimizer
setup; setup remains separately recorded. Whole-process costs include shared
data preparation and all candidates. Any future per-deployed-model lifecycle
comparison must state how shared preparation, candidate search and development
costs are allocated or amortized. Runtime array byte counts omit Python object
overheads; measured process RSS is the broader resource observation.

Each controller gets a fresh finite-table cache, but OS file caches and loaded
libraries are not cold-reset between candidates. These are host research
measurements under bounded parallel execution, not isolated hardware energy
or cold-start service benchmarks. Bayes-reference coverage fields use empty
training sets and must not be pooled with learned-model support diagnostics.

## Retention evidence

`/tmp/digital_retention_checks.json` contains the numerical results, exact
source/dependency hashes, the previous 11-test receipt and 30 retained probes
from `retention_diagnostics(fit=101)`. These probes use the seeded initial
physical parameters, not fitted study checkpoints. A balanced hidden class
produces a single observation at reliability `.85`; cell-only recoverable
accuracy and Brier score are then calculated from its propagated law.

For illustration, the initial first-passage candidate at elapsed time 3 has
cell-only recoverable accuracy approximately `.63614` under sustained drive
and `.52644` under one-shot impulse. The public last-observation channel still
retains `.85` recoverable accuracy in both cases. Removing event sign reduces
the respective cell-only accuracies to `.53146` and `.50436`. These probes show
why persistent input, event sign and reset cannot be conflated; they do not
establish which trained policy has higher utility.

## Reviewed source SHA-256

| File | SHA-256 |
| --- | --- |
| `models.py` | `a1ba992b5756e53317964629aeb063b60732d632670ad8da2193700cb33ef495` |
| `model_checks.py` | `b997c877fa91c3c6361a37e54d4d413b4eb68af64b29ad56b4af7a8c41f4f540` |
| `execution.py` | `c8d604228be101a452a8aef9753d6f3d7844b83126773ec76504c6637e79911b` |
| `training.py` | `7bdf1274dd3f2207e0c79c82a6e92a5f122cbc1acaac7a77ef78d310c9600f46` |
| `run_study.py` | `94cfae89eaea6abf0bc07f7aec557d2f8731a1a5e32d3bbfdcc7a5d161004382` |
| `launch.py` | `d66633ffdc4372cc8546c7f3a1ae243e4abb9f7577461319b0f532e6704dca1b` |

Inherited model/bank/task/content-adapter dependency hashes are in the JSON
record. A later code change requires a new scoped review or an explicitly
documented equivalence check before inheriting these observations.
