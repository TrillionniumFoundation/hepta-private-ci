# Raw sample-statistics admission audit

The raw sufficient-statistics ledger at parent `4686c861e54179690c4a668a356a4b0ce57639d5` accepted two invalid contributions during this audit:

1. A contribution declaring one observation supplied an identity Gram over five features and an identity `yTy` over two outputs, with zero cross-products. The augmented Gram had rank seven. It was admitted and produced a candidate despite being impossible to obtain from one observation.
2. A contribution containing string-valued Gram entries was admitted through float coercion and produced a candidate, while the lossless binary codec refused those same bytes. The resulting ledger could contain contributions that the binary peer could not propagate.

`BASELINE.json` preserves both actual pre-fix observations and candidate objects. These are synthetic diagnostic inputs. No historical training or held-out sample was consumed.

## Repair

Admission now requires exact nested-list dimensions and plain finite Python floats, matching `make_packet` and the lossless binary representation. Numeric strings, booleans, integers, tuple matrices and malformed dimensions are rejected before opening the write transaction.

For raw sample rows `Z = [X Y]`, the augmented matrix is `Z.T @ Z`, hence its rank cannot exceed the number of declared rows. Admission checks this necessary condition using the existing `1e-10` spectral tolerance. The check uses a scaled copy, preventing overflow when symmetrizing finite values near `1e308`. The original admitted matrices are returned unchanged; the solver, ridge objective, aggregation order and candidate encoding are unchanged.

This enforces a necessary algebraic property of the existing raw-statistics contract. It does not prove that the claimed observations occurred, authenticate a user or teacher, verify helpfulness, or detect valid-looking poisoned examples. Rank below the declared tolerance remains numerically indistinguishable from zero. Existing databases containing previously accepted malformed contributions are rejected on snapshot rather than silently rewritten.

## First local regression

The execution source was frozen in local commit `2635b33c399` before invoking the original source-bound regression driver. The driver checked its exact HEAD and clean source before and after the run, archived executed sources, and used Python 3.12.14 / NumPy 2.3.5 with one BLAS thread.

| Suite | Actual tests | Failures / errors / skips |
|---|---:|---:|
| Ledger, including three new mathematical/representation controls | 7 | 0 / 0 / 0 |
| Lossless codec | 5 | 0 / 0 / 0 |
| JSON peer | 4 | 0 / 0 / 0 |
| Binary peer | 4 | 0 / 0 / 0 |
| Total | 20 | 0 / 0 / 0 |

The driver reported 8.746247459 seconds. This is regression-driver wall time, not model-training time or a performance comparison. All original seventeen controls remain present. The new controls cover rejection before mutation at three scales, both packet representations, exact matrix types/shapes, zero statistics and fifteen genuine row-statistics combinations with one to thirteen observations.

`LOCAL_RESULT.json` contains the full driver result. `local-execution.tar.gz` contains the source/runtime freeze, complete suite logs, process controls and outputs. `ARCHIVE.json` records its exact bytes and SHA-256.

## Formatting and integration

After the regression, the repository's original `just fmt --base 4686c861e54179690c4a668a356a4b0ce57639d5` returned zero and reported no changed files in its configured scopes. The qualification Python files are outside those scopes. Ruff 0.15.13 then formatted the three changed Python files; two changed layout and one was unchanged. `FORMAT.json` binds the before/after file digests and exact AST equality. The tests were not rerun after formatting.

The hosted workflow and driver now name twenty controls. This local result does not claim execution on the hosted Python 3.12.3 target. Remote publication and that run retain their own commit identities. This stage adds no scientific training, learned Circuit evidence, A-to-B adoption, useful-work reward or Chain settlement.

## Integration with the latest received-offer implementation

The later stage normally merges exact #7212 head `6e60365410d825778bb16b759af893985db97a6b`, including #7211's single receiver validation and transactional capacity check. The earlier twenty-control execution and all its records remain unchanged. The current gate contains **24 controls**: eight ledger, five codec, four JSON peer, four binary peer and three admission controls.

Further finite-input probes found two numerical failures, retained in `OVERFLOW_BASELINE.json`. With one real row `X = Y = 1e154`, the Gram and ridge penalty were each `1e308`; their sum overflowed and the former solver exported weight zero, although the real-arithmetic solution is 0.5. Separately, two individually finite target-statistics batches accumulated `yTy = inf` while still exporting a candidate. Finite input entries alone did not protect the subsequent arithmetic.

The pooled solver now explicitly refuses an overflowing regularized Gram. Snapshot refuses overflow in any of the three accumulated matrices. The ordinary finite path retains the same arithmetic and objective. The new control also accepts a large finite solve with weight `10/11`. These are numerical-domain refusals, not newly invented feature ranges: the current contract binds a normalization digest but specifies no executable raw-feature clipping or min/max bounds. Individually valid extreme batches remain in their immutable ledger if their aggregate overflows; snapshot refuses to export, without erasing accepted history. This does not prevent valid-looking poisoning or denial of service by authenticated-looking declarations.

The first integrated regression used exact clean source `6500e89fd7f60ea248e38a3e649983dca35f2bcc`, Python 3.12.14 / NumPy 2.3.5 and one BLAS thread. All **24/24** controls passed, with zero failures, errors or skips; outer process wall time was **7.993423588 seconds**. The three latest admission controls retained one full validation and eigendecomposition per received offer, full receipt equality to the original observed reference, and refusal of the second overlapping capped writer. The unsafe historical baseline was not rerun. This is a necessary integration regression, not a timing comparison with the first twenty-control run.

`MERGE_PROTOCOL.json`, `MERGE_RESULT.json`, `MERGE_FORMAT.json`, `MERGE_ARCHIVE.json` and `latest-admission.tar.gz` preserve the distinct scope, original results, executed source, runtime, all suite logs and process observations. Official `just fmt --base 6e60365410d825778bb16b759af893985db97a6b` returned zero. Ruff 0.15.13 formatted four changed Python files; two changed layout. All four ASTs remained identical, and no tests were run after formatting. This local integration result supplies no new hosted execution or scientific model result.
