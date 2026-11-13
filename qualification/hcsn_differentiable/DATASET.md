# UCI localization: actual data audit and bounded interface smoke

User authorization for new research is already present. This independent smoke has a fixed budget and separate evidence directory; incomplete scientific qualification of the formal benchmark is not a request for more user permission. It grants no S81/S25/original170 completion or budget credit.

## Official source and data-only execution

Use the [UCI dataset page](https://archive.ics.uci.edu/dataset/196/localization) and its actual [Download ZIP](https://archive.ics.uci.edu/static/public/196/localization%2Bdata%2Bfor%2Bperson%2Bactivity.zip). The published schema is eight comma-separated fields: sequence, tag, integer timestamp, formatted date, x/y/z and activity. Attribution: Vidulin, Lustrek, Kaluza, Piltaver and Krivec (2010), *Localization Data for Person Activity*, [DOI 10.24432/C57G8X](https://doi.org/10.24432/C57G8X), CC BY 4.0. Retain this attribution with redistributed data.

From the candidate root, run the default standard-library-only path:

```sh
python -m qualification.hcsn_differentiable.localization_smoke --output /absolute/new-study/dataset-001
```

The output directory must be new. `--archive /path/to/official-localization.zip` reuses a prior download without network access, but its official-origin receipt must be retained; a matching local schema is not proof of download origin. The script preserves the ZIP, hashes it and every non-directory member, checks CRC while reading, and bounds compressed/expanded bytes. It never extracts archive paths into the filesystem. Expected main member: `ConfLongDemo_JSI.txt`.

The parser examines every row and requires the published 164,860-row, 25-sequence, four-tag, 11-label schema. It preserves source line identities, reports original backwards pairs and duplicate timestamps, and sorts each sequence by integer timestamp with source-line tie breaking. It compares **relative** tick differences with date-field differences at candidate scales 1, 10^-3, 10^-6, 10^-7 and 10^-9 seconds/tick. A unique 10^-7 match within 2 ms for every adjacent pair is required; an assumed timezone offset cannot make this check pass. Absolute timestamps are never converted to floating point before subtraction.

`report.json` contains source-code hashes before/after execution, archive/member/data hashes, full sequence counts, tag/activity counts, clock residuals, gap quantiles, selected-window statistics, actual wall/CPU time, and peak RSS when supported. `events.jsonl` preserves completed stages and optimizer updates even if the process is interrupted; `locked-spec.json` records the selection/budget before acquisition. Download, CRC, decoding, schema or clock failures produce a blocked record with no fabricated dataset pass.

## Fixed selection and frontend

The selection is locked before inspecting observations: the first **128** timestamp-sorted events of **A01** for training and the first **64** events of **D01** for development forward checks. No alternate window is searched. E participates only in whole-file integrity/schema/clock validation; it never enters normalization, selected features, optimization or model evaluation. Per-sequence full-file statistics are metadata, not a model-selection signal.

`frontend.json` fits coordinate mean and population standard deviation using observed coordinates in the selected A01 training events only. Standard deviations have a fixed 10^-6 floor; an unobserved training coordinate uses mean 0 and scale 1. Each event becomes the same 25 deterministic features for both models: 12 normalized sparse coordinates, 12 observation-mask entries and log1p of the real interval in seconds. There is no learned modality frontend. All-zero placeholders are accompanied by masks. `features.json` stores actual model inputs, original line numbers, labels and physical `dt`, and is hashed in the report.

The first event of each selected sequence has `dt=0`; subsequent intervals use consecutive original ticks. If **either fixed selection contains `dt > 0.1` seconds**, status is `blocked_selected_gaps`, exit code is 2, and no fit starts. The valid dataset/frontend artifacts remain available. There is no gap clipping, resampling, dropping, hidden subdivision or different-window fallback.

## Optional one-seed two-model execution

```sh
python -m qualification.hcsn_differentiable.localization_smoke --output /absolute/new-study/smoke-001 --archive /absolute/new-study/dataset-001/official-localization.zip --train
```

The implementation needs the existing Torch dependency only when `--train` is present. It creates a GRU with width 4 and a one-layer HCSN with content width 4, both FP64 with 11 logits and the exact same saved frontend. The HCSN uses the existing 6-active/3-phase/q8 mechanism grid and frozen default physical parameters. This coarse grid is **not a qualified physical-fidelity result**, and the parameter counts of these two tiny models are reported rather than claimed equal.

The fixed seed is 20261108. Each arm receives at most four Adam updates at learning rate 0.001, processing disjoint consecutive 32-event windows of the selected 128 A01 events. Gradient norm clipping is fixed at 1; nonfinite/missing gradients or zero gradient norm fail. Every update has a new initial state because the existing network rejects parameter changes in a retained episode. Original inter-event `dt` is retained even at these explicitly declared training-window boundaries; the new prior is placed at the preceding observation time. Both arms follow this state-reset rule. D01's 64-event evaluation uses one fresh state and no optimizer updates.

The total process budget, including data work, is **180 seconds**, one Torch CPU/inter-op thread and **1 GiB peak RSS**; ZIP limits are 16 MiB compressed/32 MiB expanded with a 30-second network read timeout. Wall/RSS are checked at data and model-operation boundaries, not enforced as an OS allocation sandbox. For a strict external kill deadline, the caller must retain the already-written event log; killing a process does not imply a completed run. No CLI flag increases these budgets or changes the seed, windows or steps. Budget exhaustion preserves exact completed-update counts and marks the run incomplete.

Outputs include initial states, every completed optimizer checkpoint, development logits, actual per-window losses and cross-entropy, and a check that HCSN physical values remain unchanged. Losses from different windows are not a learning curve. Dataset-only work and this two-model interface smoke both report **formal fits = 0**; `smoke_fits_started` and per-arm optimizer counts report the work actually performed. Unknown physical energy and provider charges remain null.

Exit 0 means the requested data-only or interface operation completed; exit 2 means blocked/incomplete, and exit 1 denotes training failure or changed source. Neither exit 0, a single seed, nor finite gradients establish generalization, six-family fairness, superiority, numerical coverage, or complete-energy efficiency. Formal admission remains governed by [BENCHMARK.md](BENCHMARK.md) and its independent evidence contract.
