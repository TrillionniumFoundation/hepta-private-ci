# V10 fixed comparison

This is a finite authored inventory experiment with frozen MiniLM representations and learned affine heads/residuals. It does not fine-tune a Transformer or establish a general memory system.

Three declared optimization seeds are descriptive replications, not independent real-world task distributions. Every held score below comes from a process launched after all fit workers exited.

## Content at oracle canonical addresses

| Capacity | Type | Independently trained linear | Rank-4 residual | Untrained | Exact SQL |
|---:|---|---:|---:|---:|---:|
| 32 | semantic | 43.75% | 87.50% | 0.00% | 100.00% |
| 32 | procedure | 98.96% | 100.00% | 0.00% | 100.00% |
| 64 | semantic | 4.17% | 35.42% | 0.00% | 100.00% |
| 64 | procedure | 51.56% | 80.73% | 0.00% | 100.00% |
| 128 | semantic | 2.60% | 7.81% | 0.00% | 100.00% |
| 128 | procedure | 19.79% | 50.52% | 0.00% | 100.00% |

## New typed combinations

All learned composition arms receive the same pair features, target groups and exact row schedule. Typed and block-head joint have equal parameter counts; dense joint is larger and charged separately. The SQL planner retains the same information and uses the same bounded interpreter.

| Capacity | Arm | Exact non-held execution | Both stored parameter values exact |
|---:|---|---:|---:|
| 32 | typed | 98.33% | 94.79% |
| 32 | joint | 3.89% | 1.04% |
| 32 | dense_joint | 1.67% | 0.00% |
| 32 | exact_sql | 100.00% | 100.00% |
| 64 | typed | 61.11% | 29.95% |
| 64 | joint | 3.89% | 0.26% |
| 64 | dense_joint | 3.33% | 0.00% |
| 64 | exact_sql | 100.00% | 100.00% |
| 128 | typed | 22.31% | 4.17% |
| 128 | joint | 1.52% | 0.00% |
| 128 | dense_joint | 1.24% | 0.00% |
| 128 | exact_sql | 100.00% | 100.00% |

## Addressing on unseen wording and unknown requests

Known coverage is `known_accepted / known_count`. Precision among accepted known requests is `known_correct_accepted / known_accepted`; it is undefined (NA) when no known requests are accepted. Correct known acceptance is `known_correct_accepted / known_count`. Counts are pooled across seeds before forming these ratios; unknown acceptance is reported separately.

| Capacity | Router | Known accepted / total | Known coverage | Accepted-known precision | Correct known acceptance | Unknown acceptance |
|---:|---|---:|---:|---:|---:|---:|
| 32 | oracle | 768/768 | 100.00% | 100.00% | 100.00% | 0.00% |
| 32 | deterministic | 768/768 | 100.00% | 100.00% | 100.00% | 0.00% |
| 32 | learned | 2/768 | 0.26% | 50.00% | 0.13% | 0.00% |
| 32 | nearest | 0/768 | 0.00% | NA (no accepted known requests) | 0.00% | 0.00% |
| 64 | oracle | 1536/1536 | 100.00% | 100.00% | 100.00% | 0.00% |
| 64 | deterministic | 1536/1536 | 100.00% | 100.00% | 100.00% | 0.00% |
| 64 | learned | 11/1536 | 0.72% | 54.55% | 0.39% | 0.78% |
| 64 | nearest | 0/1536 | 0.00% | NA (no accepted known requests) | 0.00% | 0.00% |
| 128 | oracle | 3072/3072 | 100.00% | 100.00% | 100.00% | 0.00% |
| 128 | deterministic | 3072/3072 | 100.00% | 100.00% | 100.00% | 0.00% |
| 128 | learned | 3/3072 | 0.10% | 100.00% | 0.10% | 0.13% |
| 128 | nearest | 0/3072 | 0.00% | NA (no accepted known requests) | 0.00% | 0.00% |

## Lifecycle and promotion

No split or merge is promoted. Gradient-driven children, fixed experts, rank expansion, merge distillation and release/reload are retained as candidates with exact checkpoints. Structural worded reads use the true registry address to select saved cluster membership, so these results are conditional on oracle addressing. A closed cost-completeness gate prevents a quality result from being relabeled a full lifecycle win.

The compatibility arm name `reservoir16` means 16-record replay sampling: each ordinary cycle samples 15 records afresh from the full active list and includes the corrected or inserted record. It does not model a persistent streaming reservoir. Both arms rebuild on all retained records after deletion.

| Seed | Maintenance arm | Final retained correct | Worst-cycle retained correct | Deleted/stopped reads entered model |
|---:|---|---:|---:|---:|
| 1741 | full_replay | 25.40% | 20.63% | 0 |
| 1741 | reservoir16 | 25.40% | 20.63% | 0 |
| 1742 | full_replay | 12.70% | 12.70% | 0 |
| 1742 | reservoir16 | 12.70% | 12.70% | 0 |
| 1743 | full_replay | 30.16% | 17.46% | 0 |
| 1743 | reservoir16 | 30.16% | 17.46% | 0 |

## Cost accounting scope

Completed child processes before report generation: 20. Sum of non-overlapping child wall scopes: 132.978 s. Child CPU: 132.878 s. Peak cumulative child RSS: 524976 KiB.

The process ledger includes encoding, fitting, checkpoint I/O and fresh evaluation. Per-fit receipts are nested measurements and must not be added again. Pipeline timing includes reference lookup and evidence serialization, so it is not isolated serving latency. Artifact inventory separates weights, source database, feature caches, schedules and retained history. Package installation, uploads, external host execution and energy are not measured here; no complete lifecycle cost advantage is claimed.

Read-arm order uses only offsets 0, 1 and 2 of six arms across the three seeds. This partial rotation does not fully counterbalance order effects.

Python deletion guards and explicit array release/reload are research mechanisms. Durable owner source authentication, true control sockets, live source invalidation and process stops are established only by the separate native integration evidence. Historical files remain for audit; service revocation and clean rebuilding do not imply physical erasure of all historical information.
