# Bounded retention of supplied-law task value

This research implementation searches for feasible fixed-hidden readout edits
under one exact shared196-coordinate radius. It permits disagreements with the
optimal supplied-law policy and evaluates every proposal using the complete
finite task, including its own visitation distribution and terminal decision.
It does not establish the maximum achievable value within that radius.

## Method and evidence boundaries

Q-only, Belief-only, joint196 conic proposals and a projected-gradient196
reference use the same fixed GEN state selection, labels, soft loss and radius.
The conic method is teacher-guided analytic distillation with an optimizer and
direct parameter editing. It does not backpropagate through the representation.
It is not a strict label-free WeightCode reproduction: that paper's method
boundary excludes solvers on label-derived targets and iterative label-driven
updates. The gradient comparison is a head-only reference, not full-model
training or an agentic MIT reproduction.

GEN/SELECT/TRAIN_AUDIT are a32/16/16 reallocation of64 previously exposed TRAIN
worlds for each of five fits. They are not independent validation data. Selection
uses complete equal-world expected task utility; the original KEEP model
participates with fixed tie precedence. The global choice is restricted to the
already selected family finalists. AUDIT cannot change choices.

After a complete successful MAIN process and candidate/selection seals, one
entropy acquisition generates eight IID and eight OOD public schedules per fit.
All80 are checked against a hash-only inventory of3636 known schedules and each
other. A collision fails the queue without replacement. The same checkpoint law
provides transitions and task payoffs; this is fresh public-schedule confirmation
conditional on that law, not independent financial labels or market efficacy.

The two component restorations of G_SELECTED are strict no-solve diagnostics:
restore original Belief or restore original Q. They are sealed after selection,
evaluated in TRAIN_AUDIT and confirmation, and never reselected. Separately
optimized Q/B arms are refitted controls, not these causal ablations.

## Exact source and numerical contract

The input manifest binds original compressed checkpoints, cached X85 and source
records. AST-only loading selects original semantic definitions; no old
experiment entrypoint, truth transitions or matrix exponential is executed.
The task observes the sign at observation completion and always targets the
fixed deadline6. Public features retain charges, pending requests, broken sensor
state and the complete observation history.

The old own-law teacher source is `causal_core.py` at
`hepta-private-ci@ad9309182ef71a6007257464d8b132cd5fc0ee7a`, repository path
`qualification/weight_space_nextstage_20261120/neuron/source/causal_core.py`,
SHA256`68bf0f31749dfb2dc3e50d44666906763898f4c8fe0ecbc9fd79c91de03fa180`.
Its `construct_program` uses the full-state `enumerate_graph` Bellman result,
with actual accumulated-charge differences and ordered F64 addition. It does
not use the charges-zero reconstruction in `Oracle.q` recursion for these
teacher labels. Original teacher bytes and rebuilt Q/posterior/mask/state order
must match exactly. Illegal continuation Q slots remain positive F64 zero.
Original cached C scores come from the same augmented H49 reduction; their
authentication is also exact. A changed environment that cannot reproduce these
contracts fails; it does not trigger a relaxed tolerance or another attempt.

The exact ball is
`4 * sum((new196-old196)^2) <= sum(original_Q147^2)` using rational F64 values.
Q147 and Belief49 share this single bound. Conic balls and gradient projections
use a predefined numerical inner factor0.99999999; the penalty uses the
unshrunk numerical base radius. Saved coordinates must pass the exact check.
Native export order is row-major w2[4,48] followed by b2[4], with no F32
conversion. The hidden representation and law remain protected.

Complete policy evaluation saves all states, scores, actions, costs and actual
occupancy, including zero incumbent-occupancy states. It checks
`Jstar-Jpi=sum(d_pi*(Vstar-Qstar_action))`, with terminal and continuation terms
separate, as well as terminal mass and payoff-minus-cost identity. Old
occupancy times optimal gap only screens GEN rows. Its omitted mass is reported
and is not a bound on candidate value. Posterior MSE and terminal ranking
diagnostics reuse existing scores and distinguish common original occupancy
from candidate-specific occupancy.

## Bounded execution and outputs

All output directories and records are create-only. Real runs require a frozen
protocol containing every implementation/source/input hash, split, review and
resource contract. `freeze_protocol.py` first performs a five CPU-second,
15-second metadata-only preflight; it never performs a model forward or solve.
The final freeze rechecks those pins. Recovery and draft reconstruction after a
container loss are explicitly recorded; old runtime timings are planning only.

`supervise.py` runs each real phase once, on CPU7 with one thread and512MiB
address space, and records complete subprocess lifetime and supervisor overhead.
MAIN is limited to150 CPU/240 wall seconds; confirmation and the independent
reader each have60 CPU/120 wall seconds. Per-family numerical caps are nominal
boundary-checked limits, not hard real-time guarantees. Actual overshoot,
failed/skipped proposals, artifact serialization and shared preparation are
preserved. G and training have the same three CPU-second numerical cap, not
necessarily equal observed use. No automatic retry, retuning or extra checkpoint
is allowed.

Up to35 optimized heads,25 conic attempts and five fixed PG trajectories are
registered. MAIN has at most2720 complete policy DPs; confirmation at most560.
The own-law optimum DP and graph/feature construction are counted separately.
GEN incumbent evaluation is paid once and explicitly reused for screening and
the final GEN record. This finite research workload is not future serving
demand or evidence of computational break-even.

The independent reader reconstructs raw inputs/heads and exact norms, checks
selection and timing seals, and separately implements scalar policy value,
occupancy and the full performance-difference identity. For the80 confirmed
global policies it also invokes the original recursive task executor with
original semantic feature forwards. It never optimizes another candidate.
Its successful output is `READER_RESULTS.json` with status`PASS`.

Reusable code reads private evidence only through explicit roots/manifests.
Actual protocols, checkpoints, inputs, numerical results and local paths are
private evidence, not synthetic CI fixtures. The ordinary CI command is
`python -m unittest discover -p 'test_*.py'`; these controls use only tiny
synthetic arrays and metadata and do not access real checkpoints or teachers.
Applicable repository instructions are pinned separately. Production/financial
admission remains KEEP/STOP when its owner or evidence contract is unavailable.
