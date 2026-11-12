# Peer review: pinned runtime restoration preparation, v2

Status: **reviewed for the proposed preparation operation, with one narrow terminal-observation annotation requested and accepted by Root**. This is a source review only. This reviewer did not run the driver, install tools, change source files, invoke Cargo or update any Git ref.

## Exact reviewed inputs

- Repository: `TrillionniumFoundation/hepta-private-ci`.
- Runtime restoration v1: Git blob `30e5471e271fd70cdd0e0a85155992b5d7584aee`, 44,146 bytes, SHA256 `6bbbab7250c433569089d6aa66cff467eeba9fe21c17c5b8289d89ec62132f7c`.
- Runtime restoration v2: Git blob `fcf4acc9b6f37e2cfc70998bf5c23b3a70d6bae4`, 44,672 bytes, SHA256 `73453f98eb3c7b8cb6066097984f6a198b5fb6c19faa505ac4638c25c3d8df1e`.
- Exact v1-to-v2 patch: Git blob `4f16a0da6acc387dfe8a7b3f521da655a5aa501f`.
- Original command executor: `scripts/hepta_ci_exec.py`, Git blob `c9434b3a4afb31f80e323d543936386a2fa738de`, 12,863 bytes, SHA256 `9b2bfaa563fff018df4e4f10944f6fbc63d307fa4c4a7e167c392288edb5a5c1`.
- Original complete-source inventory implementation: Git blob `51181866cbbb6e0176aab04117efffa8b6792b31`, 22,946 bytes, SHA256 `20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2`.
- Frozen dependency plan: Git blob `8936bfb0e0dbab9e471a158f1161567273798360`, 17,795 bytes, SHA256 `22b85535cbb1d079c8dd698d8827122b439c964672fce7d182726783a0fb2ec6`.

Both complete driver texts, including the full preflight function, were read. The v2 text was independently checked against its byte count, SHA256 and Git blob identity. The whole v1-to-v2 patch was read.

## Preparation boundary

The driver admits only the materialized source at commit `86dd56a930277e0d1aef3e475e35c2b5d60b43b7`, tree `383ab85c39ef9d848252ef5c25922d13d9fae6c6`, with ordered parents `c0f78493f815780f68b9bf5e390a21314d79311f` and `a96d1b821d10ed3d9e99dd06c5141f9f242ae318`. Its complete physical-source pin is 5,611,182 bytes, SHA256 `bca1a7399820966d3167a26f89355898a9ea9a7169938ffa27e7dd9576fc1711`, Git blob `e7efbbc915cf80db9f873a2b5f9bf162daf4308c`.

The source directory is `/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1`. Runtime files are confined to the new depot `/data/hepta-utility-36fa-runtime-materials-86dd-v1` and the explicit dedicated target `/data/hepta-utility-36fa-final-native-target-v1`. Existing output/depot identities cause refusal; the driver does not rename, clean or automatically retry them.

The operation has its own 600-second preparation budget, 180-second final-evidence budget and 900-second outer budget. It runs neither maintenance nor tests. These budgets do not replace or extend any source, training, evaluation, compilation or test gate.

## Findings resolved by v2

### Original executor owns command termination

The original executor owns its subprocess group, timeout, kill/wait handling and final output flushing. A competing wrapper SIGALRM could previously interrupt that cleanup.

V2 disables the wrapper timer before entering the unchanged `execute_logged` call. It keeps that timer disabled while retaining the original raw output, forwarded output and command JSON. It then restores the remaining preparation timer and explicitly checks the remaining overall budget. Each original command still receives `min(requested_timeout, remaining_operation_time)`; no command receives a longer stage budget.

This resolves the identified competing-timer risk in the reviewed command path. The review does not assert that arbitrary OS or storage failures are impossible.

### Existing /data parent is not required to be owned by this user

V2 checks the existing parent as a real, non-symlink directory with actual write/search access. The newly created depot and dedicated target retain their own current-user ownership requirements. The change removes an unnecessary parent-ownership assumption without relaxing the ownership of newly admitted writable state.

## Other reviewed boundaries

### Source and control preservation

The original inventory is run over the complete source before and after preparation; the source pin must match, including all 15,188 physical leaves. HEAD, index, config and refs are separately observed and compared. The fresh source is required to have no alternates, shallow file or graft override.

All admitted control files and source dependency inputs are pinned and reread. In this dependency-restoration operation, source files are immutable: no legitimate source formatting is expected. This differs from the later maintenance wrapper, where source postimages must be recorded separately from immutable controls.

The Git comparison is explicitly limited to HEAD/index/config/refs and the complete source inventory. It does not assert whole historical Git fsck success or complete donor-object-library immutability.

### Downloads and extraction

The six roles are drawn from the exact frozen dependency plan. Requests preserve ordinary TLS/proxy/CA verification. Reviewed URLs cannot contain credentials or dynamic queries; redirects are bounded and restricted to the allowlisted HTTPS hosts. Redirect query strings are removed from recorded destinations. Downloads are create-only and are bounded by the exact expected byte count, SHA256, individual deadline and shared operation deadline. Partial files and errors are retained instead of silently retried.

The UV archive is bounded by entry count and uncompressed size. It rejects link/special entries and non-relative/traversal names. It extracts only one bounded regular ELF named `uv` into a fixed destination; it does not expand archive member paths into the filesystem. The official archive byte pin is checked before admission. The actual extracted executable must report UV 0.11.3.

The Ruff wheel is an exact pinned archive with bounded unique relative member names and exact name/version metadata. Its metadata must declare no additional runtime requirements. The script does not implement a separate wheel extraction path: the admitted UV executable installs the named locked requirement into the new external venv.

### Environment and original offline check

The historical environment is preserved except for the reviewed explicit external PATH, V8 paths, Cargo target and UV/Ruff settings. `UV_OFFLINE=true` and `UV_PYTHON_DOWNLOADS=never` prevent an interpreter/network fallback. Existing proxy/CA environment values are preserved and are not disclosed.

The existing `/usr/bin/python3` is verified and used. `CODEX_REPO_ROOT` and `PYTHONPATH` are observed separately rather than guessed or rewritten.

The bootstrap creates an external venv, then installs the named `ruff==0.15.13` requirement using `--offline --no-index --find-links` against the single verified wheelhouse. It subsequently executes the original frozen project check, the original frozen `uv run ... ruff --version` path, and the same frozen/offline check again. The direct-URL/provenance substitution proposed earlier is not executed.

Final admission rechecks actual material/tool bytes and metadata, external directories, explicit environment and preserved proxy/CA policy. An `ENVIRONMENT_READY.json` record is preparation evidence, not a test or deployment qualification. Consumers still require the actual complete RESULT and normal complete supervisor outcome.

## Narrow terminal-observation supplement for v3

The v2 command row records an exception if the executor fails to return, but it does not explicitly distinguish an unobserved original command terminal from the wrapper's known preparation failure. Root accepted the following small annotation:

1. Initialize each command row with `original_command_terminal = "unknown_not_observed"`.
2. Change it to `"observed"` only after the unchanged original executor returns its complete result.
3. Preserve actual returncode, timeout and output-limit fields exactly. Do not synthesize a returncode when the executor did not return.

The wrapper may continue to report `FAILED_PREPARATION` for its known failure; the original command terminal remains separately Unknown when absent. A definite HTTP or checksum failure is still recorded as a definite preparation failure. This is an evidence-description correction, not a new execution branch, retry, budget or task-outcome interpretation.

No other blocking issue was found in the assigned source-preservation, extraction, environment, offline-check and cleanup review. The final v3 identity still needs its small diff checked before the Root-authorized native launch. Artifact version and checksum selection are independently reviewed by the other reviewer.

## Limits

This report is static review. It does not establish that the downloads, UV resolution, external environment or later maintenance actually succeed. It does not convert any prior failure, timeout, Unknown observation or incomplete utility evidence into NoUpdate or a pass. Actual source before/after comparison, material checks, original command records and the independent native terminal must be retained by the later execution.
