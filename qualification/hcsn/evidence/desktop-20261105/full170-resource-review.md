# Full-budget resource and rematerialization integration review

This is a static review of the frozen HCSN baseline at commit
`28a61d14ea7d4c3b3c515ab57b29c98de22e5673`. It is not a CUDA execution,
parity result, trained-weight qualification, runtime estimate, or permission to
replace the original implementation automatically. No baseline file was changed.

## Decision

Keep the original full-shape B probe first. Use the separately frozen
rematerialization candidate only after an actual original B out-of-memory
receipt under the declared resource profile and the fixed CPU/CUDA parity
checks pass. The candidate full-shape probe is now prepared outside the package;
it has not been run on CUDA. Its six non-Torch provenance and create-only
negative checks passed.

If these gates justify integration, make one new, identifiable source revision
and an explicit execution-policy config before starting the matrix. Preserve all
170 original task/model/seed identities, all data splits, 400 updates, batch 64,
length 64, hidden width 64, and B's 32 bins/dt 0.1. Segment length 1 is fixed in
the prepared candidate probe. This preserves the data and gradient horizon; it
adds recomputation and therefore is a different computational implementation
whose measured cost must be reported separately.

The original auditor has no demonstrated unconditional GPU/CPU exact-equality
bug: `audit_population.py:108-114` requires exact receipt MSE only for CPU
receipts and uses `torch.testing.assert_close` for other recorded devices. Do
not change this branch without an actual failure to investigate. The refined
grids have a genuine static memory and runtime burden, for which a later
external diagnostic can stream inference samples while retaining all data.

## Frozen identities

| Item | Fixed value |
| --- | --- |
| Full matrix | 17 models × 2 tasks × 5 seeds = 170 |
| B subset | 2 population-flux variants × 2 tasks × 5 seeds = 20 |
| Train / validation / test counts | 4096 / 512 / 1024 |
| Data seed | 271828, with original split offsets |
| Training | 400 Adam updates, batch 64, learning rate 0.001 |
| Sequence / hidden width | 64 / 64 |
| B training discretization | 32 bins, dt 0.1, effective refractory duration 0.3 |
| Per-fit submitted training examples / tokens | 25,600 / 1,638,400 |
| Full config SHA256 | `7fa3d05b8c04a918043afdfa1c266a17beccb814351258d0555a753baf13777a` |
| Canonical baseline source-map SHA256 | `13860b933a93966e880e64840efa0ac26b70ab62cbe7e38bf71587575d9831a3` |

The source-map digest uses sorted package-relative keys and compact JSON over
the SHA256 values of all recursive Python files, including tests. It is distinct
from `benchmark.py`'s concatenated source digest. The companion
`FULL170-STATIC-COUNTS.json` records both the derivations and source hashes.

## Workload and memory

### Exactly 550 forward calls per completed fit

`benchmark.py:211-327` performs the following under the full config:

| Forward purpose | Full-shape batch forward calls |
| --- | ---: |
| Training | 400 |
| Validation every 100 updates: 4 × 512/64 | 32 |
| Test: 1024/64 | 16 |
| Latency: 2 warmups + 100 measured repetitions | 102 |
| Total | **550** |

There are also 400 backward calls and 400 Adam updates. Validation, test and
latency run without gradients. All 20 B fits therefore perform 11,000 forward
calls before accounting for checkpoint recomputation or a separate grid audit.

For the frozen eager `population_torch.py:34-90`, each time step computes two
Gaussian interval matrices. Each `_log_interval` eagerly evaluates four
`log_ndtr` calls, including the two subsequently unselected open-interval
branches; these finite inactive branches are intentional numerical safeguards.
Thus there are eight matrix-shaped `log_ndtr` calls and three vector-shaped
ones per step.

At batch B=64, width H=64, bins N=32 and time T=64, a full forward evaluates

`8 × B × H × N² × T + 3 × B × H × N × T = 2,172,649,472`

scalar `log_ndtr` arguments. This is an operation count, not a GPU FLOP count
or an elapsed-time prediction. Across the original 20 B fits it is about
23.9 trillion forward scalar evaluations. A rough full-forward replay count
for non-reentrant checkpoint training adds up to another 400 forward
equivalents per fit, giving about 41.3 trillion across the 20 B fits; actual
checkpoint early stopping and backward work must be measured. Neither number
includes all other arithmetic, autograd work, optimizer work or diagnostics.

One `[64,64,32,32]` FP32 matrix is 16 MiB. There are many matrix temporaries
within a step, and uncheckpointed training retains autograd intermediates
across 64 steps. The model has only 4,353 parameters including its readout;
parameters and Adam state are not the dominant memory requirement. Static
analysis alone does not prove the exact CUDA peak or establish OOM.

The candidate's explicit segment boundary state is about 608 KiB at this shape
(active mass, refractory queue, recovery, escaped mass and filtered trace), or
about 38 MiB for 64 boundaries, before output tensors, checkpoint machinery and
the current segment's graph. This explains why segment length 1 is a plausible
memory reduction; it is not a measured peak-memory result or a guarantee of fit.

### Derive runtime only after actual full-shape timing

Use measured synchronized `forward`, `backward`, gradient validation/clip and
`optimizer_step` stage times from the correct original or candidate probe.
Record the one-step probe's instrumentation overhead separately from the full
benchmark. Then refine with actual training and no-gradient evaluation times.
A useful accounting expression per fit is

`400 × measured_train_step + 150 × measured_eval_batch + construction/I/O`.

It is still an estimate because trained states, validation, allocator behavior,
compilation and thermal/resource conditions can change throughput. Use neither
small CPU smoke timing nor advertised GPU FLOPS as an ETA. Do not alter batch,
steps, splits, model selection or the matrix to make an estimated duration fit.

## Smallest source-identifiable integration, if justified

The following is a proposal only. No implementation in this section was applied.

1. Copy the frozen `rematerialization.py` verbatim into a new isolated source
   revision. Preserve `PopulationFluxEncoder` unchanged as the original
   implementation. Its state dictionary remains compatible with the candidate.
2. Add an explicit optional factory keyword such as
   `population_checkpoint_steps=0` to `baselines.make_encoder`. Only the two
   B names select the candidate when the declared value is 1. Use a local import
   in that branch because the candidate subclasses the original encoder. Do not
   catch OOM and silently switch an individual seed to another implementation.
3. Create a derived full execution config with the original matrix, data and
   optimization budget unchanged, plus the declared execution policy. Leave the
   original `configs/full.json` bytes unchanged. Validate the policy and pass it
   through `benchmark._run_one` and the saved-weight audit constructor. Record
   the concrete encoder class, checkpoint segment length and full-BPTT policy
   in each result, as well as the separate scope of recomputation cost.
4. Freeze the entire source tree and runtime before the first matrix attempt.
   Existing `receipt_key` binds the whole config, source, hardware, software and
   split hashes, so this revision naturally gets new identities. Do not import
   or relabel an old-source completed cache as a new-source completed fit.
5. Preserve original OOM and any interrupted receipts with their source and
   resource profile. They are historical attempts, not extra successful seeds,
   and do not change the final 170-identity denominator. Select the execution
   policy for all 20 B identities before observing their task outcomes.

The new revision can also adopt the narrow, already reviewed preflight guards:
reject missing trainable gradients; reject a nonfinite pre-clip norm or updated
parameter; synchronize CUDA best-effort before closing a failed energy interval
and mark incomplete intervals explicitly. Current `benchmark.py:273-279`
checks only gradients that exist and does not inspect the returned clip norm.
Current failure cleanup at `benchmark.py:339-341` stops the meter without that
terminal synchronization. These are real evidence-quality gaps, but are not
evidence that any completed baseline smoke fit had missing/invalid gradients.

Bind the actual device UUID, driver and allocator resource policy to the new
execution identity if a memory cap is used. The existing report records device
name, CUDA runtime and other environment details, but not those three facts.
An allocator cap is a PyTorch-process bound, not a reservation of the device
or a bound on all external CUDA allocations.

## Journal, resume and measurement implications

`attempts.py:32-59` publishes a durable start, stages weights, verifies source,
then publishes an immutable terminal outcome and promotes or quarantines the
weights. `benchmark.py:411-449` reuses a completed result only if it matches the
immutable terminal receipt and its weight hash. Preserve these properties.

There is no optimizer/RNG step checkpoint. A genuine interrupted fit restarts
all 400 updates as a new attempt. The prior started-without-terminal attempt
remains interrupted with unknown budget/energy, never zero. Failed and
unavailable attempts are also retried by the current driver on a new invocation.

Run one owner for a given output/matrix. Unique attempt IDs do not create a
per-key execution lock; concurrent invocations can both spend the same training
budget. A remote tool timeout is not proof the process died. Reconcile its PID,
active journal and terminal receipt before any resume.

The aggregate report is written only after the matrix loop finishes; immutable
attempts are the durable intermediate evidence. A zero CLI exit is insufficient
to assert 170/170 because the driver can return zero with completed and
unavailable records together. Check every original identity and explicit
`accounting.completed/failed/unavailable` fields.

The existing training wall/energy scope includes training plus validation.
Construction and initial data transfer precede this interval; checkpoint I/O,
test and latency measurements follow it. Peak allocated bytes are read after
training/validation and before test/latency. Preserve these labels; do not call
them complete end-to-end cost. Candidate recomputation is inside the training
interval and must be included in measured candidate cost. Missing physical
counters remain missing, and device/package counters are not process-attributed.

## Refined-grid audit: later external streaming option

The original CPU smoke auditor remains unchanged. Its factor-one replay uses
the actual loaded population buffers and checks trace/prediction bitwise against
the encoder forward. It validates checkpoint identity, budget, validation
selection, discretization and held-out split. Keep those checks and the original
20 expected B identities in any future full audit.

Joint refinement factor F multiplies bins by F and substeps by F, so dominant
matrix work scales as F³. At factor 4 a `[64,64,128,128]` FP32 matrix is 256 MiB
before other temporary matrices. The no-grad path avoids the whole-sequence
backward graph, but does not eliminate these per-step temporaries.

For a later external diagnostic, predeclare a smaller diagnostic batch only for
refined grids, e.g. 8 samples, lowering that single matrix to 32 MiB. A separate
resource profile with batch 4 would lower it to 16 MiB if actual measurements
require it. Do not change original training batch 64, or the trained-grid replay
batch/accumulation order. Record actual device and diagnostic batch for every
grid; never silently adapt them based on MSE or output sensitivity.

Retain all 1,024 test examples in their original order. To retain the original
MSE reduction grouping, assemble the refined predictions back into blocks of
64 before applying the original sum-and-accumulate order. Microbatching can
still change floating-point GEMM behavior, so describe it as part of the
diagnostic implementation and check its numerical effect separately. Do not
claim bitwise identity without an actual comparison or introduce a post-hoc
pass threshold.

Hidden traces sampled at the original 64 input times have only
`1024×64×64` FP32 elements (16 MiB) per grid. Keeping the trained-grid trace and
one refined trace on CPU, or streaming paired reductions, avoids retaining all
refinements on GPU. Final predictions, original-grid hidden RMS, adjacent-grid
RMS, MSE, mass error and escape remain available without omitting samples.

Streaming decreases peak memory, not the total numerical workload. The original
1/2/4 audit across all 20 B checkpoints comprises 23,360 baseline-size forward
equivalents for its grid trace loops alone under the leading F³ term. It also
performs one actual factor-one encoder replay per original batch, adding 320
baseline forwards for the exact trace check. An external separable-grid audit
is an additional workload. Measure its stages independently; do not hide this
cost inside a claim that the 170-run training matrix is complete.

## Focused validation and real stop conditions

Run the existing strict test entry point with Torch available. Its canonical
discovery namespace matters because tests patch `hcsn.*` paths. Particularly
relevant existing tests are:

- `test_benchmark.py`: completed resume with exact budget; copied checkpoint
  rebinding; source-change quarantine; failed-retry accounting; interrupted
  unknown budget/energy; trained-grid refractory replay; physical-counter wrap;
  unavailable versus failed accounting.
- `test_audit_population.py`: saved-weight/buffer/split/original-MSE replay;
  copied verified weights; full empty audit retaining 20 identities and nonzero
  exit; partial coverage; tampered identity/config/split/grid/selection rejection.
- `test_population_torch.py`: finite tail backward and mass; FP64 NumPy parity;
  finite-difference drift gradients; finite FP32 BPTT.
- The frozen 16-case rematerialization checker: both recovery modes, FP32/FP64,
  segment 1/4 and inputs with/without gradients; trajectory/prediction/loss,
  parameter/input gradients, clip norm, one Adam update/moments and post-step
  evaluation. CPU and CUDA runs remain required evidence, not implied by the
  non-Torch provenance checks.

If integration proceeds, add only tests for new contracts: execution-policy
changes bind cache/replay identity; compatible candidate weights replay using
the declared class; missing trainable gradients and incomplete failure energy
cannot masquerade as valid completion. Reuse the existing parity checker for
mathematics rather than writing a second copy of the implementation.

Stop the affected operation and retain evidence on source/config/weight drift,
wrong registered shape/device/dtype, missing/nonfinite gradients, nonfinite
loss/norm/parameters, CUDA failure, OOM under the declared cap, or inability to
publish its durable receipt. A parity failure blocks candidate integration; an
actual candidate OOM does not authorize smaller training batches. A tool timeout
or an unknown process state requires reconciliation before retry, not a duplicate
launch. If optional Mamba-2/CfC cannot run, record the actual unavailable/failed
identities and continue independent authorized work; full 170 qualification stays
open. Missing GPU energy counters leave the energy blocker open but do not erase
a valid mathematical CUDA result. None of these conditions allows dropping an
identity or assigning a missing measurement zero.

## Prepared candidate-only probe

- Script: `cuda-preflight/probe-rematerialized.py`
- Script SHA256: `f8a2b7c193d2750cafb95446eff314195ca54ebb0305c008a35336f6bd874e08`
- Original v2 SHA256, unchanged:
  `70331f392c9695e0522da52817b3511b544304a6f4e23a169a016a07ea9f1285`
- Static diff: `cuda-preflight/rematerialized-probe.diff`
- Non-Torch negative evidence: `numeric-audit/remat-preflight-negatives/RESULT.json`
- Candidate module, manifest and checker hashes are fixed in the probe and
  verified before importing Torch and again at completion.

The probe records candidate-only scope, encoder class, segment length 1, actual
FP32 input shape, fixed first-batch hashes/indices, synchronized stage times,
actual CUDA hardware, allocator peaks, physical-counter availability and
terminal interval completion. It constructs no simultaneous original full-shape
model. One completed step never counts toward the 170 full-budget fits. The
probe records the external OOM/parity prerequisites but does not independently
certify them; the orchestrator must verify their receipts before launch.
