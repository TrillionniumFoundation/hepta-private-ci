#!/usr/bin/env python3
"""Materialize the one-shot general-lease dispatch capability on PR #1007.

This migration is deliberately narrow and idempotent. It patches the native
contracts/Fleet boundary, the independent closed-world inventory, and the
human/machine projections that describe that boundary. It never pushes or
changes workflow files; the temporary materialization workflow owns validation
and the final fast-forward push.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def target(relative: str) -> Path:
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise RuntimeError(f"path escapes repository: {relative}")
    return path


def read(relative: str) -> str:
    return target(relative).read_text(encoding="utf-8")


def write(relative: str, content: str) -> None:
    target(relative).write_text(content, encoding="utf-8")


def replace_once(relative: str, old: str, new: str, *, present: str) -> None:
    content = read(relative)
    if present in content:
        return
    count = content.count(old)
    if count != 1:
        raise RuntimeError(
            f"{relative}: expected one predecessor for {present!r}, observed {count}"
        )
    write(relative, content.replace(old, new, 1))


def replace_optional(relative: str, old: str, new: str) -> None:
    content = read(relative)
    count = content.count(old)
    if count == 0:
        return
    if count != 1:
        raise RuntimeError(f"{relative}: optional predecessor is ambiguous: {count}")
    write(relative, content.replace(old, new, 1))


def append_section(relative: str, heading: str, body: str) -> None:
    content = read(relative)
    if heading in content:
        return
    if not content.endswith("\n"):
        content += "\n"
    write(relative, content + "\n" + body.strip() + "\n")


def patch_authority_lease() -> None:
    relative = "codex-rs/hepta-contracts/src/authority_lease.rs"
    replace_once(
        relative,
        '''impl fmt::Debug for LeaseVerifiedUseToken {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("LeaseVerifiedUseToken([REDACTED])")
    }
}

impl AuthorityLease {''',
        '''impl fmt::Debug for LeaseVerifiedUseToken {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("LeaseVerifiedUseToken([REDACTED])")
    }
}

/// Opaque, one-shot production dispatch capability.
///
/// The exact lease binding is selected and initially verified when this value
/// is created. Its private token is revalidated while the authority owner lock
/// is held across one bounded local irreversible boundary. The capability is
/// deliberately non-cloneable and non-serializable.
#[must_use = "dropping an authority dispatch binding performs no privileged effect"]
pub struct AuthorityDispatchBinding {
    verifier: AuthorityLeaseVerifier,
    token: LeaseVerifiedUseToken,
    expected: AuthorityLeaseBinding,
}

impl fmt::Debug for AuthorityDispatchBinding {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("AuthorityDispatchBinding([REDACTED ONE-SHOT CAPABILITY])")
    }
}

impl AuthorityDispatchBinding {
    /// Consume this capability exactly once at one already-selected local
    /// dispatch boundary and return its non-authorizing audit witness.
    pub fn dispatch<T>(
        self,
        dispatch_boundary: impl FnOnce(&VerifiedUseTokenWitnessV1) -> T,
    ) -> Result<(T, VerifiedUseTokenWitnessV1), AuthorityLeaseError> {
        self.verifier.with_dispatch_boundary_witness(
            self.token,
            &self.expected,
            dispatch_boundary,
        )
    }
}

impl AuthorityLease {''',
        present="pub struct AuthorityDispatchBinding",
    )
    replace_once(
        relative,
        '''    pub fn verify_use(
        &self,
        lease_id: &str,
        expected_revision: u64,
        expected: &AuthorityLeaseBinding,
    ) -> Result<LeaseVerifiedUseToken, AuthorityLeaseError> {''',
        '''    /// Bind one exact lease to the only production final-use capability.
    ///
    /// Product owners retain no raw verified token. Dispatch consumes the
    /// returned value and rechecks expiry, replacement, epoch and revocation
    /// while holding the owner lock across the local irreversible boundary.
    pub fn bind_dispatch(
        &self,
        lease_id: &str,
        expected_revision: u64,
        expected: &AuthorityLeaseBinding,
    ) -> Result<AuthorityDispatchBinding, AuthorityLeaseError> {
        let token = self.verify_use(lease_id, expected_revision, expected)?;
        Ok(AuthorityDispatchBinding {
            verifier: self.clone(),
            token,
            expected: expected.clone(),
        })
    }

    /// Compatibility/testing primitive. Production product callers are
    /// closed-world constrained to `bind_dispatch`.
    pub fn verify_use(
        &self,
        lease_id: &str,
        expected_revision: u64,
        expected: &AuthorityLeaseBinding,
    ) -> Result<LeaseVerifiedUseToken, AuthorityLeaseError> {''',
        present="pub fn bind_dispatch(",
    )

    content = read(relative)
    test_marker = "fn dispatch_binding_is_one_shot_and_emits_exact_witness()"
    if test_marker not in content:
        anchor = '''    fn lease_expiring_while_waiting_for_owner_lock(
        dispatch_boundary: bool,
    ) -> Result<(), AuthorityLeaseError> {'''
        tests = '''    #[test]
    fn dispatch_binding_is_one_shot_and_emits_exact_witness() {
        let (registry, _directory) = fixture().unwrap();
        let written = registry.put_lease(lease(), 0).unwrap();
        let dispatch = registry
            .verifier()
            .bind_dispatch("lease-one", 1, &binding())
            .unwrap();
        let (value, witness) = dispatch.dispatch(|_| 17).unwrap();
        assert_eq!(value, 17);
        assert_eq!(witness.boundary, VerifiedUseBoundaryV1::DispatchEntry);
        match witness.authority_ref {
            crate::VerifiedUseAuthorityRefV1::AuthorityLease(reference) => {
                assert_eq!(reference.owner_id, "security-authority");
                assert_eq!(reference.lease_id, "lease-one");
                assert_eq!(reference.lease_revision, 1);
                assert_eq!(reference.store_revision, written.store_revision);
            }
            other => panic!("unexpected authority witness: {other:?}"),
        }
    }

    #[test]
    fn dispatch_binding_revalidates_revocation_before_callback() {
        let (registry, _directory) = fixture().unwrap();
        registry.put_lease(lease(), 0).unwrap();
        let dispatch = registry
            .verifier()
            .bind_dispatch("lease-one", 1, &binding())
            .unwrap();
        registry.revoke("lease-one", 1, [8; 32]).unwrap();
        let mut called = false;
        let error = dispatch
            .dispatch(|_| {
                called = true;
            })
            .unwrap_err();
        assert_eq!(error, AuthorityLeaseError::Revoked);
        assert!(!called);
    }

'''
        if content.count(anchor) != 1:
            raise RuntimeError(f"{relative}: dispatch test insertion anchor drifted")
        write(relative, content.replace(anchor, tests + anchor, 1))


def patch_exports_and_fleet() -> None:
    replace_once(
        "codex-rs/hepta-contracts/src/lib.rs",
        '''pub use authority_lease::deliver_authority_lease_with_witness;
pub use authority_lease::dispatch_authority_lease_with_witness;''',
        '''pub use authority_lease::AuthorityDispatchBinding;
pub use authority_lease::deliver_authority_lease_with_witness;
pub use authority_lease::dispatch_authority_lease_with_witness;''',
        present="pub use authority_lease::AuthorityDispatchBinding;",
    )

    relative = "codex-rs/hepta-fleet/src/authority_port.rs"
    replace_once(
        relative,
        '''use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseError;
use codex_hepta_contracts::authority_lease::AuthorityLeaseVerifier;
use codex_hepta_contracts::authority_lease::dispatch_authority_lease_with_witness;''',
        '''use codex_hepta_contracts::authority_lease::AuthorityDispatchBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseError;
use codex_hepta_contracts::authority_lease::AuthorityLeaseVerifier;''',
        present="use codex_hepta_contracts::authority_lease::AuthorityDispatchBinding;",
    )
    replace_once(
        relative,
        '''        let token = self
            .verifier
            .verify_use(lease_id, expected_lease_revision, &binding)
            .map_err(FleetAuthorityError::Authority)?;
        let (result, witness) =
            dispatch_authority_lease_with_witness(&self.verifier, token, &binding, |_| {
                ledger.issue(now_ms, grant)
            })
            .map_err(FleetAuthorityError::Authority)?;''',
        '''        let dispatch_binding: AuthorityDispatchBinding = self
            .verifier
            .bind_dispatch(lease_id, expected_lease_revision, &binding)
            .map_err(FleetAuthorityError::Authority)?;
        let (result, witness) = dispatch_binding
            .dispatch(|_| ledger.issue(now_ms, grant))
            .map_err(FleetAuthorityError::Authority)?;''',
        present="let dispatch_binding: AuthorityDispatchBinding",
    )


def patch_inventory() -> None:
    relative = "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json"
    path = target(relative)
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    verifier = next(row for row in data["types"] if row["typeName"] == "AuthorityLeaseVerifier")
    verifier["privilegedMethods"]["bind_dispatch"] = "authority_lease_bind_dispatch"

    if not any(row["typeName"] == "AuthorityDispatchBinding" for row in data["types"]):
        index = data["types"].index(verifier) + 1
        data["types"].insert(
            index,
            {
                "typeName": "AuthorityDispatchBinding",
                "sourcePath": "codex-rs/hepta-contracts/src/authority_lease.rs",
                "privilegedMethods": {"dispatch": "authority_lease_dispatch_binding"},
                "nonPrivilegedMethods": [],
            },
        )

    by_id = {row["id"]: row for row in data["boundaries"]}
    by_id["authority_lease_verify_use"]["allowedCallers"] = []
    by_id["authority_lease_dispatch_witness"]["allowedCallers"] = []

    def insert_after(existing_id: str, row: dict[str, Any]) -> None:
        if any(candidate["id"] == row["id"] for candidate in data["boundaries"]):
            return
        index = next(
            i for i, candidate in enumerate(data["boundaries"])
            if candidate["id"] == existing_id
        )
        data["boundaries"].insert(index + 1, row)

    insert_after(
        "authority_lease_verify_use",
        {
            "id": "authority_lease_bind_dispatch",
            "typeMarker": "AuthorityLeaseVerifier",
            "definitionPath": "codex-rs/hepta-contracts/src/authority_lease.rs",
            "callPatterns": [
                r"\.\s*bind_dispatch\s*\(",
                r"AuthorityLeaseVerifier\s*::\s*bind_dispatch\s*\(",
            ],
            "allowedCallers": ["codex-rs/hepta-fleet/src/authority_port.rs"],
        },
    )
    insert_after(
        "authority_lease_dispatch_raw",
        {
            "id": "authority_lease_dispatch_binding",
            "typeMarker": "AuthorityDispatchBinding",
            "definitionPath": "codex-rs/hepta-contracts/src/authority_lease.rs",
            "callPatterns": [
                r"\bdispatch_binding\s*\.\s*dispatch\s*\(",
                r"AuthorityDispatchBinding\s*::\s*dispatch\s*\(",
            ],
            "allowedCallers": ["codex-rs/hepta-fleet/src/authority_port.rs"],
        },
    )
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def patch_callers_manifest() -> None:
    relative = "CALLERS.toml"
    replace_once(
        relative,
        '''  "authority_lease_verify_use",
  "authority_lease_delivery",''',
        '''  "authority_lease_verify_use",
  "authority_lease_bind_dispatch",
  "authority_lease_delivery",
  "authority_lease_dispatch_binding",''',
        present='"authority_lease_bind_dispatch"',
    )
    replace_optional(
        relative,
        'caller_markers = ["FinalUseAuthority::open_state_dir", "FinalUseAuthority", "authority"]',
        'caller_markers = ["FinalUseAuthority::", "FinalUseAuthority", "authority"]',
    )
    replace_once(
        relative,
        '''[[boundary]]
id = "authority_lease_verify_use"
symbol = "AuthorityLeaseVerifier::verify_use"
call_pattern = '\\.\\s*verify_use\\s*\\('
caller_type_marker = "AuthorityLeaseVerifier"
definition_path = "codex-rs/hepta-contracts/src/authority_lease.rs"
definition_markers = ["pub struct AuthorityLeaseVerifier", "pub fn verify_use(", "LeaseVerifiedUseToken"]
product_callers = ["codex-rs/hepta-fleet/src/authority_port.rs"]
caller_markers = ["AuthorityLeaseVerifier", ".verify_use(", "FleetAuthorityPort"]

[[boundary]]
id = "authority_lease_delivery"''',
        '''[[boundary]]
id = "authority_lease_verify_use"
symbol = "AuthorityLeaseVerifier::verify_use"
call_pattern = '\\.\\s*verify_use\\s*\\('
caller_type_marker = "AuthorityLeaseVerifier"
definition_path = "codex-rs/hepta-contracts/src/authority_lease.rs"
definition_markers = ["pub struct AuthorityLeaseVerifier", "pub fn verify_use(", "LeaseVerifiedUseToken"]
product_callers = []
caller_markers = []

[[boundary]]
id = "authority_lease_bind_dispatch"
symbol = "AuthorityLeaseVerifier::bind_dispatch"
call_pattern = '\\.\\s*bind_dispatch\\s*\\('
caller_type_marker = "AuthorityLeaseVerifier"
definition_path = "codex-rs/hepta-contracts/src/authority_lease.rs"
definition_markers = ["pub fn bind_dispatch(", "AuthorityDispatchBinding", "self.verify_use("]
product_callers = ["codex-rs/hepta-fleet/src/authority_port.rs"]
caller_markers = ["AuthorityDispatchBinding", ".bind_dispatch(", "FleetAuthorityPort"]

[[boundary]]
id = "authority_lease_delivery"''',
        present='id = "authority_lease_bind_dispatch"',
    )
    replace_once(
        relative,
        '''[[boundary]]
id = "authority_lease_dispatch_witness"
symbol = "dispatch_authority_lease_with_witness"
definition_path = "codex-rs/hepta-contracts/src/authority_lease.rs"
definition_markers = ["pub fn dispatch_authority_lease_with_witness", "VerifiedUseTokenWitnessV1", "with_dispatch_boundary_witness"]
product_callers = ["codex-rs/hepta-fleet/src/authority_port.rs"]
caller_markers = ["dispatch_authority_lease_with_witness", "issue_with_witness", "FleetAuthorityPort"]''',
        '''[[boundary]]
id = "authority_lease_dispatch_binding"
symbol = "AuthorityDispatchBinding::dispatch"
call_pattern = '\\bdispatch_binding\\s*\\.\\s*dispatch\\s*\\('
caller_type_marker = "AuthorityDispatchBinding"
definition_path = "codex-rs/hepta-contracts/src/authority_lease.rs"
definition_markers = ["pub struct AuthorityDispatchBinding", "pub fn dispatch<T>(", "with_dispatch_boundary_witness"]
product_callers = ["codex-rs/hepta-fleet/src/authority_port.rs"]
caller_markers = ["AuthorityDispatchBinding", "dispatch_binding", ".dispatch("]

[[boundary]]
id = "authority_lease_dispatch_witness"
symbol = "dispatch_authority_lease_with_witness"
definition_path = "codex-rs/hepta-contracts/src/authority_lease.rs"
definition_markers = ["pub fn dispatch_authority_lease_with_witness", "VerifiedUseTokenWitnessV1", "with_dispatch_boundary_witness"]
product_callers = []
caller_markers = []''',
        present='id = "authority_lease_dispatch_binding"',
    )
    replace_once(
        relative,
        '''required = ["pub struct AuthorityLeaseRegistry", "pub struct AuthorityLeaseVerifier", "pub fn open_state_dir_with_trust(", "pub fn verifier(", "pub fn verify_use(", "pub fn with_dispatch_boundary<T>(", "pub fn deliver_authority_lease_with_witness", "pub fn dispatch_authority_lease_with_witness", "VerifiedUseTokenWitnessV1", "pub fn revoke(", "pub fn prune_expired_leases(", "retired_revisions", "AntiRollbackViolation", "pub fn advance_epoch("]''',
        '''required = ["pub struct AuthorityLeaseRegistry", "pub struct AuthorityLeaseVerifier", "pub struct AuthorityDispatchBinding", "pub fn open_state_dir_with_trust(", "pub fn verifier(", "pub fn bind_dispatch(", "pub fn verify_use(", "pub fn dispatch<T>(", "pub fn with_dispatch_boundary<T>(", "pub fn deliver_authority_lease_with_witness", "pub fn dispatch_authority_lease_with_witness", "VerifiedUseTokenWitnessV1", "pub fn revoke(", "pub fn prune_expired_leases(", "retired_revisions", "AntiRollbackViolation", "pub fn advance_epoch("]''',
        present='"pub struct AuthorityDispatchBinding"',
    )
    replace_once(
        relative,
        '''[[protected_file]]
path = "codex-rs/hepta-bao-adapter/src/https_consumer.rs"''',
        '''[[protected_file]]
path = "codex-rs/hepta-fleet/src/authority_port.rs"
required = ["AuthorityDispatchBinding", ".bind_dispatch(", "dispatch_binding", ".dispatch(", "issue_with_witness"]
forbidden = [".verify_use(", "dispatch_authority_lease_with_witness"]

[[protected_file]]
path = "codex-rs/hepta-bao-adapter/src/https_consumer.rs"''',
        present='path = "codex-rs/hepta-fleet/src/authority_port.rs"\nrequired = ["AuthorityDispatchBinding"',
    )


def patch_closed_world_regression() -> None:
    relative = "qa/b4-no-bypass/test_kernel_authority_closed_world.py"
    replace_once(
        relative,
        '''    def test_type_anchored_callers_match_independent_closed_set(self) -> None:
        ignored = ("/tests/", "/examples/", "_tests.rs")''',
        '''    def test_fleet_general_lease_path_uses_only_one_shot_dispatch_binding(
        self,
    ) -> None:
        code = self.lexical_code("codex-rs/hepta-fleet/src/authority_port.rs")
        for marker in (
            "AuthorityDispatchBinding",
            ".bind_dispatch(",
            "dispatch_binding",
            ".dispatch(",
        ):
            self.assertIn(marker, code)
        for forbidden in (".verify_use(", "dispatch_authority_lease_with_witness"):
            self.assertNotIn(forbidden, code)

    def test_type_anchored_callers_match_independent_closed_set(self) -> None:
        ignored = ("/tests/", "/examples/", "_tests.rs")''',
        present="test_fleet_general_lease_path_uses_only_one_shot_dispatch_binding",
    )


def patch_docs_and_map() -> None:
    append_section(
        "docs/modules/kernel.authority/TECHNICAL.md",
        "## Production general-lease dispatch binding",
        '''
## Production general-lease dispatch binding

`AuthorityDispatchBinding` is the only closed-world product final-use path for a
general authority lease. `AuthorityLeaseVerifier::bind_dispatch` captures the
exact binding and a non-cloneable verified token; `dispatch` consumes both while
the owner mutex remains held through one bounded local irreversible boundary.
The compatibility `verify_use`, `with_verified_use`, `with_dispatch_boundary`,
and free witness helpers remain available to tests and migration code, but
`CALLERS.toml` and the independent B4 inventory admit no product caller for
those raw paths. `runtime.fleet` is migrated to the bound capability and cannot
retain or serialize a raw lease token.
''',
    )
    append_section(
        "docs/modules/kernel.authority/LINEARIZATION.md",
        "## General-lease bound dispatch",
        '''
## General-lease bound dispatch

For a production general-lease effect, the linearization sequence is:

1. the owner computes the exact semantic `AuthorityLeaseBinding`;
2. `bind_dispatch` verifies the exact lease revision and creates a private,
   one-shot `AuthorityDispatchBinding`;
3. `dispatch` reacquires the authority state mutex, resamples trusted time and
   rechecks epoch, replacement, revocation, binding and expiry;
4. the bounded local irreversible callback runs while that same mutex is held;
5. a `DispatchEntry` witness is emitted and the capability is consumed.

A revocation that commits first denies dispatch. A revocation that starts after
step 3 cannot commit until the local boundary returns and is therefore ordered
after that boundary. Network acknowledgement and long-running remote work remain
outside the mutex and require their own durable-intent/reconciliation protocol.
''',
    )
    append_section(
        "docs/modules/kernel.authority/TRACEABILITY.md",
        "### Bound general-lease product path",
        '''
### Bound general-lease product path

| Requirement | Native implementation | Closed product caller | Regression/evidence |
| --- | --- | --- | --- |
| No product retention of a raw general-lease token | `AuthorityDispatchBinding`, `AuthorityLeaseVerifier::bind_dispatch` | `FleetAuthorityPort::issue_with_witness` | B4 exact-caller scan and Fleet authority tests |
| Revoke/replace/expiry rechecked at the irreversible boundary | `AuthorityDispatchBinding::dispatch` → `with_dispatch_boundary_witness` | `runtime.fleet` lease issuance | `dispatch_binding_revalidates_revocation_before_callback` and dispatch serialization tests |
| Serializable evidence grants no authority | `VerifiedUseTokenWitnessV1` with `DispatchEntry` | Fleet receipt composition | `dispatch_binding_is_one_shot_and_emits_exact_witness` |
''',
    )
    append_section(
        "docs/lane-a-foundation/kernel.authority/CURRENT_IMPLEMENTATION.md",
        "## One-shot general-lease dispatch closure",
        '''
## One-shot general-lease dispatch closure

The repository-controlled production caller for general leases now receives an
opaque `AuthorityDispatchBinding`, not a raw `LeaseVerifiedUseToken`. The
capability is non-cloneable/non-serializable, consumes itself at one Fleet owner
mutation and emits a non-authorizing `DispatchEntry` witness. Raw verification
and dispatch helpers remain compatibility/test primitives with an empty product
caller set enforced independently by `CALLERS.toml` and B4.
''',
    )

    relative = "docs/modules/kernel.authority/IMPLEMENTATION_MAP.json"
    path = target(relative)
    data = json.loads(path.read_text(encoding="utf-8"))
    operation = next(
        row for row in data["operations"]
        if row["operation"] == "authority_lease_registry"
    )
    operation["nativeSymbol"] = (
        "AuthorityLeaseRegistry / AuthorityLeaseVerifier / AuthorityDispatchBinding"
    )
    operation["state"] = (
        "source_implemented_one_shot_dispatch_binding_and_exact_predecessor_regressions_not_product_activated"
    )
    operation["designOperation"] = (
        "put_bind_dispatch_verify_revoke_prune_with_retired_revision_lineage_epoch_authority_lease"
    )
    caller = next(
        row for row in data["productCallers"] if row["id"] == "runtime.fleet.issue"
    )
    caller["nativeSymbol"] = (
        "FleetAuthorityPort::issue_with_witness / AuthorityDispatchBinding"
    )
    caller["state"] = (
        "source_composed_one_shot_owner_boundary_not_product_process_activated"
    )
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    patch_authority_lease()
    patch_exports_and_fleet()
    patch_inventory()
    patch_callers_manifest()
    patch_closed_world_regression()
    patch_docs_and_map()
    print("kernel.authority one-shot dispatch materialized")


if __name__ == "__main__":
    main()
