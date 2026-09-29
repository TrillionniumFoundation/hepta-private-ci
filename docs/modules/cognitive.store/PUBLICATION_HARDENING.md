# Publication, lifecycle final-use and recovery-report hardening

This change continues the existing cognitive-store convergence candidate. It does not replace the SQLite owner, semantic transaction, signed host bootstrap, read capability, archive codec or native owner checker. Archive bytes remain full cold-generation images; no hot history is pruned.

## Descriptor-bound cold publication

`tools/cognitive-store-host-bootstrap/archive.py` now uses `archive_publication.PinnedDirectory` for normal archive and restore output. Each directory component is opened without following a symlink. Output creation, stage creation, no-replace linking and synchronization use retained directory descriptors. Before and after the commit boundary, the original pathname must still resolve to the same owned private directory.

Restore retains the decoded image descriptor and rehashes its complete bounded payload after native-owner verification, after final reauthorization and before returning publication success. A changed image cannot borrow a successful check of earlier bytes. The published inode must match the checked inode; existing destinations are never overwritten. Source images, archives, recovered generations and active pointers are not deleted by this change.

`PublicationIndeterminate` preserves a possibly published image or manifest after synchronization or post-publication identity failure. It does not permit replay. Use the existing separately signed publication-observation request to inspect an uncertain result. Missing files are not proof of non-execution, and an observed valid artifact is not proof that earlier directory synchronization succeeded.

Scratch cleanup is bounded and inode-aware. It removes only the image inode created by that scratch operation, never a same-name replacement, unknown child tree, published output or ambiguous hard link. A moved or unrecognized scratch object is retained for governed reconciliation rather than recursively deleted.

These controls reject the tested path-replacement cases. They are not a sandbox against arbitrary code running as the same OS principal or an attacker controlling the mount namespace. The host must isolate its maintenance principal and mount configuration. Linux filesystem/device fault acceptance remains independent of these repository tests.

## Current trust after lifecycle receipt verification

The ordinary `lifecycle.py` CLI calls `reconcile_files`. It authenticates the requested plan and the existing per-storage-owner receipt set, then rechecks those inputs and rereads current signer trust after cryptographic verification. Trust replacement, revocation, expiry, changed receipts or plans, and clock regression cannot produce a completion report from an earlier observation.

The result is a last-observed report, not an atomic transaction spanning independent files. `owner_attested_complete` remains an authenticated set of owner assertions, not an independently performed physical erase. `authorized_effects`, `physical_erasure_independently_proved` and `target_host_qualified` remain false. Missing or indeterminate owner obligations remain incomplete; no new authority, signer key, provider or eraser is introduced.

### Signed-file and signature-verifier identity

Every lifecycle plan, trust bundle and receipt set is now opened relative to a retained descriptor for each parent directory component. Intermediate symlinks are rejected, the leaf remains single-link and non-group/world-writable, and both the retained leaf and the current parent pathname are rechecked before parsed bytes are used. Renaming the original parent and replacing it with a same-name directory therefore fails instead of redirecting final-use verification.

Ed25519 verification no longer resolves `openssl` from caller-controlled `PATH`. The tool admits only a root-owned, executable, non-group/world-writable system OpenSSL path, invokes it through an absolute path with a minimal environment, and rechecks the executable identity after use. This is host verifier admission, not a claim that repository code governs the system package or independently attests the selected host.

## Release recovery measurement admission

`scripts/cognitive_store_recovery_report.py` validates the existing recovery example's artifact against independently supplied source commit, tested commit, tested tree and required record count. The qualification plan validates both 256 and 16,384-record release profiles after their measurement commands. At least three complete iterations, exact-cut preservation, all expected 512-head pages, bounded integer timings, initial/final verifier observations, resource samples and Linux RSS are required.

The validator rejects duplicate JSON fields, nonfinite/floating values, missing fields, wrong candidates, debug-assertion builds, partial runs, and escalation of fixture or erasure claims. It binds the raw report digest. It does not manufacture observations or accept an SLO. Three runs are not a percentile acceptance study; sampled resource peaks remain lower bounds. The independently recorded `cargo run --release` command and artifact validation are both required.

## Regression and execution scope

| Test source | Cases | Local execution scope |
|---|---:|---|
| `test_archive.py` | 45 | Existing real crypto/filesystem protocol regressions; named native-owner mock, plus negative executable admission cases |
| `test_archive_publication.py` | 21 | Normal archive/restore path, directory descriptors, file identity, no-replace publication, retained ambiguous output and conservative scratch cleanup |
| `test_lifecycle.py` | 35 | Real Ed25519/OpenSSL signatures, all storage classes, pinned parent paths, PATH-injection rejection and bounded signed inputs |
| `test_lifecycle_final_use.py` | 12 | Real Ed25519/OpenSSL signatures, complete ordinary CLI invocation, final trust/input changes and incomplete receipt sets |
| `scripts/test_cognitive_store_recovery_report.py` | 21 | Synthetic measurement fixtures testing the validator; not performance measurements |

Four publication regressions fail against the exact pre-change archive blob `9371893ca8ca748f5ee818dca8154be411d4f3b2` and pass against the changed implementation: changed restore bytes after native checking; changed bytes during reauthorization; redirected output parent; redirected archive name before manifest publication. No regression bypass or test-only publisher was added. The existing concurrent-destination test was adapted to directory-relative syscall arguments while retaining its no-overwrite assertion.

These 134 local tests are not exact-head/base-merge Rust execution, native owner acceptance, independent deployment qualification, destructive pruning or physical erasure. The committed plan retains all independent records for publication-boundary tests, lifecycle verification/final-use tests, report-validator tests and both release-report validators. Source-head and deterministic base-merge must each establish their own terminal results. Qualification remains read-only and never applies a patch or pushes a fix.

## Remaining work

Complete current-candidate native compilation, strict lint, owner archive/recovery and resource measurements; run independent selected-host bootstrap, restart, rollback and fault qualification; implement and qualify ancestry-safe hot-generation pruning; obtain actual per-owner erasure/unlearning execution and independent acceptance. Neither a green protocol test nor a signed owner assertion closes those separate obligations.
