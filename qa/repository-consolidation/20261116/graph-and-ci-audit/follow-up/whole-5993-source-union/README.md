# Whole 5993 source union: original native evidence

This bundle preserves the actual preparation, failed first run, repaired run, and independent composition compilation for the reviewed ordinary parent `5993cb909547070e4b56ca9465996a5a946fafca` against `eeefbc864e6a254e9085d542c1e6c3647e1c881d`.

## Executed scope

The five original package commands cover Supervisor, Intelligence, Control Plane, Infer Worker Host, and Automation. The final selected source commit is `260fea2afad401f4ad87edf2f6eb2281829f5b44`, with selected tree `e99c03a587ba40ef7f10bd3d842219492f00c03d`. All 14,021 selected inputs remained unchanged during the final test run.

- The first complete run executed 779 tests: 778 passed and one failed. Ten tests were excluded by the original selection. The failing fixture supplied two identical snapshots while expecting a mixed-snapshot rejection.
- The repair changes one value in the second test snapshot. Production behavior and the existing assertions remain unchanged.
- The final complete run passed all 779 executed tests. The same ten original selection exclusions remain; they are not JUnit skipped test cases.
- Four original NDU counterexamples were executed against the old production implementation. All four failed as expected. Their raw output and same-execution JUnit are retained.
- After composition with the separately verified Neuron arity repair, the original scoped `just fix --locked` command passed across all six affected packages with 14,022 unchanged inputs. This is compilation and static-check evidence. Neither the 779-test run nor the separate 399-test Neuron run was repeated in that step.

The original nextest configuration remains in force, including its default and explicit per-test time limits. The test commands use four test threads, zero retries, and the original 8 MiB Rust thread stack. These records do not establish whole-workspace strict-warning qualification, native Windows qualification, deployment authority, or scientific performance qualification.

## Failures and collection correction

Preparation attempts retain the original missing-format-base failure, failed automatic fix diagnostic, and later clean maintenance results. The first test collector used the wrong JUnit directory. A subsequent collection-only step matched the actual JUnit run UUID to the original raw log and checked the source inputs. It did not rerun either test command. Both the original failed collection flags and the corrected receipts are included.

## Lossless recovery

There are 124 original files represented by 102 unique SHA-256 objects. Every source path, byte count, and digest is listed in `originals-manifest.json.gz`. The archive also contains the exact uncompressed manifest.

1. Read `carrier-index.json` and verify each compressed part against its recorded size and SHA-256.
2. Decompress each part independently, verify its raw size and digest, and concatenate the raw bytes in `rawOffset` order.
3. Verify the complete tar stream against `tarBytes` and `tarSHA256` in the index.
4. Resolve every original file to `objects/<sha256>` in that archive. Check every original size and digest before restoring it to a chosen destination.

All 38 parts and all 124 original files were independently restored and checked on the receiving host. The exact receiving-host report is retained in `desktop-restore-result.json.gz`. No original failure log was replaced by a summary.

The immutable carrier index SHA-256 is `53f62e17e4d3b6b6acbf1fed73203d47b9953a8323d0d225526772058624439a`. The complete raw tar SHA-256 is `023602f997dfbbc4d6c9e96e9753e755832ca388ebdf2bceb0c0c8ce8ac6ff2c`.
