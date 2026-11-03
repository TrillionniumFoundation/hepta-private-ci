# Capacity development record

Date: 2026-10-26. These are development results, not frozen-protocol qualification results.

## Execution identity and limits

Two complete development runs are retained:

| Directory under `results/development/` | Development seeds | Vector codebook ceiling | Model records |
| --- | --- | --- | --- |
| `capacity-8011-8017` | 8011, 8017 | 64 cells | 320 |
| `capacity-8011-8017-vq256` | 8011, 8017 | 256 cells | 320 |

Both summaries deliberately record `development: true` and `source_commit: development-unfrozen`. Neither run captured an immutable, complete source snapshot at execution start. Code was still being developed, including extraction of capacity I/O helpers into a separate module. Consequently, these runs cannot be retrospectively attributed to the parent research commit, a later source-freeze commit, or a claim that today's exact source bytes produced every historical development output.

The parent research commit identifies the restored repository ancestry. It is not the executed identity of these uncommitted v3 experiments. Stored model digests, source digests, archive sizes, query requests and answers remain inspectable development evidence. They do not repair the missing historical source snapshot. Formal results must come from the unified runner's independently retained source identity, source snapshot, protocol, environment and evidence seal.

The first run's original files remain unchanged. Its nested VQ selection receipt used the temporary generous allocation limit, while the top-level `budget_bytes`, serialized `artifact_bytes` and actual feasibility check used the intended comparison budget. That receipt-label defect was fixed before the second run. Formal conclusions must use the frozen run, not the old nested receipt.

## Why the VQ baseline changed

The first implementation limited all codebooks to 64 cells. On the Digits pixel task, that used only 18,264 bytes under a 57,504-byte deployment ceiling. A stronger codebook could spend more of the available budget. Development therefore increased the maximum to 256 cells and added the largest feasible codebook at each budget, alongside the predeclared powers-of-two candidates.

`FactorBank` already stored the cell count in an unsigned 16-bit header and packed route bits. The extension uses all eight route bits and supports cell identities 0 through 255; it also updates the maximum-artifact size bound. A real 256-cell fit, serialization and reload test verifies the endpoint. This changes no IntegerBitCell native Q12 contract.

The stronger codebook added actual candidate fitting and maintenance work. The maximum number of additional global-control fits increased from 256 to 1,024 so that the control could cover the larger measured work and fitting-time floors. This is a development baseline correction made before formal evaluation; no formal hidden-query result was used to make it.

The ceiling remains finite. These experiments compare declared model families and budgets; they do not prove superiority over every possible codebook size, optimizer, encoding, or single function.

## What is being measured

All numeric facts are supplied at write time. Training stores them through low-rank integer factors and explicit row routes. The held-out objects are read coordinates and architecture-selection queries, not previously unseen facts. This is a memory experiment, not forecasting or ordinary train/test prediction.

The comparison families are global centered SVD, predeclared local partitions, seeded random local partitions, learned k-means local partitions, and learned rank-zero vector codebooks. Local ranks are selected by an exact byte-budget knapsack using only selection-coordinate squared error. Hidden coordinates do not select ranks or partitions. Factor fitting itself legitimately sees every written fact.

The common precision is int16 factors and decoder weights with int32 centers. Every record latent, decoder, center, packed row route, availability mask, artifact header, source address and provenance record is charged. Budgets are common upper limits; actual occupied bytes can differ because whole-rank increments have different costs. For example, under a 1,662-byte ceiling the sunspot global model uses 1,232 bytes and the learned local model uses 1,652 bytes.

Pure parameter reads occur in a new Python process supplied only with serialized models, digests and row/column coordinates. It receives no original values, residuals, exact archives or training closures. It performs the actual integer-factor readout.

Exact replay is a separate mode. Its residual archive is bound to the complete model digest and reconstructs the canonical int32 source, including the availability mask. An external-model archive charges the referenced model once. It is not described as pure parameter recall. The controls actually encode and decode all 12 combinations of int32, packed offsets, row deltas or column deltas with raw, zlib or LZMA storage.

## Selected development observations

The following table uses seed 8011 from the stronger VQ run. Distortion is hidden-query MSE in the source's scaled integer units. The full summary retains both development seeds and every budget.

| Written source | Deployment ceiling | Global SVD MSE | Learned local MSE | Learned VQ MSE |
| --- | ---: | ---: | ---: | ---: |
| NOAA CO2 | 402 B | 573.012 | 231,211.914 | 287,656.277 |
| NASA temperature | 876 B | 61.932 | 84.920 | 109.602 |
| SILSO sunspots | 1,662 B | 42,981.934 | 35,679.348 | 41,433.336 |
| Digits pixel recall | 57,504 B | 3.334 | 2.295 | 4.084 |

The learned local sunspot model reduced hidden MSE by about 17% at this budget on both development coordinate splits. CO2 and temperature did not show the same advantage. Digits is a different memory task on an already used source; it is not a new independent domain. Its strengthened low-budget VQ comparator actually uses 57,257 bytes and 210 codebook cells.

For the declared synthetic local-subspace source, a 3,072-byte ceiling produced zero hidden distortion with the predeclared 2,260-byte local model, versus global SVD MSE 332.785. The learned partition had MSE 0.015625 at 2,996 bytes and reached zero at 3,096 bytes under the next budget. This is evidence that suitable local structure can matter. It does not establish an advantage on every source.

The exact-storage comparison includes common address/provenance metadata:

| Case | Model plus explicit residual and metadata | Strongest exact control and metadata | Interpretation |
| --- | ---: | ---: | --- |
| CO2, rank-one archival candidate | 2,361 B | 2,426 B | Small development saving: 65 B, about 2.7% |
| Temperature, best global archival rank | 3,182 B | 2,822 B | No compression advantage |
| Sunspots, best global archival rank | 6,530 B | 5,966 B | No compression advantage |
| Pure local-subspace synthetic source, best selected local family | 2,859 B | 6,036 B | Substantial saving on the declared structured source |
| Fully random synthetic source, best selected parameter candidate | 10,464 B | 7,466 B | No compression advantage |

The global archival-rank search and the selected local-family search are explicitly separate candidate sets. All candidates and their actual encoding work are retained in the receipts. A center-only archival winner can be a useful residual transformation, but does not demonstrate that a rich memory was learned in model weights.

For the fully random 256-by-24 source, a full-rank parameter model needs 13,564 bytes before common metadata; the strongest exact archive needs 7,135 bytes. The random alphabet contains 401 symbols, so comparing only against a 32-bit integer array would overstate compression. Small parameter models retain nonzero distortion. No claim of universal compression of independent random facts follows from these experiments.

## Work, retention and verification

The stronger development run executed 32,399 factor or control fits, including 22,845 SVD calls and 16,987 additional global-control fits. All 256 same-work controls met their declared SVD-work and fitting-time floors. Closed-form repeated SVD is charged as actual work and is not relabeled as independent learning or additional learning progress. K-means distance terms, SVD work proxies and measured wall time remain distinct; the proxies are not hardware FLOPs or currency.

The run reported approximately 60.70 seconds total wall time and 60,775,764 retained output bytes before the summary itself. Those retained research artifacts include alternatives, candidate receipts and query-answer evidence. They are counted separately from the minimal state of one deployed configuration. Original repository source files and the broader unified run are additional retained research material and must be included by the final evidence inventory.

The following independent tests passed together before the source freeze: 4 IntegerBitCell tests, 5 FactorBank tests, 3 codec tests, 2 allocation/k-means tests and 1 complete isolated-process capacity-runner test. They cover actual training, native integer rounding, parent inheritance, malformed-artifact rejection, missing-value refusal, all exact codec round trips, residual/model binding, 256-cell routes, allocation agreement with exhaustive enumeration, and fresh-process reads without an inherited `PYTHONPATH`.

No v1/v2 frozen source or historical result was changed. Development improvements do not convert a historical failed gate into a pass. Broad general-memory capability, arbitrary language memory, universal structural advantage and complete weight unlearning remain outside these capacity observations.
