# Real asynchronous encoder comparison: admission contract

This new formal comparison has **zero formal fits**. User authorization for new research is already present; scientific admission remains blocked by missing dataset/implementation receipts, numerical coverage and quantified comparison budgets. `research_protocol.json` deliberately fails this evidence gate. Contract tests use synthetic ledgers; the separate [localization smoke](DATASET.md) can acquire real data and perform bounded interface checks without claiming formal-comparison eligibility. It inherits no S81/S25/original170 completion or budget. Historical unknown remote execution remains unknown; a local zero here is not a statement that old remote work stopped.

## Task and split

Use [UCI Localization Data for Person Activity](https://archive.ics.uci.edu/dataset/196/localization), [DOI 10.24432/C57G8X](https://doi.org/10.24432/C57G8X). The official source describes five people, four body-mounted tags, 25 sequences, 164,860 timestamped records and 11 activities; its license is CC BY 4.0. Each event identifies a tag and its position. This provides real asynchronous observations without generating irregularity by randomly deleting an otherwise regular benchmark.

Start with the preregistered subject split A/B/C training, D development, E confirmation. Build sequence IDs and SHA-256 digests from the actual downloaded data; no windows or overlapping sequence fragments may cross partitions. The result is evidence about one held-out person, with limited population scope. A later five-fold subject evaluation must freeze all choices before examining any confirmation labels and rerun independent training within each fold. Folds and events are not extra independent training seeds.

The source reports complete individual records. In a combined tag stream, other tags are unobserved at that event: use explicit masks, not fake measured zeros. Sort within a sequence using the original integer timestamp, subtract before floating conversion, and verify its unit against the source description/date field. Preserve true elapsed time, sequence boundaries and labels; record ties, nonmonotonic records and maximum gap. The data adapter is not implemented yet.

Freeze one deterministic frontend: observed-coordinate normalization fitted on training subjects only; a 12-coordinate sparse event vector, its 12 masks, and elapsed time. All arms receive identical observations, timestamps, masks and causal history. Any model-specific trainable input projection counts in that model's parameter budget. The existing `IrregularSensorEncoder` contains a learned MLP, so using a separately learned copy in each arm would not satisfy this frozen-frontend contract. `time_scale` only transforms its time feature and does not rescale physical `dt`.

## Models and current availability

| Arm | Concrete reference / proposed implementation | Available in this candidate? |
|---|---|---|
| GRU + strong recurrent | PyTorch GRU; GRU-D with mask/time decays from the [original paper](https://www.nature.com/articles/s41598-018-24271-9) | No real-task runner or pinned GRU-D implementation |
| CfC | Official [ncps](https://github.com/mlech26l/ncps), passing the real timespans | External implementation not installed/pinned |
| Modern SNN | Recurrent surrogate-gradient network with learned decay/tau, using [SpikingJelly PLIF](https://spikingjelly.readthedocs.io/zh-cn/latest/tutorials/en/neuron.html) | No task implementation; irregular-time update must be specified and qualified |
| SSM / Mamba | Official [Mamba](https://github.com/state-spaces/mamba), exact revision and supported kernel pinned | Not installed/pinned; CPU/GPU compatibility unqualified |
| Attention | Causal time/mask-aware Transformer; [mTAN](https://github.com/reml-lab/mTAN) as an additional irregular-data reference | No task implementation; original noncausal interpolation is not automatically a causal control |
| HCSN | Existing `ContinuousSpikingNetwork` and explicit retained probability/content state | Mechanism candidate available; real-data training/evaluation adapter absent |

Neither existing synthetic encoder tests nor the names in this table count as implemented trained baselines. This local environment has no Torch, ncps, mamba_ssm or SpikingJelly. Exact library versions, implementation hashes and configuration hashes must be recorded before any launch. Baselines need comparable architecture selection, optimization and tuning, including failed attempts; a poorly trained SNN is not a useful control.

## Required ablations

The admission module requires these separately trained arms, each using the same new seed set and frontend. A paired design reuses seed *numbers* across models while creating distinct initializations and checkpoints. Five training seeds is a development floor, not a power calculation or guarantee of significance.

| Comparison | Required arm IDs and interpretation |
|---|---|
| Physical optimization | `hcsn` (trainable) / `frozen_physics`; report valid parameter-domain coverage |
| Channel contribution | `call_only`, `risk_only`, `dual`; keep only the stated physical readouts |
| Generic gate explanation | `dual` / `plain_dual_gate`; match total trainable parameters within 5% and identical content width; report residual difference |
| Reset | `hcsn` / `no_reset`; explicit alternative dynamics and its own numerical qualification |
| Distribution | `hcsn` / `mean_state`; retained content unchanged, physical state approximation documented |
| Generator sharing | `dual` / `independent_generators`; account for additional parameters/state |
| Content explanation | `content_only`: preserve content and remove **all five** physical bypasses everywhere |
| Maintenance / rollover | `hcsn` (off) / `rollover_on`; coupled implementation is currently missing |

The current five readouts are `call`, `risk`, `margin`, `expected_events`, `active`; `risk == expected_events` in the supported single-event interval. Removing only call/risk leaves physical information in the other inputs to the likelihood, gates, proposal and readout. A two-readout `dual` arm is therefore distinct from the current five-readout HCSN. A content-only intervention must also specify whether latent distribution processing remains: preserving it isolates readout contribution, while removing it is a separate compute/state ablation. Neither variant can be silently substituted for the other.

## Numerical and budget prerequisites

The current core rejects `dt > min(layer.grid.refractory)`. The default is 0.1 in the chosen physical time unit. Measure real gaps before choosing a grid. No clipping, hidden microsteps, dropped long gaps or relabeling the time-feature scale as physical clock conversion. A true change of clock units must transform drift, diffusion, discount and refractory consistently. A long-gap/substep extension requires its own time/projection error qualification before this contract can change from `long_gap_policy=reject`.

Close measured phase, space, tail and time budgets over the actual trainable physical domain and task gaps; bind the qualification to the exact HCSN implementation. Per-interval engineering `call` cannot be accumulated as regenerative `U`; any arm consuming `U` requires the corresponding regenerative qualification and a new frozen protocol. This gate checks recorded budgets and hashes; it does not itself calculate numerical error or authenticate those receipts.

Set a new explicit total wall-time ceiling **per arm across all seeds**, tuning-trial ceiling, parameter ceiling and authorization reference. The formal-comparison draft contains null ceilings; that is a missing quantified resource plan, not missing user permission. The independent smoke has its own fixed, bounded budget and uses the existing authorization. Allocate shared frontend/tables/tuning costs once to a named owner and retain the allocation policy. Selected-fit records must account for training, tuning, failed/retried attempts, encoder/table work, evaluation and transfer; retain the complete underlying attempt ledger. Old unresolved reservations cannot be interpreted as zero-cost new work.

## Result and claim contract

`validate_plan` and `validate_results` are read-only record-consistency checks. `quality_eligible` means complete comparable records, not superior quality; `efficiency_eligible` additionally requires complete measured resource fields. Actual raw artifacts, identities and ledger completeness still need independent verification; the existing user authorization is recorded separately from these scientific checks. Generated hash fixtures cannot establish that training occurred.

Each selected fit supplies arm, seed, run ID, fresh initialization digest, final checkpoint digest, execution receipt digest, and matching implementation/split/frontend/measurement-context digests. Duplicate arm/seed, checkpoint or initialization identities fail. Thousands of episodes from one checkpoint remain one trained model. Report per-seed outcomes and paired seed differences; quantify data uncertainty by subject/sequence clustering, not an iid event bootstrap. Keep inference-only interventions in a separately labeled analysis.

Report macro-F1, normalized multiclass Brier (mean squared error over examples **and classes**) and ECE using development-frozen bins. Report persistent state bytes, peak RAM and VRAM, throughput, p99 latency, training wall time and energy. The measurement-context artifact fixes hardware, threads, precision, batch size, sequence length, warmup, timing boundaries, synchronization and state/attention-cache accounting. Task quality must accompany efficiency results.

Each measurement has `value`, `status` and `scope`. Unmeasured fields use `value: null`, `status: unknown` and a reason; zero is not a substitute. CPU-only peak VRAM may truthfully be measured zero. Partial GPU/device energy can be reported with its scope but does not support a complete-energy claim. Complete energy uses `whole_system_all_cost_parts`, covering the entire charged experiment with meter scope, duration, uncertainty and idle/baseline treatment recorded. Unknown compute costs block admission; unknown/partial energy preserves task-quality records while blocking efficiency qualification.

From the candidate root run `python -m qualification.hcsn_differentiable.benchmark_admission qualification/hcsn_differentiable/research_protocol.json`; the draft must exit 1 with blockers. Pass `--results selected-fits.json` for a list of selected-fit records after actual training. `protocol_sha256` binds a separate frozen preregistration artifact, not a self-referential hash of this JSON. This formal-comparison protocol itself contains no acquired-data, training, performance or generalization evidence. Separately recorded dataset/interface-smoke artifacts do not change that claim boundary.
