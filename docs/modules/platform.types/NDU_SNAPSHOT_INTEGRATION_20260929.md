# Owner-pinned numeric V2 integration — 2026-09-29

This follow-on to `OPTIMIZATION_CLOSURE_20260929.md` closes the source-level NDU
snapshot-composition gap through the existing authenticated owner. It is not a
native-test pass, independent approval, registry publication or deployment receipt.

## Single owner and explicit compatibility

`NduAuthenticatedOwnerV1::open_with_numeric_registry_snapshot` takes the existing
registry value and an independently provisioned `RegistrySnapshotIdentityV1`.
The owner verifies the registry's content digest against that pin before opening
its existing projection store. The pin is private and immutable for that owner
lifetime; no request or received receipt can select its generation.

The original `open` and `open_with_numeric_registry` constructors keep their V1
behavior and policy commitments. They do not infer a generation from a registry
content digest. An explicitly snapshot-configured owner rejects the old
`admit_utility_signal` entrypoint rather than returning downgraded evidence.

The new public surface is additive:

| API | Meaning |
| --- | --- |
| `open_with_numeric_registry_snapshot` | Explicit owner-lifetime generation/content pin |
| `numeric_registry_snapshot` | Read-only observation of that pin |
| `admit_utility_signal_v2` | Checked local issuance using the owner's generation |
| `verify_utility_signal_v2` | Full received-receipt recomputation against the owner's pin |
| `NduRegisteredUtilitySignalV2` | Private-field signal, axis projection and non-authorizing receipt |

V1 and V2 share utility-axis projection, target-schema checks and the existing
platform.types converter. Locally issued receipts do not trigger a redundant
second conversion. Received receipts always call `verify_for_snapshot`; the
self-contained `verify` method is not substituted for owner-current policy.

## Versioned identities and ordinary evaluation

The V2 owner policy commits HPTC schema 2 over `policy_digest`,
`registry_digest` and `registry_generation`, with type identity
`utility.ndu:production-policy-numeric-snapshot-v2`.

The ordinary `evaluate` method selects admission from immutable owner
configuration. Its V2 contribution-support commitment uses
`utility.ndu:registered-contribution-support-v2`, schema 2, and the fields
`numeric_admission` and `source_support`. The underlying V2 admission includes
the snapshot and all profile/normalization/conversion commitments.

Missing source support, invalid axes and invalid numeric inputs still reject.
Both V1 and V2 then call the same `evaluate_candidates_with_policy`. There is no
second evaluator, writer, authority issuer or alternate projection store.

The existing `final_use_binding` includes the owner policy identity, so different
snapshot generations produce different scope and payload bindings even for the
same command identity. `apply_mutation` still claims and rechecks the exact
kernel-authority grant before the existing store operation. The mutation path
and legacy policy hashing functions are unchanged by this integration.

## Provisioning, rotation and operational limits

Registry authentication, durable anti-rollback state and generation selection
remain with the provisioning authority. This constructor does not authenticate
arbitrary caller-supplied pins, persist a latest generation or publish a snapshot.
The owner compares received evidence to its pin; it does not discover global
freshness by hashing registry bytes.

A rotation must use the existing runtime lifecycle: fence/drain the old owner,
independently provision the new pin, and open the new owner with the new policy
identity. A newly opened owner does not revoke an old owner by itself. Existing
kernel authority must still fence or revoke old grants and control final use.
No setter mutates a live owner's pin, and failure never falls back to V1.

Historical V1 receipts retain their original meaning. Converting the same
numeric values does not make a V1 receipt a V2 generation witness. Prompt V1,
Prompt V2, HPTC V1, topology and the three manifest encodings are unchanged in
this follow-on. Supervisor trusted-clock validity, host-observation freshness,
random-counter consumption and physical-device execution remain their owners'
separate obligations.

## Regression and evidence map

`codex-rs/hepta-ndu/src/owner_numeric_snapshot_tests.rs` contains eight native
regressions, compiled into the existing NDU library test target on Unix:

1. complete V2 receipt verification and V1 numeric-output/conversion parity;
2. rejection of an older generation that still passes self-contained verification;
3. same-generation wrong-registry and changed-input rejection;
4. snapshot mismatch rejection before any projection-store open;
5. explicit V2 downgrade rejection and preserved legacy V1 admission;
6. ordinary evaluation and final-use scope/payload generation binding;
7. preservation of missing-support and invalid-axis rejection;
8. exact signed-grant enforcement and replay rejection through the existing writer.

The existing consumer matrix retains all prior entries and adds the named pinned
numeric V2 source consumer. Exact provenance includes both the new implementation
and its tests, in addition to the unchanged root-tree evidence. The existing deep
source-head and synthetic-merge lanes run the complete NDU library tests and
strict NDU lint; no reduced success workflow or replacement receipt is introduced.

From a full checkout, use the existing repository commands:

```sh
cd codex-rs
just test --locked -p codex-hepta-ndu --lib
just fix -p codex-hepta-ndu
just fmt
```

The authoring environment verified the original edited blob identities and
byte-preservation of nine existing effect/policy functions. It had no Rust,
Cargo, rustfmt or Clippy toolchain. The eight Rust tests are checked-in test
source, not locally executed passes. Final exact-head and deterministic-merge
execution, eligible independent review and external provisioning/host/operator
acceptance remain required. No queued run, static check or source document
promotes those states.
