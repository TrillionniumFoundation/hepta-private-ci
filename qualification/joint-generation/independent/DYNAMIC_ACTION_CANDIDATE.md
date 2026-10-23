# Separate candidate: control generated content at a fixed step count

This is a research candidate, not an implementation, frozen experiment, result,
or change to r2/CORE. The current codec TRAIN comparison stays as specified.
Dynamic benefit over an effective best static NDU system is now an explicit
research goal; no result or scientific guarantee is supplied here.

Before fitting another early-exit critic, estimate headroom from the current
candidate's TRAIN outputs. If g is decoded full-minus-low raw utility and c is
the actual marginal continuation cost in the same units, the oracle can choose
the sign of g-c. Its value must still pay mandatory low/critic work, paired-label
and policy training, and any content-training opportunity loss against the best
static model. Label-aware oracle selection is an upper bound, not a deployable
policy. Existing OOF results assess what already obtained features predict.
An oracle from different weights or a different codec/cost profile is not an
upper bound for the current model. Missing static-model TRAIN outputs must be
reported rather than supplied from validation or a sealed test.

If that analysis supports changing the mechanism, consider a fixed total number
of generation steps with one shared initial joint step. Later actions choose
`text-refine`, `image-refine`, or `joint-refine`. An action must update the model's
generatable content state (for example shared hidden state and content logits),
using available input/generated feedback. Merely changing a route label cannot
establish content control. Initially exclude early stopping so that information
and content feedback can be studied without the existing stopping-tail mixture.

For a small prospectively fixed horizon, enumerate every fixed action sequence
on the same backbone. Select the strongest static NDU sequence using development
data and charge its enumeration/selection cost. Give that system all budget
savings from omitting a policy, including useful content updates. Charge the
dynamic system for all action branches, policy/conditional-value training,
branch-label acquisition, search and inference. Equal step counts do not imply
equal FLOPs, CPU or complete budgets; use actual inventories and CPU boundaries.

The first test of this candidate is TRAIN-only action crossing: determine whether
the preferred action or sequence varies across inputs, its oracle improvement
over the best fixed sequence, and how much of that improvement is predictable
from information already available at the decision. Keep source-group OOF splits,
every seed, rare costly mistakes and all measured costs. If the upper bound does
not pay the complete overhead/opportunity loss, do not fit a larger policy to
hide that limitation. A nested low-to-residual computation that reuses acquired
state is another candidate; it must demonstrate actual reuse and new information.

Fixed-rho entropic utility can have a tower/Bellman representation under the
appropriate conditional-expectation and additive-cost setup. The relevant design
question is whether actions control content state and conditional continuation
value; the choice of exponential utility alone does not rule out recursion.
Detailed paper references and implementation choices remain to be reviewed.

Keep all original tasks, baselines, denominators, caps, failures and sealed tests.
Any architecture study needs a separate recorded development protocol. Any new
formal confirmation additionally needs independent evidence, the full prior
selection history, prospective error control across confirmations and preopening
review. No official test or AV extension is authorized by this document.

## Parent-reported dot implementation probes

These are reports from the parent session's separate dot analysis, not executions
or verified performance results from this Codex Cloud environment. They contain
no trained-model utility, model-benefit comparison or formal evidence.

- NumPy nested computation at batch 64 and reported `q=0.6496` took 4.883 us,
  versus 4.394 us for the old path and 0.976 us for static computation, under the
  parent's timing convention. This was a negative timing result.
- A fused C probe passed 1536 numerical-equivalence cases, with maximum
  probability discrepancy <=1.95e-16. Measured blocks exceeded 0.10 CPU seconds.
  Reported timings were 2.484 us for fused execution, 2.657 us for a fair fresh
  computation, 2.109 us for optimized C static and 1.281 us for BLAS static.
  The roughly 6% improvement over fresh computation still left fused execution
  roughly 21% slower than optimized C static. Equivalence and that local saving
  do not establish an advantage over the effective static baseline.

The parent's T11 break-even calculation required 9.682 us of service saving
under the old weights and cost assumptions. This is a conditional historical
value, not an achieved saving, a new qualification threshold, or a prediction
for different weights, codec preparation, training allocation or service costs.
None of these probes establishes feasibility under the unchanged 10 s/12B
complete budgets or justifies a new test opening. A cloud implementation would
still need its own source review, complete cost accounting and predeclared
TRAIN-only evidence before any scientific claim.
