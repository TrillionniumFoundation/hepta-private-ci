# ui.native remediation implementation and acceptance ledger

Date: 2026-09-27
Review baseline: `b9c6a7c3f55b3bde9c7a04542eaf4b9934f7ecc0`
Continuation: `work/ui-native-remediation-20260927`

## Scope and implemented changes

Continue the existing Rust native candidate and its detailed
`apps/hepta-native/DEVELOPMENT.md`; do not replace it with another mock shell.
See ADR-20260927-canonical-rust.md for the generation and compatibility decision.

The runtime patch makes displayed revisions monotonic across upstream generation
changes. It separately tracks the raw snapshot generation, preserving valid
zero-generation startup while refusing regression masked by UI projection.
An exact terminal duplicate returns its durable original receipt even after
the view advances. Semantic drift still conflicts, and a fresh operation must
match the current view before permission or effect dispatch.

The operation's immutable Prepared record is persisted before the permission
adapter is entered. Permission exceptions and malformed permission observations
produce an immutable no-dispatch rejection. They cannot produce a success or
an automatic retry that repeats a permission interaction. Existing kernel grant
claim and final-use revalidation still precede platform effect dispatch.

Close and reconnect invalidate presentation before fallible transport cleanup.
Invalid newly connected sessions are closed, and a failed reconciliation tears
down the candidate session rather than exposing a partially recovered runtime.
Prepared-operation reconciliation now matches endpoint identity as well as
session ID and generation.

Ten new Rust integration regressions cover the above boundaries using real
journal files and isolated adapters. These tests do not exercise live authority
custody or certify a desktop platform. Their declaration is not a passed result.

## Development and qualification commands

Run from a complete, clean, committed repository checkout. The existing Rust
application uses Cargo, not the old JavaScript package. Select the committed
Rust 1.95.0 toolchain, and install OS prerequisites documented by the existing
application manual and workflow.

```sh
python3 -m unittest discover -s scripts -p test_hepta_ui_native_evidence.py -v
python3 apps/hepta-native/tools/prepare_current_source.py
python3 scripts/hepta_ui_native_evidence.py inventory --out native-inventory.json
cargo +1.95.0 fmt --manifest-path apps/hepta-native/Cargo.toml --check
cargo +1.95.0 clippy --manifest-path apps/hepta-native/Cargo.toml --locked --all-targets --all-features -- -D warnings
cargo +1.95.0 test --manifest-path apps/hepta-native/Cargo.toml --locked --all-targets
cargo +1.95.0 build --manifest-path apps/hepta-native/Cargo.toml --locked --release --bins
```

Outputs must use a new path: evidence is create-only rather than overwritten.
The source fingerprint generator reads committed bytes; do not regenerate it
against an unstaged change and then claim that change was verified. After a
source change, commit the source, refresh fingerprints in an isolated detached
continuation of the native branch using the existing generator, and review the
metadata-only diff. Current SHA-bound CI receipts, not generator execution,
establish qualification.

The workflow `hepta-ui-native-remediation.yml` constructs exact-head and
synthetic-main-merge subjects for Ubuntu 24.04, macOS 15 and Windows 2025 hosted
runners. These are qualification environments, not a declaration of minimum
supported customer operating-system versions. Each profile runs locked native
and owner tests, strict formatting/Clippy, real release builds, existing binary
self/crash qualification, deterministic unsigned packaging, and packaged-binary
self/crash tests. Linux additionally runs the existing ordinary GUI product
qualification with Xvfb, isolated DBus, real OS keyring and the real gateway.
It does not replace that GUI test with a mock transport or a success marker.

No workflow step uses continue-on-error to satisfy acceptance. The required
aggregate runs even after failures and explicitly requires both subject binding
and the entire qualification matrix to succeed. This check must also be selected
in repository protection before it becomes a server-enforced merge requirement;
a job name alone does not configure branch protection.

## Receipt fields and trust model

The collector records argv, real exit code, timeout, start/end times, source
identity before/after execution, run/attempt, and retained log digest. Sealing
requires every mandatory observation and verifies the source/run subject, log
contents, success status and observation clocks. It refuses absent, duplicate,
foreign-head, altered-log, dirty-tree, failed or timed-out observations.

A sealed receipt records actual source SHA/tree, candidate/main SHAs, ordered
merge provenance, workflow commit/file digest, both Cargo lock digests, actual
Rust version output, hosted image identity, source/test inventory digests,
package hashes/sizes, run/attempt and timestamp. The six required profiles are
generated from one matrix definition rather than six handwritten green flags.
Logs and packages are retained for 30 days; credential-free source snapshots
for 3 days. Copy approved evidence into the organization's durable retention
system before expiry; Actions retention is not permanent audit storage.

This is source-bound CI observation, not a signed provenance statement. The
workflow and collector must themselves be reviewed and trusted. Logs can include
sensitive errors: qualification uses isolated fixtures, never production keys.
Inventory lists source declarations, not compiled public API reachability or
actual per-case execution coverage. A successful test command is not a claim
that ignored or conditional tests executed on every OS.

The fields physicalHostAcceptance, accessibilityAcceptance,
productionSigningObserved and releaseAuthorized remain false. A package zip
hash is not a code signature, and keyboard event delivery is not screen-reader
acceptance. No production state root, signing key or release channel is created
or modified by this remediation.

## Six-stage acceptance ledger

| Stage | Delivered or inherited in this candidate | Still required before closure |
| --- | --- | --- |
| Canonical implementation | Rust candidate retained; explicit ADR; existing detailed manual retained; commit-bound inventory and receipt tooling | Review and integrate the chosen candidate into main; successful exact-source verification |
| Product composition | Existing main/runtime/authenticated gateway/credential helper; cleanup fixes; mandatory Linux installed GUI lane | Execute the matrix; installed macOS/Windows GUI lifecycle and failure acceptance; multi-window policy expansion only by explicit design |
| Capability effects | Existing durable journal and kernel final-use gate; pre-permission reservation; immutable rejection; monotonic revisions and duplicate results | Full view-generation/content/endpoint grant binding review, resource canonicalization and replacement races, trusted terminal receipt threat-model closure; execute Rust crash/concurrency suites |
| Safe updater | Existing updater, handoff, private storage and package tests retained and included in qualification | Validate all update crash boundaries, post-restart digest/health, failed rollback quarantine, key rotation/revocation and independent channel policy against installed artifacts; this patch does not claim new updater implementation |
| Platform/release | Existing bundle/AppDir/Windows manifests and unsigned packaging; generated packaging-source inventory; actual AccessKit dependency | Customer minimum-version matrix; signed installers/notarization; OS permission acceptance; screen readers/IME/DPI; complete release SBOM and signed provenance; independent release approval |
| Qualification | New strict six-profile workflow and immutable bound observation collector; adversarial collector tests | Actual successful Rust/build/package/GUI executions and retained receipts; branch-protection enforcement; long-term evidence retention |

## Verification performed for this patch

The authoring environment executed the 32 Python inventory/evidence regression
tests successfully. These include real subprocess success/failure/timeout,
tracked-tree mutation, immutable observation paths and adversarial receipt/log
validation against temporary Git repositories. The Rust regressions were
written but not compiled or executed in that environment; it did not contain a
Rust toolchain or a complete repository checkout. No three-platform package,
signing, notarization or installed-host acceptance is claimed in this document.
Consult the exact commit's workflow result rather than treating this text as a
qualification receipt.

## Recovery and integration procedure

Review this continuation as a stacked change over the native candidate. Do not
force-update main, overwrite another module's branch or bypass failed checks.
Retain the existing candidate PR until the continuation is reviewed; then
integrate the native candidate through the normal protected-main process.

A failed permission operation is terminal no-dispatch and must not be retried
with changed semantics under the same operation identity. A user retry is a new
explicit operation with fresh authorization. Invoking/Indeterminate records
are reconciled through the existing adapter; absence of evidence is never a
license to replay an OS effect. Failed transport close leaves no connected
session or actionable view. Operator diagnosis must preserve journal records;
never delete a journal merely to make startup appear successful.
