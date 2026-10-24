# System2: learn observed budget returns, not existence of a solution

Parent source: `e5999e69937fe1259591e477927a95057671eb71`.
This stage leaves Riccati, both child search policies, their saved critics,
prior experiments, Reader, serving defaults and native NDU APIs unchanged.

## Completed parent evidence

Run **38200287672**, job **114651959094**, completed successfully on that parent.
The actual hosted log reports **1,114 passed, 2 skipped, 1,116 total** and passing
static checks. Artifact **11725096251**: 284,167 bytes, external ZIP SHA256
`326d68e4fe0df296948f371976bf2950b520250d52ef792e8c613e96c058a9e7`.
This stage reads its preserved summaries and verifies the archive in hosted CI;
local runtime services were unavailable, so no local extraction is claimed.

All **27/27 shared-controller conditions** completed with zero failures. Full
trajectory/value agreement remains within approximately 2.85e-13. Across these
specific small problems, the reused dense map had lower median cold AND hot
latency than the Riccati path. At horizon 32, batch 256, seed 7, hot medians were
~1.303 ms Riccati and ~0.506 ms dense map. Retained tensor payloads were **2,176
versus 6,400 bytes**. This is a storage/latency tradeoff, not a Riccati speed win.
Payload counts exclude coefficient storage, transients and lifecycle costs.
No backend is installed as a production default based on these timings.

All **1,344/1,344** parent search attempts completed, plus **336 exact legacy
replays**. On the next 24 number-multisets, 21 were solvable. With eager terminal
verification and a generated-successor ceiling of 256, the heuristic found
**15/24** proofs and the learned value found **4/24**. At ceiling 1,024 both found
**21/24**, but recorded total times were ~0.036455 s versus ~0.097561 s. The learned
method generated 13,478 successors and 4,853 critic examples versus 8,313 and zero
for the heuristic. The NDU-discount variant also found 21, with no extra solved
tasks. Eager verification reduced some work but did not change success totals
in these comparisons. Same counter ceiling does not mean equal actual compute.

The earlier 20/24 result under a popped-node ceiling is not overwritten. It
answered a different budget question. Existential reachability is an unsuitable
substitute for success of a specified policy within a specified resource budget.
This is a mechanism interpretation, not proof of the unique cause of failure.

## Fixed new question

After a cheap heuristic probe fails, should the remaining budget go to the same
heuristic, to the frozen learned-value search, or should computation stop?

`system2_budget_control.py` supplies a shared **324-parameter** outcome/cost head:
15 observed inputs, 16 hidden units, four outputs. Inputs are the existing exact
arithmetic state/goal features plus total budget, spent fraction and remaining
budget. Outputs estimate proof-success probability and expected successors for
the TWO named frozen continuation policies. These are predictive estimates,
not certified/calibrated probabilities. No pretrained Encoder is instantiated.

Only the original twelve training number-multisets generate training rollouts.
For each total budget 256/1,024, run the frozen heuristic with one quarter of that
budget. Successful probes remain recorded and need no continuation label. After
failure, actually run BOTH fixed tails with the remaining budget and use their
verified success and consumed successors as targets. Failed executions abort
training rather than being converted into negative labels or replacement tasks.
There are at most 24 failed-probe training contexts, not hundreds of independent
samples. All counterfactual training rollouts and costs are retained.

The shared head trains for 200 fixed AdamW steps. A shuffled-row control has the
same inputs, initialization, architecture and update count. It shuffles paired
success/cost targets as a unit. The existing 225-parameter search critic is loaded
from artifact 11724608246 and is NEVER retrained. Both controller heads are saved,
reloaded and frozen before evaluation; all model digests must remain unchanged.

## Declared finite utility, not a general FBSDE reduction

The fixed experimental utility is `verified_proof - 0.0001 * generated_successors`.
After a failed probe, choose the largest of zero (stop) and
`estimated_success(a) - 0.0001 * estimated_tail_successors(a)`.
Probe cost is sunk for this argmax, but IS included in total episode utility.
This is a risk-neutral finite expected-utility specialization with discount one,
one mandatory probe and ONE learned decision. It is not a general optimal stopping
solution or a nonlinear NDU/FBSDE solver. Riccati does not judge arithmetic truth.

The tail RESTARTS from the root; it does not falsely claim to resume a saved queue.
Every repeated generated successor is charged again. A direct full-budget
heuristic and direct full-budget learned search explicitly control for the cost
of this two-stage architecture. Stop returns no proof, never certified impossibility.
The scalar price is fixed for this experiment, not measured wall-time, FLOPs or
real-world task value. Full cost vectors and measured latency remain separate.

## Evaluation and decision boundary

Eight arms: direct heuristic, direct learned search, probe-only stop, fixed
heuristic tail, fixed learned tail, learned controller, shuffled controller and
cost-blind selection using the SAME learned success predictions.
Use 48 previously evaluated number-multisets and the next fixed 48 hash-selected
multisets (catalogue positions 60:108), neither overlapping training. Two budgets
schedule **1,536** predictions. Selection uses identities only, not solvability.
This is not 1,536 independent tasks; intermediate arithmetic states may overlap.

Decision journals are flushed before the chosen tail runs. Proofs and costs are
sealed before post-hoc exhaustive solvability and unchosen-action calibration.
Fixed-tail control results supply evaluation targets for Brier score and cost
MAE; runtime controller functions cannot read those records. Both costs and
success counts must be reported: lower cost from simply giving up is not improved
correctness. Failures retain unknown-utility bounds and incomplete-cost flags.

Primary comparison is the next 48 tasks at budget 1,024. Learned control must not
lose solved tasks and must improve the fixed utility over direct heuristic,
both fixed tails, shuffled control and cost-blind control. No post-result price,
budget, task or arm selection. Even a pass requires independent confirmation.

## Execution boundary

Sixteen new mechanics/full-runner tests are submitted. Local container/Python
probes failed before execution; no local pass, formatter or runtime result is
claimed. The scoped workflow runs the full MemoryCell regression suite and static
checks, then the new trial. Existing workflows and historical tests are unchanged.
No new Encoder/Reader call, production activation, language/multimodal capability,
calibration certificate or NDU superiority is established by code submission.

```sh
HEPTA_MEMORY_TESTED_COMMIT=$(git rev-parse HEAD) \
  python scripts/memory_cell/system2_budget_trial.py \
  /path/to/parent-verified-control.zip /new/budget-return-output
```
