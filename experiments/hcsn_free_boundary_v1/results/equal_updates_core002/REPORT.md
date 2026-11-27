# Separate equal_updates_core002 diagnostic

## Status and scope

**4/18 new free_dual searches valid; 126 baseline searches explicitly reused; complete diagnostic: False.** All new candidates are fresh same-seed training runs targeted at exactly128 updates. This is a post-primary diagnostic on already-inspected test data, not a replacement for the 20-CPU-second primary study or an untouched new confirmation.

The original strict128 secondary remains permanently unchanged: **202 evaluated, 42 incomplete, zero added training**. This separate directory pays for new free-cell training to investigate the concrete coverage limitation. It does not fill or rewrite those original records, change the six original Holm comparisons, add learning rates, or tune on these diagnostic outcomes.

## Registration, selection and audit

EQUAL_UPDATES_CORE002_PROTOCOL.json and REGISTRATION.json were written before new training. The six tasks and seeds9101–9103 are fixed. Every new free candidate starts from the original same-seed initialization, uses frozen training.py Adam/task cross entropy/clipping/batch32/model/data, and stops at exactly128 updates. The 120-CPU-second ceiling is a failure guard, not the target allocation. No optimizer state is resumed.

Both learning rates, 0.001 and0.003, complete before choosing minimum validation cross entropy at exactly128; ties use the smaller LR. The helper's earlier CPU-gate best checkpoint is explicitly ignored. Durable selection precedes test/OOD loading. Only this diagnostic's intermediate numeric checkpoints are pruned; their hashes remain in metadata, and initial/128/selected numeric weights are retained. Original files are never pruned.

Audit counts: {'fresh_initials_byte_identical': 16, 'new_candidate_full128_prefixes_verified': 16, 'existing_original128_exact_replays': 10, 'baseline_prefix_logs_reread_live': 252, 'reused_baseline_candidate_full128_prefixes_verified': 252}. The new initial files and all128 minibatch/prefix hashes are verified; every original free128 checkpoint that already existed must replay byte-for-byte. Every reused baseline candidate's first128 minibatches is also independently checked. New and reused prediction archives are independently remapped and their accuracy/CE recomputed. Every failed execution, if any, remains in the complete cost bill.

During execution the shared filesystem filled. Original evidence had already been verified in its complete archive. To recover space, only unregistered redundant old logs/checkpoints could be removed after archive-member hash checks. Before reclamation, all252 baseline LR prefixes were independently parsed and compared, and their full-log SHA matched the original primary audit. The exact first128 evidence is retained in REFERENCE_PREFIX_AUDIT.json, whose byte hash is pinned by this analysis. The eighteen registered prefix logs and every registered training dependency remain live. Counts distinguish live rereads from the preserved pre-reclamation audit; no missing evidence is silently invented.

A check-location difference is disclosed: the new wrapper verifies the complete registered manifest before and after each worker, while the original run_search additionally hashes the dataset immediately between selection lock and heldout load. This wrapper lacks that extra intermediate hash operation. The data were static and all registered hashes match in this actual experiment; the frozen training source itself is unchanged.

## Complete ID table

Accuracy in percent, mean ± sample SD over three paired seeds. free_dual is newly retrained; all seven other rows reuse the original strict128 validation-selected snapshots and already executed predictions. No new significance claim is assigned to these three-seed cells.

| Model | Copy | MQAR | Irregular | MNIST | FSDD | Multimodal |
| --- | --- | --- | --- | --- | --- | --- |
| free_dual | incomplete 0/3 | 27.75 ± 4.93 | incomplete 0/3 | incomplete 1/3 | incomplete 0/3 | incomplete 0/3 |
| legacy_hcsn | 24.32 ± 2.75 | 19.91 ± 2.39 | 93.62 ± 1.71 | 55.21 ± 3.50 | 22.72 ± 7.67 | 14.84 ± 2.58 |
| two_gates | 12.19 ± 1.37 | 12.34 ± 0.65 | 94.08 ± 0.30 | 23.89 ± 4.46 | 12.96 ± 2.43 | 11.91 ± 3.22 |
| continuous_rnn | 12.22 ± 1.34 | 12.58 ± 0.44 | 93.75 ± 0.70 | 35.42 ± 3.75 | 15.56 ± 1.00 | 16.93 ± 1.30 |
| cfc | 12.50 ± 0.29 | 13.26 ± 0.20 | 86.91 ± 1.09 | 26.11 ± 0.69 | 9.90 ± 0.49 | 16.28 ± 2.11 |
| mamba1 | 18.51 ± 7.62 | 20.15 ± 10.05 | 84.57 ± 1.74 | 49.15 ± 9.12 | 23.24 ± 12.42 | 16.73 ± 3.96 |
| transformer | 45.85 ± 2.07 | 88.12 ± 7.62 | 85.09 ± 5.80 | 67.12 ± 2.99 | 24.67 ± 1.58 | 21.74 ± 3.73 |
| lif_snn | 11.30 ± 0.97 | 12.39 ± 0.47 | 88.54 ± 0.30 | 13.93 ± 3.60 | 9.77 ± 0.52 | 10.03 ± 0.30 |

## Prespecified OOD table

Copy/MQAR length64 and irregular3× time; no new OOD task was introduced.

| Model | Copy64 | MQAR64 | Irregular3×time |
| --- | --- | --- | --- |
| free_dual | incomplete 0/3 | 27.33 ± 5.46 | incomplete 0/3 |
| legacy_hcsn | 21.35 ± 3.66 | 15.95 ± 1.47 | 66.21 ± 15.60 |
| two_gates | 13.13 ± 0.45 | 12.55 ± 0.48 | 64.91 ± 5.10 |
| continuous_rnn | 13.07 ± 0.17 | 12.92 ± 0.49 | 58.53 ± 5.36 |
| cfc | 12.53 ± 0.58 | 12.79 ± 0.38 | 64.45 ± 20.65 |
| mamba1 | 14.76 ± 1.81 | 16.89 ± 6.52 | 52.80 ± 1.19 |
| transformer | 16.39 ± 2.78 | 60.84 ± 10.09 | 52.21 ± 1.47 |
| lif_snn | 12.53 ± 0.61 | 12.34 ± 0.63 | 61.26 ± 7.05 |

## Descriptive paired differences

Direction is new free_dual minus the indicated reused baseline, in percentage points. The per-seed pairs and sample SDs are retained in ANALYSIS.json. These are not new corrected hypothesis tests or primary acceptance gates.

| Comparator | selective_copy | mqar | irregular | mnist | fsdd | multimodal_select |
| --- | --- | --- | --- | --- | --- | --- |
| legacy_hcsn | incomplete | +7.85 | incomplete | incomplete | incomplete | incomplete |
| two_gates | incomplete | +15.41 | incomplete | incomplete | incomplete | incomplete |
| continuous_rnn | incomplete | +15.17 | incomplete | incomplete | incomplete | incomplete |
| cfc | incomplete | +14.49 | incomplete | incomplete | incomplete | incomplete |
| mamba1 | incomplete | +7.60 | incomplete | incomplete | incomplete | incomplete |
| transformer | incomplete | -60.37 | incomplete | incomplete | incomplete | incomplete |
| lif_snn | incomplete | +15.36 | incomplete | incomplete | incomplete | incomplete |

## Costs and distinct comparison targets

| Model | Searches | Median two-LR training CPU to128, s | Median measured full-search CPU, s | Full-search scope |
| --- | --- | --- | --- | --- |
| free_dual | 4 | 39.899 | 46.766 | new fixed128 search |
| legacy_hcsn | 18 | 22.706 | 44.507 | historical original20CPUperLR search, reused, not reexecuted |
| two_gates | 18 | 5.002 | 43.568 | historical original20CPUperLR search, reused, not reexecuted |
| continuous_rnn | 18 | 4.118 | 43.603 | historical original20CPUperLR search, reused, not reexecuted |
| cfc | 18 | 6.116 | 43.566 | historical original20CPUperLR search, reused, not reexecuted |
| mamba1 | 18 | 8.761 | 43.833 | historical original20CPUperLR search, reused, not reexecuted |
| transformer | 18 | 2.333 | 43.851 | historical original20CPUperLR search, reused, not reexecuted |
| lif_snn | 18 | 5.488 | 43.552 | historical original20CPUperLR search, reused, not reexecuted |

New complete worker CPU: **809.269501s**; coordinator CPU: **0.103281s**; wall time: **270.910254s**. Actual new training-update CPU is 159.418291s. Failed-worker CPU retained is 621.305721s. These are nested scopes and must not all be added together.

The reused baselines add zero training or neural inference in this diagnostic. Their historical complete original searches consumed 5520.721426s; their earlier strict128 per-run evaluation scopes consumed 17.697955s, excluding that earlier evaluation worker's shared import/setup overhead. These historical observations are disclosed, not falsely billed as newly executed work.

Equal updates are not equal compute. Prefix CPU-to128 is an observed timing of the training prefix; the original baseline full20CPU/LR searches remain real previously incurred costs. Their original whole-search costs and new free-cell fixed128 whole-search costs have different scopes. Different executions also have different contention/import/checkpoint timing. No hardware-energy or isolated-throughput claim follows.

## Interpretation limits

This complete fixed-update diagnostic, if all18 new searches pass, can describe performance after the same number of optimizer updates with the registered initialization, data and two-LR search. It cannot establish that a fixed-update gain is an equal-CPU advantage, overturn the original0/6 mechanism or0/6 content-screen results, or give a causal decomposition of the original gaps. Both statistical target and computation spent differ from the primary experiment.

The test arrays were already observed in the completed primary/secondary experiments. The diagnostic was motivated by missing strict128 coverage and was separately registered before its new execution. It is therefore a disclosed diagnostic, not an independent fresh-test confirmation. Three seeds support descriptive uncertainty only. The tiny real-data tasks, low absolute speech accuracy, mean-state closure bias and non-foundation-model scope remain applicable. It does not establish universal superiority or inferiority of any architecture family.

Reproduce audit/report only with `python -m experiments.hcsn_free_boundary_v1.equal_updates_core002_analysis`. It performs no training or neural inference and refuses to overwrite prior analysis evidence. All original38 frozen source/data files, primary selections, original secondary records and registered Holm results remain unchanged.
