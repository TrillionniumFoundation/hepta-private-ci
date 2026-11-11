# MEM8 federation coverage failure diagnostics (HOLD)

This is **one test-only diagnostic** on exact parent `ceadcb3b11dbd94a9d07afb7e6301555e4ff3f80`. It does not change production code, retrieval semantics, the 2-second federation deadline, expected 16/16 completed peers, sandbox, access controls or adoption gates.

The existing test `cognitive_runtime_tests::product_v2_reports_peer_truncation_before_aggregation` now includes the pre-existing typed `FederatedCoverageV2` object in its **assertion failure message**. Previously macOS Intel reported `completed_peers = 0` where 16 were required but did not print the already available typed `failures` counters. On any future failure the complete non-secret numeric coverage (discovery unavailable, deadline/cancelled, authority, integrity and transport unavailable) will be printed. No hypothesis about the root cause is treated as established.

## Original ai395 local check

- Source head before the diagnostic: `ceadcb3b11dbd94a9d07afb7e6301555e4ff3f80`; new worktree created detached from that immutable parent, with a new separate review branch.
- Initial `rustfmt --check` with stable rustfmt failed; its diff also affects unchanged imports and assertions from original source. Retained as a failed preflight, not converted into PASS.
- Initial locked Cargo test compilation failed at AWS-LC bindgen because Clang could not resolve `stddef.h`. Retained as a failed environmental preflight.
- Without changing any source, used `BINDGEN_EXTRA_CLANG_ARGS=-I$(gcc -print-file-name=include)`, and ran `cargo test --locked -p codex-hepta-memory --lib product_v2_reports_peer_truncation_before_aggregation -- --nocapture` with `CARGO_BUILD_JOBS=4`, isolated `TMPDIR`, and `timeout 420`. **One actual test passed, 0 failed, 432 filtered out**, with exit 0. This is **not** a macOS reproduction or whole-crate/required-CI pass.
- `git diff --check` passed. Only the exact assertion message is changed in code.
- All three original PTY output archives are embedded losslessly in `raw-pty-logs.tar.xz`, hashed per member and as one compressed artifact in `EVIDENCE.json`. `EVIDENCE.json` is not claimed to contain its own hash.

This evidence does not consume any MEM5 actor, the 54 reused development cases, any new cohort or any sealed role. Source/exposure, owner-authenticated recovery and independent scientific validation remain **Draft / HOLD / NoUpdate**.
