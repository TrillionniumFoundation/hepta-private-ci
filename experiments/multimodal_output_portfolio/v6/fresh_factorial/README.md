# Fresh matched base × gate objective study

This is a new bounded scientific experiment. It answers whether a change to the base training objective, the gate training objective, or their interaction changes emitted text/image quality in the constructed MNIST digit-pair domain. It does not recover, replace, or relabel the unavailable full-002 checkpoints. The historical-recovery factorial remains unchanged in its separate source path and retains all original archive pins.

## Registration and estimands

The four cells are `b0g0`, `b0g1`, `b1g0`, `b1g1`: supervised/terminal-entropic base training crossed with supervised/terminal-entropic gate fitting. Use the original three fixed seeds, 17, 29, and 43. For each seed, the two bases start from the identical seeded parameter state and use the same batch, latent-noise, action and update schedule. Both gates on a base receive identical frozen-base emitted-output rewards. No forecast, online controller, search, candidate sweep or adaptive stopping is part of this study.

For source-pair loss `L`, average the three fixed seeds first. The three registered contrasts are:

| Contrast | Coefficients on b0g0, b0g1, b1g0, b1g1 |
| --- | --- |
| Base main effect | −1/2, −1/2, +1/2, +1/2 |
| Gate main effect | −1/2, +1/2, −1/2, +1/2 |
| Interaction | +1, −1, −1, +1 |

The primary cohort has 60 future source pairs, ten in each of six fixed corruption strata. The uncertainty calculation resamples paired source units within strata, 10,000 replicates at bootstrap seed 431125. The three two-sided percentile intervals use quantiles `0.05/6` and `1−0.05/6`. A main effect is an improvement only if its upper endpoint is below zero. Interaction has a direction and interval, not an improvement pass/fail label. Negative, null and positive results are all retained. These intervals are conditional on the fitted models and three fixed seeds; they do not measure training-seed population uncertainty.

The gate factor compares hard mean-best-plan imitation against direct finite entropic utility optimization. It is an objective package, not an isolated test of risk aversion. Base training uses the original differentiable surrogate; it is not the emitted-output observer score. Secondary factual accuracy, per-seed effects, descriptive CVaR90 and 30 clean-retention source pairs do not add confirmatory comparisons. Clean retention is not a continual-learning forgetting experiment.

## New model generation

`template.json` fixes the original architecture and bounded recipe. Two fresh observers each use 5,000 disjoint evaluator sources: 4,000 for 300 optimizer steps and 1,000 for descriptive calibration. Reward A uses seed 314159; Audit B uses seed 161803. Neither calibration score selects a retry, model or hyperparameter. Audit B is never provided to base/gate fitting.

Six fresh bases each execute 2,000 original updates, with 1,007,464 parameters each. Twelve fresh gates execute 120 updates each and have 3,236 parameters each. Total optimizer work is **600 + 12,000 + 1,440 = 14,040 updates**. The original five implementation modules are exact SHA-pinned at the scientific source `b98961ceb71414490e1c6ae397cf635bca3093f4`; those same blobs exist at evidence head `406a926f8fdfd1eed28abc9cfe449daa1fea02cc`.

The bootstrap generation receipt is create-only. Before fitting, the code independently reconstructs seeded initializer fingerprints and base/gate update schedules from the frozen recipe. Original training reports must match those controls, including base action schedules and gate source/scenario/update schedules. Checkpoints are saved and reloaded through their actual original typed loaders. The source, data receipt, newly executed training reports and every new file hash are retained.

After fitting all twelve gates, the append-only `model-seal.json` binds exactly **20 new model files**: two observers, six bases and twelve base+gate checkpoints. It binds the complete bootstrap and training seals, protocol, source data and fresh generation ID. Every model seal is checked before inference. There is no historical archive bypass option and no old checkpoint import argument.

## Historical source exposure and fresh-source boundary

Twenty exact committed Git blobs under `registration/published/` are mandatory. Their original repository paths, Git blob IDs and SHA256 values are in `registration/published-manifest.json`; compact committed JSON bytes are kept distinct from the unavailable raw-archive serialization. Automated identity extraction reconstructs the old **360** future/retention source pixels and **488** known pixels including the validation-only competence/command probe. A mandatory-set check rejects missing records even if someone removes the corresponding manifest entry.

| Published evidence | Source coverage and treatment |
| --- | --- |
| full-001 | Future pairs 0–59 and retention 0–29; 180 unique pixels excluded. |
| full-002 | Future 60–119 and retention 30–59; another 180 unique pixels excluded; exact prior 360 union checked. |
| replay-001 | The original full-001 ordered 7,560 rows are replayed; no additional scientific source cohort. |
| competence-001 and command-film-001 | Validation pairs 512–575, 128 pixel identities in the published summaries; official test and retention unscored. |
| Neuron calibration | Validation pairs 640–703 and 704–767, as predeclared in its exact specification. The entire validation split is disjoint from fresh future/retention sources. |
| terminal, paired and trained owners | Previously observed full-001/full-002 engineering replay; source lineage and zero-new-sample claims retained. |
| published CI | The v6 workflow explicitly selects the conditioned protocol. Its smoke offsets are future900/retention450. The complete ranges future900–999 and retention450–499 are reserved and excluded. The older default protocol's first-case smoke is already inside full-001 exclusions. |

This catalog covers known published v6 records at the pinned evidence head. It does not prove that arbitrary unpublished local runs or every unretained CI artifact never touched another source. Root must provide a named, hash-bound discovery receipt, explicit prior-evidence roots, and a scope review for every catalog item plus unlisted local/CI runs. Inventory errors, symlinks, unsupported archives, unexplained opaque payloads, omitted exposure identities, changed metadata or **any unresolved source-exposure gap block registration and a fresh-confirmatory claim**. The review may not call the missing original model archive recovered.

The predeclared fresh pair ranges are future120–179 and retention60–89. If the reviewed union overlaps them, preparation fails without fallback sampling. The unchanged MNIST manifest, all four original compressed-file hashes, all training/evaluator/validation partitions, source pixel identities and case mapping are checked. Unselected unexposed source IDs remain reserved; their pixels and labels are not emitted as a development set.

## Execution and one-time final access

The approved path is one `harness` execution: prepare, bootstrap, gates, inference, independent replay, evaluate. Source algorithms, reviewed exposure census, actual CPU environment specification and one unused absolute owner directory must be committed and externally verified before source preparation or training. All stage paths must be the corresponding child of that owner; relative paths, symlink aliases and alternate output owners fail. This protects a retained owner and published protocol. Deleting/remapping evidence or changing the published protocol is outside the protection claim and prohibited by this study.

Preparation writes label-separated training/evaluator arrays and public observations. It writes opaque final targets once and does not reopen them. Model and inference stages install a process audit hook denying final target file access; their only modeled inputs are the prepared training/evaluator pools or public observations. The preparation process necessarily sees dataset labels to construct the sealed cohort; this is an implementation separation, not OS-level confidentiality against a host administrator.

Every arm selects one of the original four two-action plans, then executes the same three-action suffix. All 1,080 rows have equal structural work: one encoder, one gate, two initial transitions, three suffix transitions and one joint decoder producing two modalities. Actual time/RSS may differ. The separate replay process must reproduce every emitted byte and all four 384-dimensional state snapshots per row before final scoring.

Final evaluation first verifies complete required model/output files, source bindings, the entire replay and the new Audit B identity. An exclusive-create final-access ledger then consumes the source cohort **before** its first target-payload read. Concurrent claims and retries fail; even a later evaluation error consumes the cohort. The scorer rereads emitted PNG/UTF-8 bytes and uses the original Audit B; a second NumPy implementation independently checks metric arithmetic on the same OCR predictions. This does not independently certify OCR truth.

## Environment, budget and interpretation

The original CPU package versions remain registered: Python3.12, Torch2.14.1+cpu, NumPy2.3.5 and Pillow12.3.0. Root's official-index availability receipt is copied byte-for-byte to `registration/environment-preflight.json`; SHA256 `f891be2ab1c5d054d76e98ea7b793e5244cbf3785c7c84962ee42ceef50ea183`. Every stage still verifies actual installed versions, deterministic CPU mode, two Torch/inter-op threads and numerical thread limits. Python patch and platform are recorded; all stages must agree. No cross-host bitwise identity with the lost original weights is claimed.

The whole harness has a 1,800-second compute deadline, a sampled 2-GiB child RSS guard plus completed-child peak check, and a 1-GiB new-evidence bound. Setup/download/install cost is recorded separately. CPU/wall/import/exit and failed-stage costs are preserved; no automatic retry or resumed training is permitted. The guard is not a kernel allocation cap, and electrical energy and joint process-tree peak allocation are not measured.

The historical report gives approximately 461 seconds for six base fits and 11 seconds for its two observers; this is a planning reference, not a promise for a different host. If the budget or an integrity gate fails, retain the partial experiment and report the failure. Do not extend the budget after examining outcomes or silently choose new sources.

This fresh study can identify the registered base/gate objective contrasts without the historical archive. It cannot establish recovery of original checkpoints, independently new random-seed replication, AGI, automatic topology evolution, dynamic-controller superiority or production qualification. Its absolute scores must not be pooled with old full-002 scores because its observer/model generation and final source cohort are newly executed.

## Validation status before execution

The pure NumPy/stdlib test modules exercise factorial arithmetic, malformed and omitted census records, archive coverage, altered source/init/schedule, missing or aliased models, model-seal omission, owner reuse/alias, final claim races, replay differences and bounded failure costs. All model fixtures are explicitly nonmodel bytes and do not count as optimizer execution or scientific observations. The real source census, model training, holdout outcomes and resource measurements remain to be executed by root after review and publication.
