# Fixed-weight crossed-wording routing diagnosis

## Outcome and scope

Run-002 completed once with exit code 0. All 2,904 fresh decoder queries, 1,272 actual trained-parent feature forwards and 2,400 new router optimizer updates completed. Decoder optimizer updates were zero. All original decoder/base/router bytes, historical reports and executed source pins passed the final unchanged-input check.

This is a post hoc development diagnosis on the previously exposed 44-root synthetic capacity cohort. The protocol was frozen before these new reads, but it was designed after the historical cohort failures were known. Fresh outputs do not make the old cohort an independent confirmation set. Scientific Phase 3 remains open; equal total budget, robust capacity advantage, production acceptance and general memory are not established.

Changing router training observations substantially recovered retention relative to the original router. The full crossed-wording router still scored below the single adapter on retention in seeds 2719 and 4051. Its transfer scores were 25%, 21.875% and 0%; its raw unknown correctness was 16.667%, 54.167% and 87.5%. No decoder weight was changed to obtain these results.

## Comparable denominators

Each seed has 64 retention, 32 transfer and 24 unsupported/unknown probes. Retention and transfer count exact generated answers only when source capability permits that expert. Raw unknown correctness counts a router abstention or a literal decoder answer of unknown; it is not parameter-memory accuracy.

The tables below use these same subgroup denominators. Oracle and uniform exclude unknown, so their all metric has denominator 96 whereas the other policies have denominator 120. Do not compare those all metrics. Uniform is the exact expected score across the two measured experts, not a new randomized dispatch run.

All six candidate policy routes were frozen before fresh final decoder outputs. The reported policy scores are selections from one retained per-expert raw matrix. No live policy dispatch was executed. Guarded metrics are counterfactual scoring under the frozen capability rule; they are not a new owner/zero-callback execution test.

### Seed 1907

| Policy | Retention / 64 | Transfer / 32 | Raw unknown / 24 |
|---|---:|---:|---:|
| Original router | 2/64 (3.12%) | 3/32 (9.38%) | 12/24 (50.00%) |
| Full crossed wording | 60/64 (93.75%) | 8/32 (25.00%) | 4/24 (16.67%) |
| Balanced 76-row crossed wording | 59/64 (92.19%) | 8/32 (25.00%) | 5/24 (20.83%) |
| Lexical nearest source | 59/64 (92.19%) | 4/32 (12.50%) | 4/24 (16.67%) |
| Parent-feature nearest source | 37/64 (57.81%) | 6/32 (18.75%) | 12/24 (50.00%) |
| Single adapter control | 45/64 (70.31%) | 11/32 (34.38%) | 0/24 (0.00%) |
| Structured metadata rule | 61/64 (95.31%) | 8/32 (25.00%) | 24/24 (100.00%) |
| Uniform expected routing | 33.5/64 (52.34%) | 4/32 (12.50%) | N/A |
| Eligible oracle | 61/64 (95.31%) | 8/32 (25.00%) | N/A |

### Seed 2719

| Policy | Retention / 64 | Transfer / 32 | Raw unknown / 24 |
|---|---:|---:|---:|
| Original router | 0/64 (0.00%) | 1/32 (3.12%) | 16/24 (66.67%) |
| Full crossed wording | 41/64 (64.06%) | 7/32 (21.88%) | 13/24 (54.17%) |
| Balanced 76-row crossed wording | 41/64 (64.06%) | 9/32 (28.12%) | 11/24 (45.83%) |
| Lexical nearest source | 44/64 (68.75%) | 7/32 (21.88%) | 6/24 (25.00%) |
| Parent-feature nearest source | 32/64 (50.00%) | 7/32 (21.88%) | 10/24 (41.67%) |
| Single adapter control | 43/64 (67.19%) | 7/32 (21.88%) | 0/24 (0.00%) |
| Structured metadata rule | 42/64 (65.62%) | 9/32 (28.12%) | 24/24 (100.00%) |
| Uniform expected routing | 27/64 (42.19%) | 4.5/32 (14.06%) | N/A |
| Eligible oracle | 47/64 (73.44%) | 9/32 (28.12%) | N/A |

### Seed 4051

| Policy | Retention / 64 | Transfer / 32 | Raw unknown / 24 |
|---|---:|---:|---:|
| Original router | 0/64 (0.00%) | 0/32 (0.00%) | 16/24 (66.67%) |
| Full crossed wording | 39/64 (60.94%) | 0/32 (0.00%) | 21/24 (87.50%) |
| Balanced 76-row crossed wording | 31/64 (48.44%) | 0/32 (0.00%) | 21/24 (87.50%) |
| Lexical nearest source | 42/64 (65.62%) | 3/32 (9.38%) | 4/24 (16.67%) |
| Parent-feature nearest source | 41/64 (64.06%) | 0/32 (0.00%) | 18/24 (75.00%) |
| Single adapter control | 40/64 (62.50%) | 2/32 (6.25%) | 0/24 (0.00%) |
| Structured metadata rule | 45/64 (70.31%) | 5/32 (15.62%) | 24/24 (100.00%) |
| Uniform expected routing | 28/64 (43.75%) | 2.5/32 (7.81%) | N/A |
| Eligible oracle | 45/64 (70.31%) | 5/32 (15.62%) | N/A |

## Interpretation and fixed-decoder limits

The full-cross fit uses 304 source observations (256 source-supported and 48 explicitly unsupported operations). The balanced fit keeps 76 observations with the original 64 source-supported / 12 explicitly unsupported operation count, and 16 supported plus 3 unsupported operations per wording. All three retain the same 16:3 operation-category ratio. The actual router reject-target count also includes source-supported questions for which both experts were wrong: original counts are 18/28/30, balanced counts are 16/27/29, and full-cross counts are 68/109/119 for seeds 1907/2719/4051. The effective routing-target distributions are therefore not identical. Both use the original router configuration and 400 updates. Labels come from this run’s actual two-expert generations and capability checks. Full-cross changes observation count as well as wording; the balanced control reduces that confound but does not identify one universal cause of the old failure.

For seed 1907, the original router’s source known accuracy across four wordings was 87.5%, 0%, 35.9375% and 17.1875%; source unknown accuracy under the first wording was 0%. Full-cross source known accuracy was 87.5%–92.1875% across the four wordings, with 100% source unknown correctness. Its final unknown score was only 4/24. Source-set improvement therefore did not establish unsupported-input generalization.

The lexical control improves retention over single in these three exposed seeds. Its transfer score is lower for seed 1907 (4/32 versus 11/32), equal for seed 2719 (7/32 versus 7/32), and higher for seed 4051 (3/32 versus 2/32). The descriptive pooled transfer count is 14/96 versus single 20/96; no independence or significance claim is made from pooling. Its raw unknown correctness is only 4/24, 6/24 and 4/24. It uses retained source question prototypes and measured utility targets. It is not evidence of a purely parametric end-to-end memory system.

Fresh eligible-oracle retention is 61/64, 47/64 and 45/64. The latter two remain below 75%. For seeds 1907 and 4051, the metadata rule already equals the eligible oracle, leaving zero headroom to beat metadata by 5 percentage points on this fixed matrix. No router can repair missing decoder answers while these bytes remain fixed.

Eligible-oracle event interpolation is 5/16, 6/16 and 5/16; procedural extrapolation is 3/16, 3/16 and 0/16. These are decoder/capability limits for the measured matrix. They prevent closing the old transfer gates through router changes alone.

The 28 source dependency groups per seed define grouping, not proven statistical independence. Wordings, shared training and the three seeded synthetic fixtures are correlated evidence. No independent future CI incident, new natural memory dataset, multi-host failure experiment or total-budget-matched capacity study was added by this diagnosis.

## Actual additional work and sunk costs

| Additional diagnosis event | Actual value |
|---|---:|
| Decoder queries | 2904 |
| Decoder input tokens | 185136 |
| Generated tokens | 6156 |
| Parent feature forwards | 1272 |
| Parent feature input tokens | 80544 |
| New router optimizer updates | 2400 |
| New decoder optimizer updates | 0 |
| New gradient forward/backward probes | 0 |
| Fresh decoder worker processes | 27 |
| Fresh feature worker processes | 3 |
| Event wall seconds | 1435.8135474470037 |
| Shared frozen base disk bytes, counted once | 271170520 |
| Artifact bytes before final result | 21166875 |
| Parent process CPU seconds | 4.6674237839999995 |
| Child process CPU seconds | 2541.961509 |

Each seed result retains decoder load/generation wall and CPU, input/generated tokens, feature worker timing and feature bytes, router fit/update/inference work, prototype/index storage, and the complete source/final read receipts. Stage wall values overlap whole-event wall values and must not be summed again.

The additional event shares one source/final expert matrix across policy comparisons; its reads are charged once, not once per counterfactual policy. It is not a per-policy serving benchmark or an equal-TOTAL-budget comparison.

Historical sunk costs are separately retained: 7680 decoder optimizer updates, 192 gradient forward/backward probes and 1200 original-router updates, plus the historical source-selection and final-read receipts. Older codec evaluations are outside this routing diagnosis cost scope. No historical decoder training was repeated here.

## Evidence and preparation state

The bundle includes complete run-002 raw request/stdout/journal/owner records, actual feature matrices and prompts, utility evidence, frozen route plans, source/final assessments and cost receipts. It also includes all 12 historical parent/single/child checkpoints, 3 original router binaries, 201 pinned historical report JSON files and 3 training result JSON files. Inputs were copied byte-for-byte into a relative layout; historically declared absolute paths inside original receipts remain unchanged.

Run-001 contains its five original preparation JSON files only. It was never executed and has no decoder calls, execution-start receipt or result. No old driver-source snapshot was retained at that preparation. This archive does not reconstruct or invent one. Run-002 retains its exact five executed source modules both under driver/ and runs/run-002/diagnosis-source/.

Executed repository HEAD: d61a36e21d1ad6d90614c145455b88c647c430e8. Repository Python source digest: 2d26691648176e8a6101a883654d448516f0c93a5d5add9d105a029e16d51131. Executed diagnosis source digest: f618cc5c165f198e906691f8a84ac80a2ba7f9c5cc6ce3fee596a60370a4e511.

Run-002 result SHA-256: 916d71c43c09a80ccd942bacb63dd4eeace98c66340f67181cafbf3884ddf9a3. Protocol SHA-256: 37b4788f42c6899fe60ee3f85098e9791fdb552126d529c1112e3e178511ab8d.

The frozen 271,170,520-byte HuggingFace base is not duplicated in this archive. Its publisher revision and every file size/SHA are retained in runs/run-002/base-acquisition.json; the fixed acquisition tool is included in the repository source snapshot. All trained adapters needed for this diagnosis are included.

See REPRODUCE.md for explicit portable paths and a new prepare/execute workflow. MANIFEST.json records every included member before the manifest itself. Archive and chunk checksums are provided beside the compressed bundle.

## Published readable source

The five formatted publication copies are included under publication-readable-source/. The exact executed originals remain under driver/ and runs/run-002/diagnosis-source/. publication-notes/ retains the before-format AST inventory and the formatter equivalence receipt; all five copied files were independently checked against those hashes and ASTs during packaging. Formatting was not a new model run and did not change the archived protocol or results.
