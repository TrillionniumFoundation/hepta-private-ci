# Original A/Material and Trainer constructor separation

This is an isolated, unformatted, uncompiled and unexecuted two-file test-fixture proposal. It builds on the exact `e54fe13095d93a559de5c2816a15f5171774f7cf` provider afterimage from the pre-held-expiry packet `7e7469819f3729305d6da386d6ae000e157b5925`. The existing combined candidate and source refs are untouched.

## Concrete behavior

`UnstartedMaterialProvider::new_with_original_work_deadline` owns the same actual A Session, one ledger writer, original Decision and Outcome signatures, original Material configuration, and original Material command owner. It returns before opening Trainer custody files, creating a Trainer or starting any `material_ports` test handler. The original A/Decision/Outcome/Material construction subrange is preserved byte for byte.

The existing `UnstartedProvider::new` and `new_with_original_work_deadline` remain the old callers' interface. They await this Material construction once, then open the same four custody files and start the same four existing test handlers once, in their original order. The same original Bootstrap constructor consumes those inputs. No original signature, append, A execution, or Material construction is repeated. The old `original_bytes` and `finish` implementations remain byte for byte unchanged.

The new Material-only owner keeps A and its original files alive while a future caller serves its public original Material endpoints. Its explicit `finish` stops and joins A and checks that no external Material service clone remains. It does not claim to join tasks that the future caller owns. There is no new service responder, synthetic receipt, Training getter, writer recovery, lease, signature or authority factory in the new module.

## Why this is needed

The former constructor always made a Trainer and four same-UID `cfg(test)` Material peers. Using that object in an A child would not establish that a distinct Trainer process obtained its actual inputs through the original public peer admission. The new type makes a Material-only return point explicit, so an A child can serve the actual endpoints before the Trainer child binds its own streams and uses its own custody files. Neither physical streams nor typed clients have yet been created across processes by this package.

The old local constructor remains a mechanism fixture with its original same-UID test-port behavior. This split does not reclassify those ports as production endpoints.

## Preserved contracts and limits

- The exact caller-selected work expiry is forwarded unchanged to the same original freeze point. The old default path still samples the same original 900-second fixture limit there.
- The existing four Material test transports retain their original 500-ms transport behavior and 300-second lifetime. Custody files are still opened before starting those transports.
- Full A input, original run identity, original Decision and Outcome signatures, full ledger, baseline and original Material checks are unchanged.
- A construction error still explicitly stops and joins A. An error while attaching the old Trainer still stops and joins A and finishes every already-started original test peer. No failing Result is turned into success.
- New Rust remains in a `*_tests.rs` module reached from the existing test-only provider support. No ignored-path rules or product caller lists are changed.

## Remaining production boundary

The extracted code deliberately retains `VersionFixture::new_initial`, which uses the original test Current store. It does not provide production `RootAuthorityDirectory` custody. Production Current preparation and publication require the original Root-owned `Arc<NeuronGenerationCurrentOwnerV1>` and perform actual CAS/current reads, not merely snapshot comparison. A UID-60001 fixture file or private key cannot be copied, chowned or decoded to stand in for that owner in UID 0.

The full three-UID flow still needs a reviewed concrete Root Current/issuer service arrangement, actual public Material-to-Trainer endpoint binding, and parent-preheld-before-child first admission. This package is a usable constructor separation for that work, not a public Root loop or a completed useful task. The original FinalUse consumer nonce store and the UID-0 Host issuer are separate authorities; this proposal does not reopen one as the other.

## Verification performed here

The preparation script checks the exact preimage, reconstructs the parent by inverse substitution, checks the full original A/Material subrange and original parent cleanup suffix, and checks the original four test-port call counts. A private copy is used for `git apply --check` and exact afterimage comparison. These are pure source/patch checks only. No formatter, Rust compiler, Rust test, source qualification gate, native operation or H request has been run. No real independent B, new C, daemon recovery or Root execution is asserted.
