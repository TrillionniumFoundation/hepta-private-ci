# P10: shared Stem chain CI shim convergence (shadow only)

Branch head before this documentation commit:
`538ef55ab201ce865058dcbfc3fe81bf9c9fff0c`.
Parent P9 [#2999](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2999)
keeps the frozen 421M cognition control, EmbeddingGemma 2 perception/Memory
candidate, T5Gemma 2 context encoder and native Hepta 150M/300M students.

## Narrow Rust CI fix

Windows Clippy on the unmodified P8 ancestor rejected the disallowed SQLx
PoolOptions.connect call in two *test-only* SQLite fixtures:

- `codex-rs/hepta-automation/src/migration_convergence_tests.rs` now uses
  original, reviewed convergence blob
  `cbfd7e431a6ef59d76bf7f599178ab0b91cb1088`.
- `codex-rs/hepta-memory/src/cognitive_schema_tests.rs` now uses original,
  reviewed convergence blob `825a37ef501ad4715fbcdc24cae92763520b2070`,
  also tracked in HOS2 #2998.

Both use `codex-state` SQLite shim, keep the temporary database directory
alive until pool close, and preserve schema/migration/rollback/tamper assertions.
No lint is disabled and no shipping runtime path is switched.

## Admission evidence is exact-HEAD only

This document intentionally touches `docs/learning/STEM_BAKEOFF*` to trigger
the full existing shared-Stem Shadow workflow **on the P10 SHA**, in addition
to P10 Blocking CI, V8 Canary and Architecture Convergence. Previous P9 success
is not transferable to P10 and no queued job counts as pass.

Remaining blockers include source RustSec/cargo-deny advisories (candidate
fixes #2976/#2983), cross-platform Bazel/Windows tests and zlib fallback
qualification (#2991), approved and byte-pinned real teacher models/license/
preprocessors, independent future/OOD cohorts, full 150M/300M training and
physical GPU p95/p99/RSS/VRAM/energy with 1–4096 Cell fan-out.

The five-layer architecture stays shared modality frontends → slotizer →
versioned shared Stem → lightweight Cell gate/adapter/head/state →
external Memory reference. No per-Cell 421M model duplication, production
Memory write, action authority or autonomous merge is introduced.

**DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.**
