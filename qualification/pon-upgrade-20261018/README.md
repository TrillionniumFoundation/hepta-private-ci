# Retained PoN upgrade observations, 2026-10-18

This directory preserves raw bytes already retrieved from the native host. It is
an evidence retention increment, not a new test run, a successful final-source
qualification, or a repaired implementation-map set. `STATUS.json` records the
precise source identities and unavailable material. Historical results keep their
original source, command, exit code and limitations.

## Retained observations

| Directory under `observations/` | Recorded result and source scope |
| --- | --- |
| `hepta-eb86-native` | Original `eb86cece...` check failure, exit 101, retained with its log. |
| `hepta-1b0-native` | Original `1b0d03ed...` all-targets check, ordinary qualification/recovery, timed holdout/longitudinal tests and native binary builds, each recorded exit 0. These are not runs of later source. |
| `hepta-1b0-bazel-lock` | Original Bazel lock update timed out, exit 124 after 1200 seconds; before/after lock hashes match and the empty patch is retained. This does not satisfy the lock-update gate. |
| `hepta-provenance-full-history` | Original full-history fetch failed, exit 128. |
| `hepta-provenance-filtered-history` | Original blob-filtered history fetch failed, exit 128. |
| `hepta-provenance-commit-graph` | Original tree-filtered history fetch failed, exit 128. |
| `hepta-2c4-explicit-study` | Original `2c4f21bf...` explicit native study metadata/logs and summary, recorded exit 0. The original scope is fixed arithmetic tasks with no full service startup, organizational independence or production qualification. |

The three provenance results do not record a source commit/tree, so this bundle
does not invent one. They preserve transport failures, not proof that any absent
object is a nonancestor. The historical 2c4 summary's `installed_generations=3`
uses that study's original configuration/process-reader scope; it is not evidence
of the subsequently added ordinary Supervisor upgrade study.

## Unavailable full study

The remote manifest describes **1,830 files / 231,521,771 uncompressed bytes**.
The archive `learning-generations-2c4-full-study.tar.gz` is **58,497,445 bytes**,
with its reported SHA-256 in `STATUS.json` and the byte-preserved remote manifest.
At initial packaging, the archive and full original file set were reported
retained on the main native host and the runtime tunnel was disconnected. They
are not included here. That historical observation is not a current availability
claim. Retaining the manifest neither transfers those files nor independently
verifies the remote archive.

## Provenance repair remains blocked

All **19** affected navigation maps remain unrepaired by this increment. The
original checker and all original execution claims remain unchanged. Missing
local history cannot be treated as nonancestry. The reusable preparatory tool,
its original README, existing isolated test source and Lane D fixture patch are
retained under `scripts/qualification/implementation-map-renewal-20261018/`.
Its original README remains a historical review note; paths and then-current
source identities in that note have not been rewritten. Byte-exact received
Python tool/test copies are preserved separately under `received-tools/`; their
manifest entries retain the original `working_script_path`. The earlier report
of five isolated real-Git tests is bound to those received bytes, with no retained
execution log. The scripts under `scripts/` may be formatted as working tools;
that does not create a new test receipt, execution credit or real-map success.

## Byte verification

From the repository root run:

```sh
sha256sum -c qualification/pon-upgrade-20261018/SHA256SUMS
```

`MANIFEST.json` records every retained original file's input path, size and SHA-256.
Each observed native file was checked against its original transport manifest
before copying and then reread byte-for-byte. The two original transport
manifests are themselves preserved unchanged; they also enumerate unrelated
Chain/earlier observations that are outside this deliberately selected bundle.
`SHA256SUMS` covers the selected original files, received tool sources (separate
from the working Python scripts), new status and README, and the independent
manifest. No native tests or format/build jobs were run to package this evidence.
