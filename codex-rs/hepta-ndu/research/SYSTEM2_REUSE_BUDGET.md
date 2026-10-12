# System2: exact terminal scheduling and shared finite-horizon preparation

Parent source: `15a9c7cd50d471cd255779401c3555b70588ce28` (PR #1546).
This stage does not change the training objective, pretrained models, native NDU
Rust API, production policy, or the meaning of general recursive utility.

## Completed parent evidence (read from the actual job log)

Run **38198110184**, job **114645228400**, completed successfully at the parent
source. Full MemoryCell regression: **1,098 passed, two skipped, 1,100 total**;
static diagnostics passed. The log reports all nine LQ cases successful, maximum
trajectory difference **2.789435349370706e-15**. Solver-only recorded totals were
**0.016026509 seconds Riccati versus 0.007000992 seconds Hamiltonian**. This tiny
single-state study establishes parity, NOT Riccati acceleration. Different backend
work and unrepeated timings cannot establish a production speed ranking.

The same run completed **336/336** arithmetic-search predictions, zero execution
failures. Twenty of 24 task multisets were solvable. Valid proofs at 64/256 popped
states were: greedy 0/0; breadth-first 0/5; heuristic 14/19; learned value 16/20;
NDU-transformed value 16/20; shuffled labels 5/9; flat NDU 0/5. At budget 256,
learned value took ~0.220970 seconds versus heuristic ~0.046990 seconds over the
24 tasks. It generated 15,428 versus 9,791 successors and evaluated 7,551 critic
examples. Hence more solved tasks under a popped-state ceiling does NOT establish
same-compute efficiency. NDU's affine discount produced no extra successes here.
Four impossible tasks remain in the denominator; search non-discovery is not a
proof of impossibility. These are rational-arithmetic controls, not LLM results.

Parent artifact **11724608246**, 97,121 bytes; external SHA256:
`3838a940e601117070438a6e6f88ffc7c46645c50df5ef0f1ea304ebe91ae0bd`.
Local container/Python services failed in this turn; no local ZIP verification is
claimed. The new hosted run verifies the original archive, source and tensors.

## Search: use known exact terminals rather than asking a learned scorer

The existing `search` gets two explicit optional arguments; default behavior stays
`terminal_policy='deferred', successor_limit=None`. In `eager` mode, every new
terminal expression is checked immediately by the SAME postfix verifier. Valid
proofs return; invalid terminals are discarded without critic evaluation. This is
a scheduling/control ablation, not a new ability to predict arithmetic truth.
All seven arms receive the same terminal rule, including greedy and heuristic.

The existing yielded-successor count, INCLUDING duplicates, now has optional hard
limits 256/1024, with an independent popped ceiling of 8192. A successor generator
can calculate several rational options before yielding; this overhead is timed
but the limit is not advertised as a CPU-instruction bound. Exact verifier calls,
critic examples, popped states and wall time remain separately reported. Partial
batch truncation follows deterministic original successor order. No model scores
or outcome labels choose which generation is charged. On generation exhaustion,
previously generated queued terminals can still be checked; absence of a proof
is never labelled impossibility. Failures remain with incomplete-cost flags.

The runner loads the TWO frozen 225-parameter models from the parent artifact;
there is NO new fitting. First it repeats all 336 default searches and requires
identical proofs, discovery flags and cost counters (time is not compared).
It then registers **1,344 predictions**: 24 reused + 24 next-hash-slice task
multisets, two terminal modes, two successor limits and seven arms. Task selection
uses the original identity hash, not solvability or observed performance. New root
multisets do not imply disjoint intermediate arithmetic states or a new domain.
All predictions are sealed before exhaustive evaluation reachability. Correctness
of any returned proof is checked independently. The declared primary comparison
is next-hash-slice / 1024 / eager: learned versus heuristic and shuffled critics.
No result-dependent support selection, model selection or threshold tuning occurs.

## Numerics: both Riccati AND the reference may reuse preparation

`hamiltonian` now accepts a vector or bounded matrix right-hand side; the original
vector interface remains. Identity RHS columns use ONE factorization to construct
a reusable zero-noise linear state/control map. This prevents unfairly comparing
a shared Riccati cache to a dense solve repeated separately for every Cell.

`riccati_reuse` reuses the existing solver to cache K and P0 with the scalar noise
offset. Both backends validate coefficient CONTENT, dimensions, horizon, costs and
noise, and recheck cache content once per batch. Mutation invalidates reuse. Only
initial states vary within a shared cohort: different task dynamics or terminal
costs require different caches. These are controller-state batches, not new
trained Neuron Cells. Dense maps support zero noise only; Riccati expected values
retain the additive-noise offset, but nominal paths are not stochastic rollouts.

The benchmark fixes seeds 7/19/31, horizons 4/16/32, n=4, m=2 and batch sizes
1/16/256: **27 conditions**, with five cold and seven warm timings, alternating
backend order. Cold includes full preparation plus application; warm includes
coefficient/cache checks and application. Full paths, controls, values and actual
quadratic path costs must agree before timings are accepted. All samples and
failures remain. Tensor payload bytes exclude transient allocations, serialization
and original shared coefficient storage; no lifecycle-memory claim is made.
The objective is measured crossover and amortization, not proving Riccati always
wins. No ordinary Riccati reduction of nonlinear or random-coefficient NDU is implied.

## Execution

Sixteen new tests cover multi-RHS parity, no solver calls on reuse, coefficient and
cache invalidation, noise offsets, exact terminal precedence, oracle separation,
legacy behavior, generation ceilings and task identity. They are SUBMITTED tests,
not claimed local passes. Local `just fmt` was attempted but the runtime service
failed before execution. The existing hosted workflow retains full MemoryCell
regressions, static checks and the original nine-case LQ reference. It replaces
redundant critic refitting with exact saved-model legacy replay plus the new search
matrix; historical raw artifacts remain untouched. Source SHA/tree and failures
are uploaded. Workflow submission is not an execution or speed claim.

```sh
python scripts/memory_cell/system2_search_budget.py parent-verified-control.zip /new/search 
python codex-rs/hepta-ndu/research/riccati_reuse.py /new/shared-lq
```

Set `HEPTA_MEMORY_TESTED_COMMIT` to the actual checkout for the search runner.
Production acceptance, natural-task reasoning emergence, calibrated NDU stopping,
new multimodal capability and independent semantic adjudication remain unestablished.
