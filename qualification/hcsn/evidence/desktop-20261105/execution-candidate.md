# Prepared HCSN execution candidate

This directory is an isolated copy of baseline commit
`28a61d14ea7d4c3b3c515ab57b29c98de22e5673`, prepared for review. It has not
been staged to the GPU host, run as a training matrix, pushed or qualified.
The inherited package README describes historical baseline receipts; those
receipts do not qualify this new source revision.

The copied workflow also includes the root agent's separate artifact-retention
fix: retain the smoke run/weight directory alongside JSON receipts. That
pre-existing local change is recorded in `inherited-workflow.diff` against the
retrieved baseline and is outside the research-package diff. It was not introduced
or altered by this execution-candidate preparation.

Execution remains gated by an actual original full-shape B OOM under the
declared resource profile, the frozen 16-case CPU and CUDA parity receipts,
and a successful separate candidate full-shape CUDA probe. The root agent will
also review this integration and run the strict CPU tests. This preparation
does not assert any of those gates have passed.

## Minimal source changes

| File | Change |
| --- | --- |
| `qualification/hcsn/rematerialization.py` | Exact bytes of the frozen external candidate module; SHA256 `ea0be5db010342050437fc5aa5d0458b8601b744670a4d7e3abd84cfbc52ae38` |
| `qualification/hcsn/execution.py` | Explicit policy validation; implementation description; guarded public CUDA device/cap metadata; terminal energy synchronization; allocated/reserved training peaks |
| `qualification/hcsn/baselines.py` | Optional `population_checkpoint_steps=0`; value 1 selects rematerialization only for the two B variants, with segment length fixed to 1 |
| `qualification/hcsn/benchmark.py` | Pass policy to the factory, record the actual implementation, bind stable CUDA metadata to existing cache keys, enforce finite/missing-gradient guards, close and label observed energy intervals |
| `qualification/hcsn/attempts.py` | Add complete/incomplete/unknown energy-interval counts and counter subtotals while retaining all observed attempt costs and legacy totals |
| `qualification/hcsn/audit_population.py` | Restore and verify the declared implementation during saved-checkpoint replay; retain the original CPU exact-MSE check and CUDA-receipt tolerance unchanged |
| `qualification/hcsn/configs/full-rematerialized.json` | Original full config plus exactly `population_checkpoint_steps: 1` and `cuda_memory_fraction: 0.5` |
| `qualification/hcsn/tests/test_execution.py` | New policy/cache, cap refusal, evidence-scope, candidate checkpoint/replay/resume and numerical-failure contracts |
| `qualification/hcsn/tests/test_cells.py` | Strengthen existing native/CfC backward coverage to reject missing trainable gradients; include B's no-recovery variant |

The original full config bytes, old smoke config, `cells.py`, numerical kernels,
original B class and all old smoke evidence remain unchanged. No checkpoint
math is duplicated in the new tests. The frozen parity checker remains outside
this directory and must be run against its original pinned baseline/module;
changing its pins to accept the integrated source would not replace that check.

## Preserved experiment and changed execution cost

The derived config retains all 170 task/model/seed identities, both tasks,
seeds 0 through 4, split sizes 4096/512/1024, data seed 271828, 400 Adam
updates, batch 64, length 64, hidden width 64, learning rate 0.001, dt 0.1
and 100 measured latency repetitions. The two B variants retain 32 bins.
Validation-only checkpoint selection and the held-out test procedure are unchanged.

The new policy is explicit and uniform across the 20 B identities. There is no
OOM-triggered substitution or per-seed fallback. It retains full BPTT and changes
activation storage and training recomputation. Measured candidate runtime and
physical energy therefore include its extra compute and must be reported as
candidate execution costs. One successful probe or partial matrix never counts
as 170 completed full-budget fits.

The allocator fraction is applied before constructing any benchmark model. A
failure to set it, or a conflicting successful readback, makes every affected
request unavailable with zero submitted training budget; the code never retries
uncapped. Device UUID, driver, compute capability, VRAM size, requested cap and
public-API readback live in stable hardware provenance, which the existing
`receipt_key` includes. Missing optional metadata retains explicit reasons.
Driver lookup uses the CUDA-reported UUID and rejects an unmatched response;
it never guesses from GPU ordinal.

Allocated and reserved peaks are result measurements, not volatile input keys.
They describe the allocator peak since the reset after model/dataset creation
through training/validation. They exclude later test/latency work. A failure
before the current run's reset cannot inherit a previous run's peak. The cap
does not reserve the GPU or limit third-party allocations outside the PyTorch
allocator.

`peak_gpu_interval_complete` can be true only for a completed CUDA training
interval with valid allocated and reserved readbacks. CPU execution records
that flag as null and `peak_gpu_measurement_status: not_applicable_cpu`.
Missing CUDA readings have status `unavailable` and an explicit reason.
Null peak values are never GPU memory measurements, even when CPU training
or an energy interval completed successfully.

## Gradient and energy contracts

Static review of `cells.py` confirms the intentionally inactive whole parameters
are already frozen: `hx_fixed` freezes `boundary_input`, `no_recovery` freezes
its two recovery parameters, and `softplus` freezes `raw_financial`. Call/risk
ablations use portions of parameter tensors; zero gradient elements are valid.
The new guard rejects only a missing gradient on a parameter whose
`requires_grad` is true, or a nonfinite existing gradient. It adds no exemptions
for individual models. The strengthened existing tests must verify the actual
runtime; the local host currently has no Torch.

The pre-clip norm and updated parameters must also be finite. An Adam update
that completed before a nonfinite-parameter check fails remains counted as an
executed optimizer step. An invalid clip norm fails before the update. All
submitted examples/tokens and immutable failure attempts remain visible.

Before the terminal physical-counter reading, CUDA synchronization is attempted
even on a failed training operation. Counter readings from an incomplete
interval remain marked `interval_complete: false`; they are not a complete
training-energy result. A complete observed interval on a failed fit measures
that partial attempt, not the unexecuted remainder of 400 updates. Missing
counters stay null. A final CUDA synchronization also covers failures outside
the training meter's lifetime, without extending that meter's stated scope.

Aggregation keeps the original any-reading count and available-cost total, then
adds measured-attempt counts and counter subtotals for complete, incomplete and
unknown intervals. Only literal boolean `interval_complete` values establish
the first two categories. Legacy receipts and missing/nonboolean flags remain
unknown, with their real readings retained. An interval marked complete with
no physical reading is still a missing-energy attempt. Categories include only
the counters actually observed; no missing counter or attempt is zero-filled.

## Validation prepared and performed

The existing canonical `checks` entry point discovers **104 test methods** in
this candidate. On the local host without Torch, the available tests recorded
47 passed, 0 failed, 0 errors and 57 explicitly skipped, status `partial`.
The exact-source preparation receipts are under `preparation-checks/`; use the
latest receipt named by `EXECUTION-CANDIDATE.json`. This is not a strict tensor
pass, CPU parity, CUDA parity or CUDA memory result.

Six new non-Torch contract tests cover policy/cache separation, UUID-bound
metadata and explicit missing facts, refusing an unapplied cap before any
training call, synchronization before an incomplete terminal energy reading,
avoiding stale allocator peaks, and mixed complete/incomplete/legacy cost
aggregation. Three new Torch tests are prepared for
candidate factory initialization/RNG identity and checkpoint replay/resume,
missing versus intentionally frozen parameters, and failure accounting around
clip/Adam. The existing strict suite supplies independent kernel and gradient
checks; the frozen external 16-case checker supplies rematerialization parity.

After root review, strict CPU verification uses the existing command from this
directory:

```sh
python -m qualification.hcsn.checks --require-torch \
  --output preparation-checks/strict-cpu-review.json
```

Do not start the full derived config before the separate original-OOM,
CPU/CUDA-parity and candidate-full-shape receipts satisfy the declared gates.
Keep the entire source tree, tests and runtime frozen during a matrix. Existing
source-change quarantine, immutable attempts, completed-weight verification,
170-identity accounting and unknown interrupted budgets remain in force.

## Public API references used in the implementation review

- [PyTorch 2.8 process allocator fraction readback](https://docs.pytorch.org/docs/2.8/generated/torch.cuda.memory.get_per_process_memory_fraction.html)
- [Official CfC cell source](https://ncps.readthedocs.io/en/latest/_modules/ncps/torch/cfc_cell.html)
- [Official Mamba-2 module source](https://github.com/state-spaces/mamba/blob/main/mamba_ssm/modules/mamba2.py)

The optional-model source inspection is contextual. The actual installed
versions and their real gradients still require the recorded runtime tests.
