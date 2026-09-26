# ADR: one canonical Rust native application and commit-bound qualification

Date: 2026-09-27
Status: proposed for the native candidate; not a main-branch or release decision
Owners: ui-platform; accessibility deputy

## Context and decision

The main-branch JavaScript boundary and the unmerged Rust native application are
not interchangeable implementation generations. This remediation continues the
Rust application in `work/ui-native-current-source-20260925`, based on commit
`b9c6a7c3f55b3bde9c7a04542eaf4b9934f7ecc0`, rather than building a second native
framework or restoring an arbitrary historical tree. The implementation is
`apps/hepta-native/Cargo.toml`, its committed Cargo lock, and `src/main.rs`.
The manifest selects Rust 2024 and eframe with AccessKit, with separate updater
and credential-helper binaries. The authenticated loopback gateway remains in
`codex-rs/hepta-native-gateway`; kernel final-use authority is not moved into UI.

The remediation branch is a continuation for review, not a second product.
Existing Rust implementation, packaging, updater and DEVELOPMENT.md are inherited
work, not new implementation claims for this patch. No other module's authority
or activation status is changed by this decision.

## Retired surface and compatibility

`src/native.js`, `src/shell-runtime.js` and the JavaScript mock adapter surface
are retired as production entrypoints in this candidate. Their API names and
old test receipts confer no capability on the Rust application. Do not add an
empty npm facade simply to make `npm test` green: the applicable checks are
locked Cargo build/test, rustfmt, Clippy and the Python packaging/evidence tools.
A future JavaScript consumer requires an explicit versioned protocol adapter,
not in-process access to the authority or operation journal.

The production path remains native `main.rs` -> `NativeShellRuntime` ->
authenticated `LoopbackGatewayBackend`, with OS credentials loaded through the
credential store. One mutable Rust runtime serializes requests and the existing
private journal lock supplies cross-process ownership. This patch does not
introduce multiple simultaneous sessions or multi-window effect owners.

Generation zero is a valid owner genesis snapshot in the existing isolated
Linux product fixture. Preserve that compatibility: the UI projection remains
positive, while raw upstream generations are fenced separately. Displayed
revision is strictly increasing across every upstream generation in one
session. A prior revision cannot become current again on a generation change.

## Source identity, not historical proof

`CURRENT_SOURCE.json` enumerates committed implementation bytes. Its baseline
and historical commit are provenance only. The implementation map's sourceBase
identifies a source commit; it is not a claim that the metadata commit itself
was tested. Embedding the metadata commit's own hash in its contents would make
a circular identity requirement. The actual qualification receipt therefore
binds the checked-out HEAD and Git tree at execution time, along with the
candidate SHA, pinned main SHA, workflow SHA and dependency digests.

Generate public/restricted declarations, annotated tests, capability variants
and packaging paths from the actual checked-out source using
`scripts/hepta_ui_native_evidence.py inventory`. This lexical inventory does
not expand Rust macros, prove API reachability, or count test declarations as
passes. Its source digests are required alongside actual command observations.

For synthetic qualification, merge the pinned main and pinned candidate once
per profile using a deterministic Git commit with ordered parents. A conflict,
source fingerprint mismatch, dirty tracked tree, failed command, missing log,
skipped profile or cancelled profile is a failure, not a waiver.

## Consequences and release boundary

The existing DEVELOPMENT.md remains the application development manual.
`REMEDIATION-20260927.md` documents this patch, its commands, evidence semantics
and unfinished work. No historical test pass is inherited. Unsigned packages
are candidate artifacts, not notarized or production-signed distributions.
AccessKit configuration and delivered keyboard events do not establish real
screen-reader, IME or physical display acceptance.

CI evidence here is not an independent cryptographic attestation or a release
grant. Signed release-channel selection, credential custody, installed-host
acceptance and promotion remain separate. Until the entire required matrix
actually passes, even repository-controlled qualification remains pending.
