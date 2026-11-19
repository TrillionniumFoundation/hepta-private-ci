# Registered CPU implementation scale diagnostic

The 30 configurations in `SCALING001_PROTOCOL.json` are **registered, not yet executed**. Registration was permitted after 30 constructor/count checks and exactly one small synthetic preflight. The full suite is blocked until the main 176-run study and the LIF supplement have both finished and passed their independent integrity analyses.

This panel measures this CPU implementation's behavior with random initial weights, a shared random input sequence, and random class labels. Four small Adam updates per formal case are computational probes, not content training. No dataset, trained checkpoint, content accuracy, GPU, energy, foundation-model throughput, or equal-quality claim enters this diagnostic.

## Frozen configuration panel

The three models are `distribution_free_dual`, `two_gates`, and `transformer`. All use batch1, input64, output10 and float32 CPU execution with one Torch/BLAS thread.

- Eighteen cases hold width32/depth1 fixed and vary sequence length across 16, 32, 64, 128, 256 and 512.
- Twelve additional cases hold length64 fixed and use width/depth pairs (32,2), (32,4), (64,1) and (64,2).

Each case uses a new Python process. The order is fixed in the protocol, with the three models evaluated for each dimension setting. Input seed743001 generates one master sequence of length512; each shorter sequence is its prefix. Identical inputs and labels are used across models and widths/depths. Initial model seed743002 is fixed. Actual input arrays and initial parameter arrays are saved with array-level and file-level SHA bindings.

### Constructor counts observed before registration

These are actual total trainable parameter counts, including frontend, backbone and readout. A baseline's internal hidden width is chosen by the existing frozen factory. It can differ from the public width passed to that factory. No new parameter padding or enforced 3% acceptance gate is introduced by this experiment.

| Public width | Depth | Distribution total | Two-gate total | Transformer total | Two-gate internal width | Transformer internal width |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 32 | 1 | 20,474 | 20,308 | 20,930 | 49 | 36 |
| 32 | 2 | 38,410 | 38,710 | 38,793 | 52 | 37 |
| 32 | 4 | 74,282 | 74,067 | 72,611 | 53 | 37 |
| 64 | 1 | 55,226 | 55,188 | 55,280 | 81 | 59 |
| 64 | 2 | 105,386 | 105,492 | 105,034 | 86 | 64 |

All constructor configurations and component counts are copied into the frozen protocol. Every formal worker rechecks its actual counts and complete model configuration against those records. The selected inference/training behavior comes from the unmodified factory exported by `runtime_eval.py`, backed by the unmodified `model.py` and numerical kernel.

## Measurement contract

Every formal worker performs, in order:

1. One complete inference forward warmup.
2. One complete Adam update warmup.
3. Three measured full-sequence inference forwards.
4. Three measured complete Adam updates.

Every forward starts from a fresh sequence state. The optimizer and parameters persist within the worker, so Adam's state is initialized by the warmup. Each optimizer timing includes zeroing gradients, forward, mean cross-entropy on every random-label position, backward, gradient finiteness checks, clipping at norm2, Adam step at learning rate0.001, and finiteness checks on updated parameters and Adam state. A successful case must demonstrate parameter changes and exactly four completed Adam steps.

CPU and wall times are saved for every warmup and measured operation. Inference checks its complete output shape and finiteness. The extra gradient/parameter/optimizer finite checks are explicit in this new timing contract; the new 30-point panel should not silently mix older runtime-body measurements as though their audit overhead were identical.

`resource.getrusage` RSS snapshots are cumulative process high-water marks. They are not isolated activation allocations. The primary peak-RSS measurement is the full worker's Linux `wait4` receipt. Complete worker CPU additionally covers interpreter/import cost, the frozen factory's hidden-width search, input and initial-weight serialization, warmups, post-measurement checks, result writing and exit. Body timings are nested inside that full cost and must not be added again.

Each worker has a 300-CPU-second soft resource limit, a 305-second hard CPU limit, and a 600-second wall watchdog. A failed, killed or timed-out worker retains all available partial measurements, log, identity evidence and an explicit failure receipt. The scheduler continues through all registered configurations. `COMPLETE.status=completed` means all30 configurations were attempted and recorded; `successful_cases`, `failed_cases` and `all_cases_successful` separately describe outcomes.

The report contains all30 rows and measured CPU ratios across T at fixed width32/depth1. The three repeats are descriptive; no asymptotic exponent is fitted and no unmeasured model size is extrapolated.

## Preflight evidence and cost

`results/scaling_preflight001` contains the completed constructor checks and one `distribution_free_dual_b1_t16_w32_d1` probe. This preflight used one forward/optimizer warmup and one measured forward/optimizer pair. It therefore completed two Adam steps; 26 state tensors changed and all finite checks passed.

Its complete independent child cost was **5.715105 CPU seconds**, including imports and all constructor checks. The separate preparation supervisor used **0.096268076 CPU seconds** through registration. Those two scopes sum to **5.811373076 CPU seconds observed lower bound** for this preparation. They do not include the future formal suite. The inner small-case timers are nested.

At registration, `results/scaling001/cases` and `RUN_AUTHORIZATION.json` did not exist. No formal scaling case had started.

## Execution and completion gates

From the checkout root, use the already verified CPU runtime environment:

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/workspace/scratch/58af017d4789/torch_runtime \
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
python -m experiments.hcsn_distributional_v2.scaling_eval run \
  --protocol experiments/hcsn_distributional_v2/SCALING001_PROTOCOL.json \
  --output experiments/hcsn_distributional_v2/results/scaling001 \
  --run-after audited-main-and-lif
```

Use a locally installed environment matching `requirements-cpu.txt` when moving the checkout; the historical scratch dependency path is not a portable requirement.

The run verifies the following completion/audit metadata before it creates an authorization record or starts a worker:

- Main study: successful complete176 coverage and a successful full scheduler receipt.
- Main independent analysis: expected176, valid176, invalid0, successful analyzer receipt.
- LIF study: successful complete18 coverage.
- LIF independent analysis: status passed, expected18, valid18.
- Final normalized LIF cost-receipt map: completed, which is produced only after its analysis process has exited.

Only these prerequisite metadata fields and receipt hashes are consumed. Content scores and predictions are not used. Every worker rechecks the same gate identities and frozen dependency hashes. The CLI refuses to replace an existing authorization or rerun a study directory.

A new independent replication requires new protocol, preflight and output paths:

```bash
python -m experiments.hcsn_distributional_v2.scaling_eval prepare \
  --protocol experiments/hcsn_distributional_v2/SCALING_NEW_PROTOCOL.json \
  --output experiments/hcsn_distributional_v2/results/scaling_NEW \
  --preflight-output experiments/hcsn_distributional_v2/results/scaling_preflight_NEW
```

This `prepare` command does not run the30-point suite. Its protocol retains the fixed study001 design, with a new identity/hash and explicit new output locations.

## Output and cost interfaces

`results/scaling001/COMPLETE.json` has schema `hcsn-v2-scaling-complete.v1`, `expected_cases=completed_cases=30` when the suite finishes, the30 original `records`, success/failure counts, protocol/source bindings, nested complete worker CPU, and report/summary hashes. Each case ID is `<model>_b1_t<T>_w<W>_d<D>`.

Every `cases/<case_id>/` directory contains `IDENTITY.json`, `EXECUTION.json`, and a successful `RESULT.json` or explicit `FAILURE.json`. Successful workers also retain inputs, initial weights and every measured operation. A process dying before identity creation is labelled `failed_before_identity` with `actual_counts=null`, rather than inventing a measurement.

The independent outer `SUITE_EXECUTION.json` records `/complete_child_cpu_seconds` for the whole scheduler/report/worker tree. Its `/supervisor_self_cpu_seconds_through_cutoff` is separate. All per-worker, coordinator-body and warmup/measurement timers are contained in the full suite child. Final cost accounting should add only the complete outer child and separate supervisor, plus the separate preparation scopes above.

Final auxiliary evidence and archive closure must include the protocol, source snapshots and entire formal suite. Closure checks30 exact registered IDs and preserves resource failures as negative evidence; it does not turn them into successful measurements.

Frozen scaling source SHA-256: `be79c27898c56e557b3b58ee9858d116dbfd61998129a5f1e2ab84f0115db6fa`.

Frozen protocol SHA-256: `287c56ae904ec5c4cabe6e5ee309d6a22b8f4648e9b1890ed650af2b0fbc1fa3`.
