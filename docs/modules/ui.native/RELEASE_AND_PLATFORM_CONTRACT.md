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

- the AccessKit adapter to be compiled;
- keyboard/focus behavior to remain in the qualification fixture set;
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

1. exact source SHA and source tree;
2. native and projection workflow SHA-256 values;
3. aggregate dependency-lock digest;
4. Node and Rust toolchain identities;
5. runner operating system, architecture, and image;
6. generated test-manifest digest;
7. aggregate generated-artifact digest;
8. qualification timestamp;
9. source dependency SBOM in SPDX 2.3 JSON;
10. unsigned package manifest, archive checksum, and packaged-binary smoke;
11. exact-head and deterministic synthetic-merge results; and
12. explicit false values for unobserved signing, physical accessibility, and
    release authority.

The projection workflow emits the receipt and SBOM. The native workflow emits
build, test, fault, package, installed-Linux, and artifact evidence.

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
