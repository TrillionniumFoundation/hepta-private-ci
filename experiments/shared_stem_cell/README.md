# Shared Stem / Neuron Cell experiment suite

This directory is the experiment control plane for the six experiments in the
shared-Encoder + Cell-specific gated Head proposal. It is research-only:
`production_accepted` is false for every emitted receipt and no runner may
select, activate, promote, or release a model, topology, or executable.

The suite tests whether one frozen Stem plus small Cell adapters can deliver
better utility per active resource than replicating complete models. It does
not infer equivalence to a 10T or 100T parameter model from parameter count.
Conditional routing, external memory, distillation, and specialist decoders
can match a bounded task distribution, but general capability equivalence must
be established by independent held-out evaluations and is not assumed.

## Experiments

1. `scripts/memory_cell/stem_selection_experiment.py` compares small, medium,
   421M and replicated-421M arms under a common budget.
2. `scripts/memory_cell/reader_four_arm_diagnostic.py` evaluates no evidence,
   ordinary retrieval, sufficient verified evidence, and deleted-premise arms.
3. `experiments/shared_stem_multimodal_system2/multimodal_ndu_runner.py`
   summarizes modality-pair results and the five System-2 ablations.
4. The same runner rejects an internal NDU score when external task outcomes
   or resource measurements are missing.
5. `codex-hepta-plasticity` exposes proposal-only Cell split candidates with
   state migration and retained-task gates.
6. `codex-hepta-compiled-use` exposes a fixed five-action ABI, a bounded ring
   queue and a deny-by-default sandbox interface. It never executes arbitrary
   bytes or writes executable memory.
7. `experiments/shared_stem_head_matrix/runner.py` compares linear, gated,
   LoRA and sparse-expert Cell Heads under one frozen Stem and active workload.

## Required reporting

Every arm must bind exact source/model/preprocessor/Head digests, dataset split,
host profile and measurement interval. Report task utility, active FLOPs,
latency p50/p95/p99, resident memory, peak memory, negative transfer, new-Cell
incremental cost, calibration/OOD, old-task retention and rollback status.
Missing measurements produce `insufficient_evidence`, not zero.

The canonical decision rule remains conservative: a candidate is retained only
when its independent lower confidence bound exceeds the baseline upper
confidence bound in the declared direction and all hard floors pass. Internal
NDU utility is diagnostic; it cannot substitute for task success.

## Suggested order

Run the reader diagnostic before tuning retrieval or Heads. Then select a Stem
with the four-arm resource/utility comparison, establish unimodal baselines,
add modality adapters and specialist decoders, run NDU ablations, and only then
generate offline split proposals. The compiled-use pilot is last and must use
typed actions, capability checks, signatures, W^X, resource budgets and
rollback; the slow MCP/tool path remains the authorization/control path.
