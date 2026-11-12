# Original 7bb0fa86 compilation and ordinary-A failure

Source `7bb0fa86fd3588c7711fe1ed6e361962c8d11741`, tree `ad0c66b5cf914a2effac4b3695042ccb4c79bfff`.

The scoped seven-package `just fix` completed with exit 0 in 113.014377114 seconds, with unchanged source. The subsequent ordinary-A native parent completed with **0 passed, 1 failed, 0 skipped**, in 1.418 seconds, also with unchanged source. The fresh JUnit is exactly 2,198 bytes, SHA-256 `9acad88ba70193ca7eae8f454168509f81bb8be5799f492f0a4b7028ae5786b1`.

## Exact observed failure

The daemon's original 281-byte stderr records:

```text
Error: original Initial readiness frame exchange: original Root publication frame read response length: original Root publication poll rejected: ready=0; requested_events=0x1; root_revents=0x0; stream_revents=0x0; deadline_elapsed=true; os_error=None; io_kind=Other; os_error=None
```

This observation supplies explicit deadline evidence for this particular client response-length poll. It does not determine the underlying reason the Root reply was unavailable. Root child stdout and stderr are both empty; its signal-9 status after cleanup is not treated as the underlying cause. Earlier failures without this diagnostic are not retroactively classified from this record.

## Original bytes and collector

The archive preserves 41 original files / 2,326,070 input bytes: actual drivers, compilation output, test-binary preparation, fresh and explicitly excluded prior JUnit, and both original child log pairs. Duplicate or prior XML is not an additional execution. Pinned executables are excluded.

The read-only collector is the previously verified af2 collector with exactly seven `af2ec8ea → 7bb0fa86` tag substitutions. Its reversed bytes and AST match the prior collector. The 4,430-byte create-only upload matched SHA-256 `529ab061d2fa01dd6c2397a0b93438e3410f8db5bf5d9dd562710796999f3d14`.

Only the authorized UID0 collector was executed: `sudo -n /usr/bin/python3 -u /home/qq/hepta-learn-ff41-tools/collect_native_originals_7bb0fa86_v1.py`. Job `1a1d1fd5219-2564-1c8c`, key `ci-evidence-collect-7bb0fa86-20261112-v1-ff41`, completed with exit 0 and durable complete output, no automatic retry and no timeout. The collector ran no Rust command or test and verified all original bytes again after packaging.

Six 16-KiB reads were bound to one archive version. Each chunk was immediately saved and checked; the archive and all 41 members were verified for size, SHA-256 and Git blob identity. Original MCP text, collector source, exact replacement diff and actual launch/status receipts are retained separately.

Archive: 93,180 bytes; SHA-256 `2e19aa546f0239a3f99b9b8b4368593cf53ba9fb5d08c87cc50e3538104770e9`; Git blob `d4178d4a1aef652daef1db6dd5e5b5864217da41`. Manifest SHA-256: `686f46c7255c9cc0020ca2711353953193068ef4b8a1b094bb15a27a74506ea0`.

Whole Adopt / evaluated post-B NoUpdate / cold-recovery counts remain 0 / 0 / 0. Full caller verification remains on hold.
