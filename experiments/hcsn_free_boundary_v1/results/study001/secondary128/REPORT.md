# Strict exactly-128 secondary: original completed evaluation

## Result

**202 of 244 searches were eligible and evaluated; 42 remain incomplete; none is invalid. No additional training was performed.** This original secondary is permanently retained with its missingness. It is not repaired by later experiments.

An eligible search requires one exact update-128 snapshot from each of the two predeclared learning rates, 0.001 and 0.003. The LR is chosen solely by the corresponding validation cross entropy; an exact tie chooses the smaller LR. Its durable selection is written before heldout inference. A missing LR snapshot is not replaced with a nearby update, a reduced LR search, extrapolation, or resumed training.

## Coverage

Cells show evaluated/scheduled searches (missing count). The two mechanism tasks use eight seeds for mechanism arms; other core cells use three. “Not scheduled” is distinct from missing evidence.

| Model | Copy | MQAR | Irregular | MNIST | FSDD | Multimodal |
| --- | --- | --- | --- | --- | --- | --- |
| free_dual | 1/8 (missing 7) | 0/3 (missing 3) | 1/3 (missing 2) | 0/3 (missing 3) | 1/3 (missing 2) | 0/8 (missing 8) |
| legacy_hcsn | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) |
| two_gates | 8/8 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 8/8 (missing 0) |
| continuous_rnn | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) |
| cfc | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) |
| mamba1 | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) |
| transformer | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) |
| lif_snn | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) | 3/3 (missing 0) |
| fixed_dual | 8/8 (missing 0) | Not scheduled | Not scheduled | Not scheduled | Not scheduled | 7/8 (missing 1) |
| direct_dual | 8/8 (missing 0) | Not scheduled | Not scheduled | Not scheduled | Not scheduled | 7/8 (missing 1) |
| free_margin | 8/8 (missing 0) | Not scheduled | Not scheduled | Not scheduled | Not scheduled | 8/8 (missing 0) |
| free_continuation | 2/8 (missing 6) | Not scheduled | Not scheduled | Not scheduled | Not scheduled | 5/8 (missing 3) |
| free_ordinary | 6/8 (missing 2) | Not scheduled | Not scheduled | Not scheduled | Not scheduled | 4/8 (missing 4) |

Only **2/18** core task-seed panels have all eight models: irregular/9103 and fsdd/9103. **0/6** tasks have all eight models across all three core seeds. Across the entire matrix, free_dual has only **3/28** eligible searches: selective_copy/9108, irregular/9103 and fsdd/9103. Its multimodal coverage is 0/8, so no full eight-seed, two-task equal-update mechanism comparison exists.

All seven baseline models have complete scheduled coverage. That cannot replace absent free-cell observations or justify a selected-subset comparison as the full planned matrix. This secondary establishes neither an equal-update advantage nor an equal-update deficit for free_dual across the registered tasks.

## Audited artifacts

All 202 eligible searches have independent recomputation of prediction coordinates, labels, argmax, accuracy and cross entropy in `../analysis001/SUPPLEMENTARY_AUDIT.json`. All 244 original selected checkpoint hashes were rechecked and remain unchanged. The same audit preserves every missing search, missing learning rate and actual primary update count.

`SECONDARY128.json` retains eligibility, val-only choices, heldout metrics, original complete-search costs, and training CPU to update128. Per-run `SELECTION.json`, supervised prediction NPZs and summary files remain in `runs/`. Numeric checkpoints are referenced from the original searches and not copied.

## Costs and interpretation

The separate secondary worker used **83.157664 complete CPU seconds**, **83.242755 wall seconds**, and a 369,416 KiB whole-process peak RSS. This includes interpreter/imports, frozen-file/eligibility checks, new heldout inference and writes. These are additional evaluation costs; they are not extra model training.

Every original two-LR search remains fully charged. Training-prefix CPU for a 128-update snapshot is descriptive, not an invented cheaper completed search. Equal update counts would not imply equal CPU time. Neither the snapshots nor this incomplete coverage establish how much of the primary equal-CPU gap is caused by update counts versus other architectural or optimization differences.

The primary 20-CPU-second study and its six-comparison Holm family are unchanged. The complete primary conclusions, tables and limitations are in `../analysis001/REPORT.md`. A later separately registered fixed-update retraining diagnostic, if performed, has its own directory, new computation bill and post-primary status; it does not alter this original **202 evaluated / 42 incomplete / zero new training** result.
