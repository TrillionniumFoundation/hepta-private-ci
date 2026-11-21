# WSP evidence and next admissible comparison

Research checked on 2026-11-21. The existing `ProgrammaticEdit` remains a
residual-correlation coordinate baseline. It is not renamed as a discovered
weight program. A successful operator benchmark does not close the independent
question of replacing representation learning with WSP.

## What the current primary sources establish

| Source | Implication for Hepta |
| --- | --- |
| [Takehi et al., Sparks of Weight-Space Programming](https://rikiyat.github.io/blog/weight-space-programming/), Nov 2; response Nov 12 | The authors describe WSP as a capability/concept, not a single optimization algorithm. The programmer reasons about existing weights or task semantics and chooses the edit. Their no-gradient experiments do not establish universal pretraining replacement. |
| [Hu et al., Exploring WSP](https://arxiv.org/abs/2611.09382), Nov 6 | Across 16 trajectories and seven benchmarks, the authors report uneven transfer and six trajectories that retained the original weights. NoUpdate must remain a valid outcome; development success is insufficient. |
| [Li et al., WeightCode](https://arxiv.org/html/2611.25476v1), Nov 19 | Programs construct task-specific computations from weights, activations and task knowledge. Discovery uses bounded LLM sessions and external selection/retention checks. Rerunning a reusable program on a new network is a separate operation from discovering it. |
| [Training Vision Models for LLM-Driven WSP](https://arxiv.org/html/2611.26408v1), Nov 19 | Edit-ready training differentiates through simulated closed-form edits and trains the original network with additional losses. Easier subsequent edits do not remove its prior BP cost. |

These are recent primary research reports, not evidence that a general multimodal
HCSN encoder can already be trained without BP. WeightCode reports discovery
sessions taking roughly 30–130 minutes (some task limits longer), with US$5–13
API cost for several task families; rerunning an existing program takes minutes
without new LLM calls. Its numerical figures are paper-specific and are not a
price or speed forecast for Hepta. Its protocol selects at most eight labeled
candidate edits per single round, applies retention checks and separately counts
additional label-scored work. A label-driven residual coordinate optimizer does
not reproduce that discovery protocol.

## Concrete required protocol for Hepta

1. Freeze a new task, editable parameter mask, base checkpoint and train/dev/
   independently sealed final splits. The prior final set is already consumed.
2. Give the programmer only the task specification, source, existing weights,
   permitted training examples and bounded development feedback. Preserve the
   entire prompt/program/check sequence, including failed proposals and NoUpdate.
3. Save the exact executable weight program and its candidate artifacts; a finite
   update vector alone cannot establish reusable program transfer. Validate
   feature/rate/retention constraints before native candidate admission.
4. Compare the actual program with BP, ridge on frozen features, residual edits
   and no update under the same editable mask. Match data access and explicit
   forward/evaluation budgets; report work counts as well as wall time.
5. Charge LLM discovery requests/tokens/time, local inspections and all checks.
   Report initial discovery separately from per-model rerun. If billing metadata
   is unavailable, mark it unknown rather than zero. Amortized cost is
   `discovery_cost / number_of_deployments + rerun_cost`; savings require enough
   independently validated reuses to repay the discovery cost.
6. Freeze every chosen candidate before a single final evaluation, including
   independent retention tasks. Keep all unsuccessful runs in the result set.

No new external LLM discovery session, task experiment or program-transfer run
is performed by this patch. The current assistant's literature/code analysis
has no measured API bill and must not be represented as zero-cost discovery.
There is no basis yet for closing the WSP-over-BP training advantage claim.
