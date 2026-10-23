# Memory population: publication closure and later CI evidence

This supplement preserves events after the [frozen three-seed evidence bundle](../20261023-memory-population/README.md). It does not rewrite that bundle, its 955 original raw files, the experimental source, or any scientific gate.

## Complete original archive published

The original **2,751,996-byte** gzip was successfully stored by the root publication call. [The actual returned receipt](archive-upload-confirmation.json) binds Git blob `bb871e1407f842f23817e978fcbc387c09a00e45` and SHA-256 `67b8c7bcdd4f3405188dfb6afd8e8b36cb17252a48dc74502afa2b29702b3b55`.

The main evidence directory contains the complete original ten-file bundle. **No transport parts or reconstruction step are required.** Its unchanged verifier can be run directly there:

```bash
python -B tools/assemble_evidence.py verify --bundle .
```

Earlier whole-blob and part attempts did not return confirming receipts during bounded waits and were interrupted. Alternative transport manifests, recovery helpers and actual round-trip validations were prepared as contingencies. Their records remain in this supplement's raw archive; they were superseded by the successful whole-object upload. No connector size limit, permission error or precise cause is inferred from those waits.

The repository's 512,000-byte default is unchanged. The entire original archive passed the unmodified size checker with one exact-path exception. Its complete byte count and hash remain explicit in `.github/blob-size-allowlist.txt`; no wildcard or threshold increase was introduced.

## Growth hosted CI now verified

[Run 39920456698](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/39920456698), on exact source `2b42a265e51ad2ac0d2127e8f6b81cc4fa4d1b3b`, completed successfully. Its only job, `120304154416`, ran from **2026-10-23 11:06:01 to 11:08:16 UTC**.

The [independent CI receipt](growth-ci-verification.json) checks the actual API records, complete job log, original 8,590-byte artifact, all 82 named test IDs, 33 Python source hashes and two fixture hashes against the exact Git revision.

| Actual suite | Distinct tests |
| --- | ---: |
| Parametric memory | 27 |
| Catalog | 6 |
| Growth | 6 |
| Owner admission | 7 |
| Existing evolution | 22 |
| Process inference | 14 |
| Total within this run | 82 |

These tests overlap other suites. They must not be added to the final population's 73 tests as an independent total. This run is `SHADOW_ONLY`, with `full_growth_confirmation_executed=false`, `pretrained_model_download=false`, and `production_activation_allowed=false`. It closes this source's hosted mechanism-verification wait, not a new pretrained study or production admission.

## Remaining observed CI queues

The [five-run observation](key-ci-observation.json) was recorded at **2026-10-23 11:50:32 UTC / 07:50:32 America/New_York**. It is not a new full 36-PR snapshot.

| Run | Source | State |
| --- | --- | --- |
| Growth `39920456698` | `2b42a265...` | Success |
| Catalog repair `39939320934` | `9d0473ff...` | Queued |
| Architecture `39932441732` | `07df4a9c...` | Queued |
| Blocking CI `39932441833` | `07df4a9c...` | Queued |
| V8 canary `39932441722` | `07df4a9c...` | Queued |

[Draft repair #3489](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3489) fixes the catalog workflow's missing `packaging==26.3` dependency and adds only the exact repair-branch trigger. Local smoke and six catalog tests passed; this table does not claim that hosted repair validation has run. The original import failure, with zero catalog business tests executed, remains preserved.

Both final population hosted runs already passed the same 73 distinct tests. Research conclusions remain unchanged: the primary int8 checkpoint storage/quality gate passed; matched-budget fission, learned-routing advantage, heterogeneous retention/transfer, net system compression and general memory were not established. Production acceptance remains false.

## Original bytes and verification

`raw-updates.tar.gz` preserves the original later CI responses/logs/artifact and publication-attempt records. `raw-updates.manifest.json` lists every original member's size and SHA-256, as well as excluded temporary index / unused alternate-compression files. The embedded manifest is byte-identical to the external manifest. `archive-verification.json` records the actual complete reopening and member-by-member byte comparison. The original study archive is a separate immutable object, not regenerated here.

`checksums.json` binds all files in this supplement except itself. The main study bundle's original verifier remains limited to its own exact ten-file inventory.
