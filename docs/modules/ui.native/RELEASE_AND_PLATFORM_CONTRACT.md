# ui.native platform, accessibility, crash, and release contract

This document is normative for repository-controlled product preparation. It
does not claim production signing, physical accessibility acceptance, operator
promotion, activation, or release.

## Platform product matrix

The machine-readable projection is
`docs/modules/ui.native/generated/platform-matrix.json` and is regenerated from
the Rust manifest and platform metadata.

| Platform | Repository-controlled product shape | External release gate |
| --- | --- | --- |
| macOS | `Hepta Native.app`, macOS 14+, fixed bundle ID, high-DPI metadata, Keychain-backed credential boundary | Developer ID custody, entitlements review, notarization, stapling, installed-host acceptance |
| Windows | application directory, `asInvoker`, PerMonitorV2, long-path aware, Windows credential-store boundary | Authenticode, timestamping, installer/AppUserModelID registration, installed-host acceptance |
| Linux | AppDir layout, desktop entry, Wayland/X11 support, desktop keyring boundary | distribution package/repository ownership and signing, installed-host acceptance |

Unsigned development packages are deterministic ZIP artifacts. They contain the
main shell, updater helper, credential helper, platform metadata, a package
manifest, and per-binary SHA-256 digests. Unsigned packaging is not a substitute
for installer or release trust.

## Accessibility

Repository-controlled checks require:

- the AccessKit feature to remain declared and its adapter to compile in the
  executed application build;
- keyboard/focus behavior to have executed behavioral acceptance evidence;
- platform metadata to preserve high-DPI behavior;
- generated projections to fail when the accessibility feature or source
  contract disappears.

Physical acceptance remains mandatory for:

- VoiceOver, Narrator, and representative Linux screen readers;
- Chinese IME composition;
- focus restoration after dialogs, reconnect, and update restart;
- multi-monitor and mixed-DPI movement;
- reduced-motion and contrast behavior; and
- installed artifacts, not only test fixtures.

Receipts must record these as `false` until independent physical evidence is
attached.

The generated platform matrix checks source feature presence. It does not
establish compilation, keyboard/focus behavior or physical acceptance. Current
projection tooling therefore reports keyboard/focus acceptance as pending.

## Crash and recovery contract

The qualification profile covers shell crash, gateway loss, permission failure,
platform-effect uncertainty, update interruption, and package restart.

- `Prepared` records abandoned by a different session incarnation are
  quarantined.
- `Invoking` and `Indeterminate` records are reconciled with the platform owner.
- Terminal records never regress.
- Exact duplicates do not redispatch.
- Journal persistence uncertainty poisons the writer and prevents additional
  effects.
- Update state survives interruption and cannot be erased before installed
  target and running-process confirmation.
- Rollback may restore only the recorded predecessor and is verified before the
  transaction is cleared.

## Release evidence bundle

Every candidate evidence bundle must contain:

1. candidate, immutable implementation and executed subject SHA/tree identities,
   including ordered merge parents;
2. current qualification workflow commit and SHA-256 identity;
3. application and owner Cargo-lock identities;
4. executed Rust toolchain identity;
5. runner operating system, architecture, and image;
6. generated test-manifest digest;
7. complete check logs, measured outcomes and artifact digests;
8. qualification timestamp;
9. package-bound source dependency SBOM in CycloneDX 1.6 JSON and in-toto
   provenance, with their binding manifest;
10. unsigned package manifest, archive checksum, and packaged-binary smoke;
11. exact-head and deterministic synthetic-merge results; and
12. explicit false values for unobserved signing, physical accessibility, and
    release authority.

The sole current workflow, `.github/workflows/ui-native-qualification.yml`,
collects six exact-head/ordered-parent-merge platform bundles plus the exact
implementation storage subject. `scripts/hepta_ui_native_qualification_evidence.py`
seals platform observations and emits package-bound SBOM/provenance through
`scripts/hepta_ui_native_supply_chain.py`; the aggregate requires every subject
from the same run and attempt. It retains build, test, fault, package,
installed-Linux and storage evidence.

`tools/ui-native-projections/receipt.mjs` produces a local projection observation
bound to the current workflow and generated artifacts. Its optional SPDX 2.3
source inventory is auxiliary. Neither establishes workflow execution or replaces
the current qualification bundle. Historical workflow receipts remain provenance
for their original subjects and cannot promote a current candidate.

## Signing and notarization dry-run

`npm run signing-dry-run` validates that the committed platform identities and
metadata required by release owners are present and prints the expected signing
command sequence. It never loads credentials and always reports
`productionSigningObserved: false`.

Actual signing must run in an isolated release environment with independent key
custody. The release owner must verify the signed artifact digest against the
qualified unsigned candidate, allowing only the expected signature/container
transformation.

## Promotion and rollback

Promotion requires independent review of all applicable receipts and external
evidence. No source workflow may self-authorize release.

Rollback procedure:

1. stop new update promotion;
2. retain the failed candidate, updater journal, package receipt, and runtime
   health evidence;
3. verify the recorded predecessor digest and signature;
4. acquire the update transition lock;
5. restore the predecessor atomically;
6. restart the product;
7. verify the active artifact digest and authenticated runtime health;
8. mark the transaction rolled back only after both checks succeed; and
9. quarantine the installation and escalate when any rollback check is
   indeterminate or fails.

Deleting unresolved update state, replacing the predecessor, or reporting
restart alone as health is forbidden.
