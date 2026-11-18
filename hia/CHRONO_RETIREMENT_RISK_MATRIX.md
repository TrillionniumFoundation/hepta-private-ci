# Chrono retirement: signed-wire and cache compatibility risks

This is a **source-only migration risk inventory** on exact Codex predecessor `bbb534d8be9098c041d5f3dd1ca1214fbcc2fd8a`. It neither resolves `RUSTSEC-2026-0543` nor qualifies a native HIA product. Do not introduce advisory ignores, promote default dispatch, merge, or delete old Rust based on this inventory.

## Pinned resolved-lock graph

Independent GitHub-blob in-memory parsing and reverse dependency traversal matched the reachability module's earlier result: `codex-rs/Cargo.lock` Git blob `e1fdaf3fde907d24fec7ea787d49c0e29b3eb4bd`, workspace manifest blob `145c9b24e7203461337a68cf9938f9f0bce720a9`, **1,530 packages**, **193 source-less non-vendored candidate roots**, **121 chrono-reachable** (28 directly and 93 indirectly), and **zero unresolved/ambiguous declared lock edges**. These are conservative lock graph candidates, not executable feature or runtime proof. Immediate external importer candidate-root coverage is overlapping: `schemars` and `serde_with` 120 each; `sqlx-core`, `sqlx-mysql`, `sqlx-postgres` and vendored `sqlx-sqlite` 87 each; `oauth2` 69; `rmcp` 68. Do not sum these coverage values.

## Three distinct first-party risk classes

**1. Simple Unix-seconds representation: `codex-git-utils`.** Exact `codex-rs/git-utils/Cargo.toml` blob `a0bd7872854cffa38dd559805a1dea2d06db85ae` directly declares chrono; `src/baseline.rs` blob `083dd6010fcc71d8e9d9542bc7813dba88b7684f` contains a single `chrono::Utc::now().timestamp()` call for a Git actor signature with `offset: 0`. A separately prepared source-only proposal substitutes `time::OffsetDateTime::now_utc().unix_timestamp()` and the already declared workspace `time` dependency. It has **not** passed an exact complete-checkout Cargo/Bazel build. Even after this direct removal, `codex-git-utils → schemars → chrono` remains reachable in the pinned lock. Never claim it closes the advisory.

**2. Signed timestamp wire: `codex-agent-identity`.** Exact manifest blob `36d5eb41fd694a9eb2834cbd6af4bc0977fa36c80` and only Rust source blob `14a9e35190118d3f62fe1197dd9735229f34e4cd`. Both `authorization_header_for_agent_task` and `register_agent_task` produce `Utc::now().to_rfc3339_opts(SecondsFormat::Secs, true)`; one signs the agent assertion and the other signs the task-registration timestamp. Replacing chrono must preserve the exact **whole-second UTC `Z` string**, not merely represent the same instant. A fractional-second or offset-format change alters the signed payload. Demand byte-exact timestamp fixtures and signing/verifying compatibility, including boundaries, before a dependency substitution.

**3. HMAC-authenticated persisted timestamps: `codex-cloud-config`.** Exact manifest blob `ecb33d34beb89a3112cbd316e6bcf672b089a833`; `src/cache.rs` blob `e5d1d4dc84a725a8148f143ce687eb6d2f9d2b24`. `CloudConfigBundleCacheSignedPayload` serializes `DateTime<Utc>` values `cached_at` and `expires_at` with `serde_json::to_vec` and signs those bytes using HMAC-SHA256. It rejects expired caches at `Utc::now()`; saves use checked `ChronoDuration::from_std(TTL)` arithmetic. Changing the temporal type, serializer or precision can invalidate previously written cache signatures even if a new binary can serialize its own data. Preserve old signed-cache read compatibility, exact JSON/HMAC byte behavior, TTL boundary/error behavior and old-versus-new fixture tests. An unqualified type rewrite risks persisted-state breakage.

## Required adoption order

- Freeze exact source preimages and preserve historical negative records; use an isolated reviewed Draft branch.
- For each completed first-party replacement, run the repo's `just test -p …`, scoped `just fix`, `just fmt`, strict Clippy, and regenerate **both** Cargo and Bazel locks using supported recipes. Never hand-wave lock drift.
- For signed wire/cache crates, qualify old/new interoperability and negative inputs before integration. For external importers, use maintained replacements or explicitly reviewed dependency-path removal; mere first-party direct-import removal is insufficient.
- Obtain passing current-head original cargo-deny, complete native/default Rust/HIA owner and public/effects tests, installed CLI, Linux GNU/musl, macOS Intel/ARM, Windows, performance, full workspace, rollback and release gates. Keep legacy/default Rust until all applicable gates close.

**Status:** `whole_codex_rewritten=false`; `production_dispatch_migrated=false`; `retirement_ready=false`; `performance_closed=false`.
