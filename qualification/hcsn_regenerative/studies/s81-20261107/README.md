# Qualified and frozen S81 mechanism pilot

The independent study `hcsn-regenerative-mechanisms-fv-pilot-20261107-1631115f163f-v1`
was frozen at **2026-11-07 16:14:56.958080 UTC**, before any formal task fit.
Its immutable plan is [`plan.json`](plan.json), SHA256
`cc2fe01594bd77721eda1f2a3130257ba5dbfa61c498a9f469f91195598c2550`.
This is a qualified execution plan, not evidence that the mechanisms improve
task outcomes. Expansion admission remains **HOLD**.

## Reconstructing the unchanged qualification artifacts

Run `python3 materialize_qualification.py` in this directory, or provide
`--output /absolute/new/directory`. The standard-library-only helper checks all
nine Git part files, reconstructs the exact 585,492-byte ZIP, verifies its full
SHA256 and CRC and all 47 member hashes, and materializes the operator bundle,
sidecar, qualification receipts, and original raw evidence. It executes no model
and never overwrites different existing output bytes. The frozen plan remains
`cc2fe01594bd77721eda1f2a3130257ba5dbfa61c498a9f469f91195598c2550`.

The prior unpublished candidate commit
`bce57ec488133b9f8be59a1ccf8ca9ab7f0f10da` stored a direct large NPZ and duplicate
qualification files. Native Git API reads repeatedly ended with incomplete
large responses; HTTP Range was ignored by that endpoint in the observed probe.
Those failures remain retained, and no formal training was started. This commit
changes only the artifact carrier to files of at most 65,536 bytes. It retains
the exact original ZIP, numerical bytes, source pins, qualification results,
failed configurations, frozen plan, and all scientific budgets. The network
root cause is unknown; no official response-size limit is asserted.

## Actual qualification

The final suite ran once through the native Hepta runtime Kaggle adapter.
The actual request was `hcsn-s81-kaggle-qual-v1-20261107-1631115f163f`.
Provider COMPLETE, native completion, remote manifest, HTTP lengths, whole
artifact SHA256/ZIP CRC, and all 32 numerical/runner source bytes were checked.
The complete raw suite is retained as
[lossless archive parts](artifacts/MANIFEST.json),
SHA256 `9ec88b996749732155d4c31e7830b297a668fbf648a3f849aff6aa8cab334661`.
Four inaccurate provider listing sizes remain disclosed; actual HTTP lengths
and independently checked manifest sizes/hashes matched the downloaded bytes.

| Required check | Actual evidence |
| --- | --- |
| Full-distribution finite-volume unit tests | 8 methods passed |
| Finite-volume audits in the actual Kaggle environment | 12 CPU and 12 CUDA cases passed |
| True zero-refractory construction | 6 unit methods and 36 direct convolution comparisons passed |
| Selected S81 operator construction | Exact NPZ and sidecar bytes bound to the plan |
| Final consuming runner unit tests | 13 passed; 0 skipped, errors, or failures |
| Short graph and derivatives | 47 CPU and 47 CUDA cases passed |
| Full 64-step sequence and derivatives | 42 CPU and 42 CUDA cases passed |
| Fresh-process next-episode update | Exact CPU and CUDA next-block results; 3 actual updates per device |
| Complete non-task feasibility probe | 400 updates in 80.99728586699996 seconds; original gate below 450 seconds |

The actual environment is Python 3.13.16, NumPy 2.1.3, Torch 2.11.0+cu130,
CUDA build 13.0, one CPU thread, deterministic algorithms, and a Tesla T4
with 15,636,037,632 bytes and compute capability 7.5. The operator builder
used SciPy 1.16.3. A new lease may use a different UUID of this exact GPU
class. Software or device-class changes require new qualification and a
distinct plan; prior Colab results are not silently reused for such changes.

The 32-file source-set digest is
`731f883bf55e28abdfc02c7e650e1c8108877fa6d99fd9fe82b349ef67c87a39`.
The actual materialized `operators-s81.npz` SHA256 is
`a1d7168201def0ec0503ab753fe431fc66de12adde22be5c984da0a3e5eaef8a`;
its materialized `operators-s81.json` sidecar SHA256 is
`bbfb5372e8642f05d19bd54bfba69ba7404d8d90b057cc6380eb08bd40505f64`.
All represented probabilities, features, source pins, and environment gates
are checked again before task construction and training.

## Fixed experiment denominator

| Dimension | Frozen value |
| --- | --- |
| Arms | regenerative dual, ordinary smooth dual, margin-only, Call-only, risk-only, endpoint, no reset, no refractory, uniform tick, conditional boundary |
| Tasks | delayed recall and adding |
| Independent training seeds | 1103, 2207, 3301, 4409 |
| Learning-rate trials | 0.001 and 0.003; both receive the complete budget |
| Test episode seeds | 4703 and 5801, aggregated within each fitted model |
| Per fit | 400 updates, batch 64, sequence length 64, hard wall 480 seconds |
| Complete training matrix | 160 fits, 64,000 updates, 262,144,000 sequence positions |
| Actual learned capacity | 81 state coefficients and 2,890 trainable parameters in every arm |
| Selection groups | 8 task/training-seed groups, 20 fits each |
| Selected test evaluations | 80; episode seeds do not create extra independent training repeats |

The complete ordered roster SHA256 is
`fcce78273b9eaab029840546bf41da3a568580b7a777c06b978986b42884da5b`.
All arms use identical split data, seed-matched initialization, and minibatch
order. All 20 training/validation terminals in a group precede selection;
the original validated selection lock precedes all tests in that group.
Incomplete learning-rate pairs remain in the denominator. Strongest-control
claims require the complete registered other-arm set, not a post-test choice.

The ten per-task contrasts, minimum useful absolute MSE reduction 0.01,
four-training-seed paired intervals, and Holm family of 20 are frozen in the
plan. Zero-variance or missing-replicate estimates are ineligible for an
inferential success claim. All signs, failed fits, and unknown attempts remain
reported. Four seeds and two synthetic tasks do not provide a confirmatory
external-task or deployment result.

## Provider execution boundary

The pretraining
[`MECHANISM_EXECUTION_AMENDMENT_20261107.md`](../../MECHANISM_EXECUTION_AMENDMENT_20261107.md)
adapts the provider envelope from the earlier Colab setting to Kaggle.
A 3,000-second provider job handles one group and one phase, running one
bounded operation at a time on GPU 0. Before each claim, at least 720 seconds
must remain: 480 for the operation, 60 for supervisor/startup/drain, and 180
for evidence export and close. Insufficient or unknown time prevents a new
claim. It does not shorten training or erase an unstarted fit.

The sole owner verifies the prior authoritative terminal and exact complete
history before proceeding. Selection and selected evaluation are separate
phases. Known failures/timeouts remain terminal and are never replayed.
An unknown attempt, failed integrity check, or environment mismatch halts
the owner for read-only reconciliation. Private notebook input mounts are
verified by exact capsule/bundle hashes, not just a mutable notebook name.

## Numerical and scientific limits

The S81 resolution was selected before task training from the smallest grid
passing the original state-L1 0.02 and expected-count-relative 0.03 gates.
The failed S25 grid remains recorded: maximum state L1 0.20530385943 and count
relative error 0.17668811113. S81 maxima were 0.01584776136 and 0.01186598755.
These are bounded unconditioned-law checks on the registered schedules;
they do not establish arbitrary-posterior, cohort, or global continuum error.

The 64-step derivative probe resolved nonzero first-input dependence for its
three registered arms and fixed non-task fixture. This establishes the tested
graph behavior, not task-level long-memory benefit. Fresh-process mechanism
recovery used independent episodes, with the intended reset between them.
It is not production mid-fit resume. The separate finite-volume recovery
test checks continuing belief/state consumption.

The qualification suite consumed 241.621250125 seconds. Measured GPU device
counter intervals were 4,719.457 J on GPU 0 and 2,666.498 J on GPU 1. These
include idle or unattributed device activity and are not whole-machine or
model-exclusive physical energy. Nested probe energy is not added again.
Whole-machine physical energy, complete billing, external-task retention,
and deployment cost gates remain unknown or unmeasured.

This study contributes **zero** completion credit to the original frozen
170-run campaign or the separate Hepta × NDU experiment. Earlier failures,
unknown Colab attempts, the original B OOM, and unfavorable results remain
separate evidence. Neither qualified numerics nor a favorable synthetic pilot
can authorize expansion without external utility, retention, and complete
cost evidence against the strongest deployable control.
