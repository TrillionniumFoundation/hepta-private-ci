# Native release hardening continuation — 2026-09-27

## Scope and authority

This continuation starts at PR #1059, commit
`a19349609731fb5700cf6d89edffc288b2f4eee4`. Its six-bundle aggregator,
read-only formatting proposal, journal v4 checksums, forensic previous snapshot
and persistence-failure fencing are inherited, not newly implemented here.
The existing complete Rust source and product version `0.1.0` are retained.
Historical-source reconstruction and version `0.0.0` were inaccurate descriptions
of this product candidate; the JavaScript projection tool is not the product.

No main merge, protection bypass, signing, deployment or release is performed.
`productionImplementation`, `productionQualified` and `releaseAuthorized` remain
false. This document is a development record, not an acceptance receipt.

## Implemented changes and regression coverage

| Requirement | Change | Regression evidence source |
| --- | --- | --- |
| NATIVE-EFFECT-NEGATIVE-001 | Both successful and unsuccessful launcher exits remain indeterminate. A launcher can apply a side effect and subsequently fail. An exit code cannot manufacture terminal negative evidence. | `src/platform_terminality_tests.rs`: two Unix child-process tests, including a child that writes an observable file before exiting 7. |
| NATIVE-HTTP-FRAMING-001 | Exact HTTP/1.1 status grammar; printable header values with only SP/HTAB trimming; nonempty decimal Content-Length; header size and body-start consistency checks. Existing rejection of Transfer-Encoding remains. | `src/native_http_tests.rs`: six tests, four newly added; controls, Unicode whitespace, duplicate framing, invalid lengths and deadline retention. |
| NATIVE-TRUST-IMPORT-001 | Reject duplicate JSON key IDs, weak Ed25519 keys and duplicate encoded public-key material within a trust set. Verify endpoint/update signatures using the pinned library's strict verifier. | `tests/trusted_key_regressions.rs`: five integration tests. |
| NATIVE-PACKAGE-CLOSURE-001 | Unsigned package schema v2 binds the existing product version and all five payload files: three executables, platform metadata and packaging notice. No extra/missing files, duplicate fields, digest disagreement or production-authority flags are accepted. | `tools/tests/test_package_security.py`, discovered by `scripts/test_hepta_ui_native_package_security.py` in the existing six-subject Python lane. |
| NATIVE-PACKAGE-EXTRACT-001 | Bound member count and expanded sizes; reject traversal, Windows devices/ADS/backslash/trailing aliases, case collisions, non-regular or privileged members. Validate and extract through one ZIP handle; rehash copied bytes. Never recursively delete an existing output/destination. | The same 33-test package suite includes extraction-time mutation, metadata substitution and sentinel-preservation tests. |
| NATIVE-PROJECTION-001 | The projection generator recognizes the existing crate-private running-process confirmation API, without widening Rust visibility. Regenerate the API and discovered integration-test registries. | `tools/ui-native-projections/test/generate.test.mjs`: six tests after adding the visibility regression. |

## Compatibility and limits

The unsigned package validator deliberately rejects schema v1, unknown payload
files and malformed or placeholder product versions. Consumers must regenerate
candidate packages with the v2 builder; legacy packages are not silently trusted.
The three existing executable paths and `binarySha256` remain unchanged.
Every platform payload file is now covered by `fileSha256`. Archive/file hashes
are integrity checks, not signatures, notarization or release authority.

Trust-set tightening requires one unique encoded key per ID within a file.
It prevents a revoked and a live alias sharing material in that same set; it does
not establish persistent cross-version key history, monotonic epochs, emergency
revocation distribution or signing-key custody. Those remain open work.

Launcher observations intentionally retain uncertainty. A queryable operation-ID
broker, idempotent OS APIs and operator reconciliation still have to be implemented.
The path-string OS adapters still need handle-based file identity fencing.
Package extraction hardening does not claim immunity to an attacker who can
mutate the extraction directory itself concurrently; private-directory ownership
and OS-specific handle/ACL validation remain necessary.

## Validation actually performed in the authoring environment

The package suite ran with 33 tests passing, zero skips, on the local Linux
Python environment. It exercised real ZIP reads/writes and extraction, but the
binary contents were deliberate fixtures: no compiled product, desktop session
or production installer is implied. Its reproducibility test builds all three
package shapes twice and compares their byte digests.

The projection generator, npm clean install (no dependencies), syntax checks,
projection verification and six Node tests ran locally. Projection checks inspect
source declarations and inventories; they are not Rust execution evidence.

There is no Rust toolchain in the authoring environment. Eleven new Rust tests
(two launcher, four HTTP and five trust tests) are committed for hosted execution,
not reported as passing. Formatting, Clippy, app/owner tests, release builds,
crash profiles, packaged-binary execution and Linux GUI/keyring/gateway acceptance
must pass on the final exact candidate and deterministic merge subjects.

Reproduction commands:

```sh
python3 -m unittest discover -s scripts -p 'test_hepta_ui_native_*.py' -v
python3 apps/hepta-native/tools/package_unsigned.py --self-test
(cd tools/ui-native-projections && npm ci --ignore-scripts --no-audit --no-fund && npm run lint && npm run typecheck && npm test)
cargo +1.95.0 fmt --manifest-path apps/hepta-native/Cargo.toml --check
cargo +1.95.0 clippy --manifest-path apps/hepta-native/Cargo.toml --locked --all-targets --all-features -- -D warnings
cargo +1.95.0 test --manifest-path apps/hepta-native/Cargo.toml --locked --all-targets
```

The retained workflow supplies owner builds/tests and the six complete product
subjects. A failed, cancelled, missing or skipped subject is not a qualification.
Fresh metadata records source identity only; it cannot close execution gaps.

## Remaining release blockers

1. Actual six-subject exact-source results, successful aggregate and required-check
   enforcement. The connected GitHub integration returned HTTP 403 when reading
   main branch protection; no administrative protection change was made.
2. Protected-main convergence after qualification, with no forced merge or rewrite.
3. Queryable OS effect receipts, resource handle fencing, complete crash-boundary
   reconciliation, and Windows durable replacement/ACL/file-identity validation.
4. Production macOS signed/notarized bundle transactions, Windows signed installers
   and updater ownership, Linux signed package/repository ownership, complete
   released-artifact SBOM/provenance and persistent key rotation policy.
5. Installed upgrade/rollback matrices, real authority-to-OS end-to-end acceptance,
   physical IME/DPI/screen-reader and long-running resource measurements, independent
   security review and independent release approval.

These include unimplemented engineering, not only missing external receipts.
No success evidence or release approval is synthesized to close this list.
