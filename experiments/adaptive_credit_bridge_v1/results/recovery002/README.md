# Fresh signed-credit formal002 and verified portable archive

This records a new run after the execution environment was recovered. It uses
new local research signing keys and the previously frozen source/model. It does
not restore the lost raw formal001 run, add another efficacy comparison, or
establish organizational independence between the synthetic signer roles.
The original complete adaptive-neuron v2 archive remains separately preserved.

## Verified result

- The original formal002 run and its independent audit passed 16 episodes,
  48 signed facts and 11 fault cases.
- The portable bundle verified 228 sealed source inputs and a partial Git
  object proof at commit `e91a7002bfd650e4a2b057b18b9d81f4242b9ed2`.
- Relocation changed 19 copied JSON files: the two executable paths in
  `INPUTS.json`, the two research-permit `allowed_root` values, and the
  `owner_request` model/calibration paths in 16 terminal records. All other
  copied files and all original raw evidence stayed unchanged. Each change
  has before/after values and hashes in `HOST_PATH_RELOCATION.json`.
- The unchanged frozen auditor passed all 16 episodes and independently
  reconstructed 48 SNN prefixes from the relocated bundle. It verified 88
  evidence signatures and 55 root signatures, rejected the two corrupted
  signatures, and confirmed cold native retries append no new credit or ticks.
- The final tar was then extracted to another directory: all 5,316 regular
  members were verified and its own `REPLAY.py` passed the same complete audit.
  This last check is recorded in `DELIVERED_ARCHIVE_VERIFICATION.json` and
  `DELIVERED_AUDIT.json`.

The archive is 14,120,442 bytes (63,503,635 uncompressed bytes), with SHA-256:

```text
655a25e9c06569213750e0c228eaac565edfbe7f07ee32c11f66e51d57efdc81
```

`ARCHIVE.json` records its local path and manifest identity. The archive contains
the unmodified original run/audit, exact Linux owner and bridge executables,
checkpoint/model, frozen source and Git proof, native Cargo manifests/locks,
verified vendor packages, build receipts, portable audit and export/replay
launch receipts. No archive upload was performed. Large raw evidence and
native binaries are outside Git; this directory contains the small receipts.

After the successful final replay, the two reproducible uncompressed bundle
copies and the incomplete first extraction were removed to reclaim space.
`CLEANUP.json` records the initial sandbox-view removal attempt. A subsequent
read found copies present again; `CLEANUP_FOLLOWUP.json` records their removal
in the live filesystem, followed by a separate call confirming all three copy
paths were absent. The logical bytes in these attempts overlap and must not be
added or interpreted as a measured net filesystem-space gain. The final tar
hash was checked before and after removal. Actual replay/audit outputs,
original raw evidence, frozen source and the final tar remain available.
Re-extract the tar before using a removed bundle path recorded in an earlier
launch receipt.

## Replay and independent extraction

The archive's entrypoint is `credit-portable002/REPLAY.py`. On an environment
matching the frozen Python executable identity and dependency versions:

```sh
python3 /absolute/extracted/credit-portable002/REPLAY.py replay \
  --bundle /absolute/extracted/credit-portable002 \
  --destination /new/replay \
  --receipt /new/replay-launch
```

The Python requirements are NumPy 2.3.5, SciPy 1.17.0 and cryptography 50.0.2.
Python, Git, the Rust toolchain and Python wheels are prerequisites, not archive
contents. The exact environment identity is in the frozen source seal; the
auditor checks it. The bundled executables target Linux, and a different native
platform is not qualified by these receipts.

The repository helper `../recovery_verify_archive.py` additionally checks the
archive SHA, each member and the complete inventory, extracts only regular
files into a new directory, and invokes the delivered entrypoint. Its arguments
are `--archive`, `--archive-receipt`, `--destination`, and `--receipt`; use
absolute paths and new destinations. `../recovery_portable.py` provides the
measured export, replay and package stages. Neither helper changes the frozen
experiment source or the original raw evidence.

## Native rebuild inputs

Both `build/owner` and `build/signed` include an offline Cargo workspace and
vendor tree. Rebuild only a new copy. The qualified compiler is
`rustc 1.95.0 (59807616e 2026-04-14)`, with executable SHA-256
`bff349e72704ff70bc08a234a3847338e797065bbedde5e556808bc87b7bf7c6`.
The frozen build scripts in `source/experiments/adaptive_neuron_v2/owner/build.py`
and `source/experiments/adaptive_credit_bridge_v1/build.py` are the authoritative
recipes. They use `SOURCE_DATE_EPOCH=0`, `CARGO_INCREMENTAL=0`, an isolated
`CARGO_HOME`, the exact `RUSTC`, and these path remappings, adjusted to the new
copy's absolute paths:

| Build | Ordered `--remap-path-prefix` mappings |
| --- | --- |
| Owner | frozen source root → `/research-source`; copied build root → `/research-build`; copied vendor root → `/research-vendor` |
| Signed bridge | copied build root → `/signed-credit-build`; frozen source root → `/research-source` |

The locked commands are `cargo build --offline --locked --release -j 1 -p
codex-hepta-neuron --example adaptive_neuron_host` for the owner and `cargo build
--offline --locked --release -j 1 -p hepta-research-signed-credit-bridge` for the
bridge. The generated manifests and locks are retained, so regenerating them
is unnecessary. Export did not perform another native rebuild and does not
claim a byte-identical result for an unmeasured compiler/linker environment.
Replay uses and hashes the exact supplied binaries.

## Cost accounting

`COSTS.json` includes eight nonoverlapping outer stages, including the failed
first final-extraction attempt. The measured stage totals are 96.787195 seconds
wall time and 82.263409 seconds descendant CPU. The newer launchers separately
record 0.005591 seconds of their own CPU; the three earliest launchers did not
measure that component. Inner native RPC/build/audit/retry measurements are
explanatory and must not be added to their enclosing stage costs. Original v2
training and its owner build are reused evidence, not newly incurred costs.

`credit-delivered-launch002` failed with `ENOSPC` while writing a partial
extraction, before invoking the auditor. Its failure log and cost are retained.
After space was freed, `credit-delivered-launch003` completed the full final
extraction and replay. No failed attempt was overwritten or hidden.

These intervals include the worker interpreter startup and all descendants,
but exclude the outer launcher's own interpreter startup. They describe the
listed experiment/export stages, not the whole interactive session or CI
compilation. No energy in joules was measured. The fresh formal run reports
actual owner ticks, SNN work and signed/native RPC work in
`ORIGINAL_FORMAL_SUMMARY.json`; validation/retry work remains separately visible.
The subsequent storage cleanup is measured separately in `CLEANUP.json`
(0.462544 seconds wall and 0.417621 seconds self CPU); it is not a further
experiment. The live-filesystem follow-up additionally records 0.299863 seconds
wall and 0.299354 seconds self CPU. The nested final-replay launch streams are preserved under
`launches/nested-delivered-replay003` and are already included in the successful
final extraction/replay outer stage.
