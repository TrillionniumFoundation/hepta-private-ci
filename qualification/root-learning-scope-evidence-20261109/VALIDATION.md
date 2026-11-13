# Validation details and interpretation

## Native execution

Host: ai395, isolated source `/home/qq/hepta-root-product-0744-20261109/source`.
Toolchain: Rust 1.96.0. The unchanged native helper is separately pinned in the runner/receipt.
The starting 10608 codex-rs objects were checked against the prior maintained baseline.
Each new inventory contains 10622 file/symlink entries, including CALLERS and two source-QA files.

The pre-maintenance cumulative candidate ran the repository-prescribed test entrypoint:

```sh
just test --locked --offline -p codex-hepta-agentd -p codex-hepta-learning-artifacts --lib --test-threads 2
```

Ordinary raw logs show 772 agentd and 109 learning-artifacts passing cases.
The six explicit Root parents were selected exactly by the native Root qualification runner:

- `root_learning_registration_reopens_without_replacing_original_history`
- `root_learning_sealed_pin_and_dedicated_uds_recover_original_checkpoint`
- `root_learning_handoff_reaches_dedicated_uid_with_original_root_pin`
- `root_scoped_learning_reopens_exact_scope_and_refuses_legacy_client`
- `original_external_uid_returns_a_verified_receipt_through_held_pidfd`
- `root_learning_public_registration_serves_retained_writer_and_recovers_history`

Root JUnit has six cases, run UUID `17b138c5-3514-4ff2-951a-b8f55c3546bb`.
Its SHA256 is `5a73fad9e6e9d0ddaf0bbc98a7a526353c79dd30ad684b0bce057a558d198355`.
Raw logs, names, UUID, report timestamp and original command window were checked together.
The public-service case records actual consumer UID 60001, schema 2 / Cell scope,
original retained writer and dedicated listener, one restored receipt and exact retry.
Nested process helpers are not additional parent tests.

Source audit ran scanner self-test, whole-tree verify, and 17 bootstrap/scope/collision regressions.
Both scanner implementation files retain their baseline hashes.

## Required maintenance and final source proof

After behavior qualification, the repository-required maintenance ran:

```sh
just fix --locked --offline -p codex-hepta-agentd -p codex-hepta-learning-artifacts
just fmt
cargo check --locked --offline -p codex-hepta-agentd -p codex-hepta-learning-artifacts --bins
```

All three exited 0. Seventeen Rust files changed mechanically, including one redundant clone cleanup.
The maintained inventory is `1901b15d75b0d0b7eec8c2b1a3d0abeea6e0f279661203d38b22b10c82d16f20`.
No tests were rerun after maintenance, in accordance with the repository's instructions.
The final full source verifier ran `python3 scripts/verify_hepta_callers.py verify` and exited 0.
It covered 6157 Rust files, 188 boundaries and 170 protected-file entries (133 distinct paths).
It reports `PASS_HEPTA_CALLER_CLOSED_SET` and `authorityGranted=false`.

## Preserved failures and collection correction

1. Initial v1 compilation exited 101 on ambiguous assertion imports and missing optional
   scope fields in existing test fixtures. Those errors were fixed before v2 behavior tests.
2. Initial source audit found a test helper missing an explicit test-only impl annotation,
   plus a broad same-name constructor matcher. Existing typed receiver resolution fixed
   the matcher; the scanner implementation was not changed. The collision regression passed.
3. The original Root command exited 0, but its wrapper looked under CARGO_TARGET_DIR for JUnit.
   The actual report was under source/codex-rs/target/nextest/local/junit.xml, so collection failed.
   The original failed receipt/status/log remain unchanged and are included in the native archive.
   Reconciliation verified the existing six-case report and did not rerun Root tests.
4. That Root report had overwritten the ordinary JUnit. The identical ordinary command ran
   once more before maintenance; full raw case inventories matched the original run and new JUnit.
   This does not add 881 more distinct cases. Reconciliation explicitly records one rerun.
5. The first post-fmt source verifier rejected a single-line literal marker after rustfmt
   wrapped a method chain. Its failed receipt remains. Only exact marker whitespace was aligned
   in CALLERS and one source-QA file; non-whitespace guard sequences and every Rust byte remained fixed.
   The final whole-tree verifier then passed. Source-QA tests were not rerun on those final marker bytes.

The archives retain distinct failed, corrected and successful receipts. No original failure was relabeled.
The independent readback records the two reconcile-index references resolved by the companion archive.

## Published source and review cuts

All ten source cuts are based on the previous cut, starting from `e2e20033daa67d9d9826d4942e4d6bdd15ba4ab5`.
Their changed-line counts are 280, 301, 439, 444, 115, 306, 408, 287, 493 and 452.
The final cumulative tree is `deca4dc9e355ba313c68528d9c88bd5104a71f36` and code head is `b8e8c6e82abc1479c573f61a5e17d28d581e6cad`.
Exact-ref connector readback checked all 33 files against the final local/native source inventory,
including content SHA256, Git blob SHA1, size and tree membership. The reports are in the source archive.
The v3 review-cut issue was fixed in v4: cut 4 includes all legacy registration-test adaptations.
These are cumulative review cuts; individual cuts have no separately claimed native/CI qualification.

## Product acceptance remains HOLD

The unchanged startup guard, empty product caller sets and `production_ready: false` are intentional.
Actual training/evaluation/signing owners and Circuit providers are absent from this product assembly.
Frozen Cell/Organ scope checks declared components after authenticated Training and on recovery;
it does not prove execution-time tensor masking, data isolation or downstream benefit.
Evidence receipts use initial-request binding, not an independent signature over FrozenLearningScopeV2.
The actual UID test uses pre-signed fixtures; the Root service test uses synthetic Experience receipts.
Different UIDs are process-custody evidence, not independent scientific evaluation.
No Device/Notes consumer lane, formal generation publication/recovery, sustained operation or deployment
is qualified by this stack. `Unpublished` remains the ordinary generation boundary.
