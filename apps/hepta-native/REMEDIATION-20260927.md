# Native remediation continuation — 2026-09-27

Status: implementation candidate, not qualified and not release-authorized.
Branch: `work/ui-native-closure-20260927`. Continue PR #1046 without overwriting
its concurrently updated branch. No change in this continuation authorizes a
main merge, a privileged platform effect, or production promotion.

## Corrected baseline

The inspected candidate already tracks complete Rust source and declares
product version `0.1.0`. `historicalSourceCommit` is provenance, not a runtime
source-restoration dependency. The previous review's `0.0.0` and historical
source-restoration assertions must not be used as current implementation facts.
The protected-main delivery and six exact-subject execution receipts remain
separate, unfulfilled acceptance criteria until independently observed.

## Exact-source qualification and source identity

The required job now downloads all six same-run/same-attempt bundles. It
reconstructs the deterministic merge, binds candidate, main base, workflow
commit and workflow file digest, revalidates each retained command observation
and log, hashes retained package bytes, and requires matching inventories and
lock digests across platforms for each source subject. Missing, duplicate,
foreign, cancelled, failed, altered, or partially rerun evidence cannot pass.
The aggregate remains a repository-controlled observation, not signing,
physical acceptance, independent review, or release authority.

The formatter no longer has contents-write permission or writes to a moving
branch. It produces a pinned-source patch artifact. Applying that patch is an
ordinary reviewed source commit; the normal qualification workflow must run on
the resulting exact SHA. A successful proposal job is not a formatting pass.

Source fingerprints cover tracked bytes rather than untracked caches. Dirty,
deleted, and symlink-substituted tracked files are rejected. Fingerprint-only
commits are excluded from implementation source selection. The metadata writer
preserves reviewed mappings and open gaps, refreshes every source object from
the selected source commit, and never manufactures execution completion.

After committing implementation on this continuation branch, run:

```sh
export HEPTA_UI_NATIVE_WRITE_BRANCH=work/ui-native-closure-20260927
python3 apps/hepta-native/tools/prepare_current_source.py --sync-metadata
python3 apps/hepta-native/tools/prepare_current_source.py --write-fingerprints
python3 apps/hepta-native/tools/prepare_current_source.py
python3 scripts/test_hepta_module_registry.py
```

Commit only the resulting native identity/mapping files. `sourceBase` denotes
the implementation commit preceding the metadata-only commit, while CI binds
the exact final candidate, its tree, main base and deterministic merge.

## Journal v4: corruption detection without unsafe replay

New snapshots carry a SHA-256 checksum of the versioned ordered operations and
retirement frontier. This detects accidental corruption; it is not a MAC,
anti-rollback protection, or permission to reconstruct missing authority.
Legacy v2/v3 records remain readable and migrate at the next actual persisted
change. They do not retroactively gain checksum protection.

Before replacing a valid snapshot, retain its exact bytes as
`<journal-path>.previous`. This is one bounded forensic checkpoint, not a replay
source. A corrupt primary is not overwritten. A missing primary accompanied by
a checkpoint fails closed. Never copy the checkpoint over the primary to
recover automatically: an old Prepared record may correspond to an effect that
already happened. Preserve both files and obtain authoritative operation-ID
reconciliation. No automatic repair or full operational recovery is claimed.

Snapshot writing is isolated in a private module. Unix temporary permissions
are restricted before publication. Private error-injection tests cover open,
write, file sync, replace and directory sync boundaries. They do not introduce
a public fault switch or environment override. These tests model error returns;
they are not proof of power-loss durability, kill -9 behavior or Windows storage
semantics. Rust execution and actual fault-host results remain required.

Exact duplicate records are a no-write idempotent result; semantic drift and
terminal changes still conflict. Reads use the existing non-following regular
file opener. This does not close ancestor-directory replacement races or
handle-based platform-effect dispatch: those remain open work.

## Evidence and unresolved delivery gates

Local Python testing covers aggregate tampering, source-identity substitution
and existing evidence checks. It is not Rust compilation, hosted matrix
execution, an installed application, or physical accessibility acceptance.
The current editor environment has no Rust toolchain; hosted qualification
must supply the real format, Clippy, native/owner tests, build and package proof.

The connected GitHub integration returned HTTP 403 for branch-protection
administration. No branch-protection setting has been changed. An authorized
repository administrator must add `ui.native remediation required`, preserving
all existing protections and verifying the read-back result. Do not disable
checks, force-push main, or merge on a missing/pending/skipped aggregate.

Still open, not implemented or accepted by this continuation:

- operation-ID OS broker receipts, queryable effect terminality and full crash
  boundary reconciliation, platform path-handle fencing, and Windows durable
  replace/ACL/file-identity qualification;
- macOS Developer ID/notarization/bundle rollback; Windows Authenticode and
  installer/updater-service integration; Linux distribution signing;
- production SBOM and signed provenance, release-key custody/rotation/revocation,
  and installed upgrade/downgrade matrices;
- real authority/gateway/UI/OS end-to-end acceptance, physical IME/DPI/keyboard/
  screen-reader runs, soak/resource results, independent security approval and
  independent release approval.

Keep `productionImplementation=false` and `releaseAuthorized=false`. The
release verdict remains no-go until the actual required external and hosted
receipts exist. This document is a development record, not an acceptance receipt.
