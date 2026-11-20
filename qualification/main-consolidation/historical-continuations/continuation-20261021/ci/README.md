# CI checkpoint evidence

This directory is a compact, integrity-indexed handoff. Each file is below 400,000 bytes. Full generated locks are carried in the repository change and are deliberately not duplicated here.

- `tls/`: final two-file TLS patch, real Cargo/Bazel command receipts, exact source conservation, all nine Windows resolver changes, and original command logs. Candidate base is `0cb777545966333a96be265a69d03c9982231bc7`. Original Bazel update and check passed; native Windows qualification remains pending.
- `cargo-deny/`: exact-source local baseline/candidate output showing 7 → 4 advisory errors, package paths, and preserved original RustSec inputs. Original CI job log retrieval failed; these are explicitly local reproductions. The four maintenance advisories still fail the unchanged gate.
- `base-identity/`: actual failed job `118980327865` and investigation tying event base `603238` to advanced owner `98b40c` and prospective merge `6b074e`. A real ancestry-preserving merge is the proposed repair; equality checks remain strict.
- `p0-fixes/`: replace-object and hidden-index identity hardening plus Bazel optional binary lookup regression evidence; includes cargo-bin trailing-LF hash reconciliation.
- `initial/`: historical 00:40–00:49 UTC audit and failure excerpts. Backlog refresh is explicitly non-atomic and includes all captured queued pages: 100 + 100 + 82 + 0. It does not represent current runner capacity or all 40,000 reported historical runs. Initial PR metadata is dated; newer top-level CI_MATRIX/BLOCKERS and inventory delta take precedence for current state.

`MANIFEST.json` records every checkpoint payload checksum and origin/transformation. `RAW_OMISSIONS.json` indexes all original CI audit files and explicitly explains omitted payloads. Sources remain in scratch where retained; task-owned caches/source-download archives were reclaimed only after qualification, with cleanup receipts. No full raw payload has been silently truncated.
