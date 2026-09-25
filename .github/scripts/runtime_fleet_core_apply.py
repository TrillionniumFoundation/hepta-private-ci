#!/usr/bin/env python3
"""One-shot, fail-closed runtime.fleet convergence helper.

This script only edits the checked-out candidate. The invoking workflow owns
validation, commit creation, exact-parent checks, synthetic-merge execution,
and the final non-force push.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FLEET = ROOT / "codex-rs/hepta-fleet/src"


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def replace_exact(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return source.replace(old, new)


def add_after(source: str, anchor: str, addition: str, label: str) -> str:
    if addition.strip() in source:
        return source
    return replace_exact(source, anchor, anchor + addition, label)


def add_before(source: str, anchor: str, addition: str, label: str) -> str:
    if addition.strip() in source:
        return source
    return replace_exact(source, anchor, addition + anchor, label)


def restore_historical_core() -> None:
    head = os.environ["HISTORICAL_HEAD"]
    paths = [
        "codex-rs/hepta-fleet/src/allocation_model.rs",
        "codex-rs/hepta-fleet/src/allocation_store.rs",
        "codex-rs/hepta-fleet/src/allocation_store_tests.rs",
        "codex-rs/hepta-fleet/src/lease_ledger.rs",
        "codex-rs/hepta-fleet/src/lease_ledger_tests.rs",
        "codex-rs/hepta-fleet/src/placement.rs",
        "codex-rs/hepta-fleet/src/placement_tests.rs",
        "codex-rs/hepta-fleet/src/resource_model.rs",
        "codex-rs/hepta-fleet/src/resource_model_tests.rs",
        "codex-rs/hepta-fleet/src/runtime_use.rs",
        "codex-rs/hepta-fleet/src/runtime_use_tests.rs",
    ]
    run("git", "cat-file", "-e", f"{head}^{{commit}}")
    run("git", "checkout", head, "--", *paths)


def patch_lib() -> None:
    path = FLEET / "lib.rs"
    source = path.read_text()
    source = add_after(source, "mod allocation_model;\n", "mod allocation_store;\n", "allocation_store module")
    source = add_after(source, "mod model;\n", "mod placement;\n", "placement module")
    source = add_after(
        source,
        "mod release;\n",
        "mod resource_model;\nmod runtime_use;\n",
        "resource/runtime modules",
    )
    source = add_before(
        source,
        "pub use authority_port::FleetAuthorityError;\n",
        "pub use allocation_store::FleetAllocationSnapshot;\n"
        "pub use allocation_store::FleetAllocationStore;\n"
        "pub use allocation_store::FleetAllocationStoreError;\n",
        "allocation store exports",
    )
    source = add_after(
        source,
        "pub use authority_port::FleetAuthorityPort;\n",
        "pub use lease_ledger::FleetConsumptionObservationV1;\n"
        "pub use lease_ledger::FleetReconciliationOutcomeV1;\n",
        "reconciliation exports",
    )
    source = add_before(
        source,
        "pub use registry::AgentRecord;\n",
        "pub use placement::FLEET_PLACEMENT_POLICY_VERSION;\n"
        "pub use placement::FleetCapacityMeasurementV1;\n"
        "pub use placement::FleetPlacementCommitV1;\n"
        "pub use placement::FleetPlacementError;\n"
        "pub use placement::FleetPlacementPlanV1;\n"
        "pub use placement::FleetPlacementRequestV1;\n"
        "pub use placement::admit_host_with_authority;\n"
        "pub use placement::capacity_observation_binding;\n"
        "pub use placement::commit_placement_with_authority;\n"
        "pub use placement::placement_authority_binding;\n"
        "pub use placement::plan_placement_v1;\n",
        "placement exports",
    )
    source = add_before(
        source,
        "pub use revocation_control::FleetNodeRevocationState;\n",
        "pub use resource_model::FleetResourceAxisV1;\n"
        "pub use resource_model::FleetResourceLimitClassV1;\n"
        "pub use resource_model::FleetResourceUnitV1;\n"
        "pub use resource_model::FleetResourceVectorV1;\n"
        "pub use runtime_use::FleetAllocationGrantV1;\n"
        "pub use runtime_use::FleetAllocationUseV1;\n"
        "pub use runtime_use::FleetReconciliationCommitV1;\n"
        "pub use runtime_use::FleetRuntimeUseError;\n"
        "pub use runtime_use::admit_runtime_use_v1;\n"
        "pub use runtime_use::consumption_observation_binding;\n"
        "pub use runtime_use::read_active_grants_v1;\n"
        "pub use runtime_use::reconcile_consumption_with_authority;\n",
        "resource/runtime exports",
    )
    if "mod resource_model_tests;" not in source:
        source += '\n#[cfg(test)]\n#[path = "resource_model_tests.rs"]\nmod resource_model_tests;\n'
    path.write_text(source)


def patch_authority_port() -> None:
    path = FLEET / "authority_port.rs"
    source = path.read_text()
    source = replace_exact(
        source,
        "    hash_u64(&mut scope, grant.resources.cpu_millis);\n"
        "    hash_u64(&mut scope, grant.resources.memory_bytes);\n"
        "    hash_u64(&mut scope, grant.resources.accelerator_millis);\n",
        "    hash_u64(&mut scope, grant.resources.concurrent_turns);\n"
        "    hash_u64(&mut scope, grant.resources.memory_mib);\n"
        "    hash_u64(&mut scope, grant.resources.tool_processes);\n"
        "    hash_u64(&mut scope, grant.resources.turn_queue_slots);\n",
        "authority resource binding",
    )
    source = replace_exact(
        source,
        "                cpu_millis: 100,\n"
        "                memory_bytes: 1024,\n"
        "                accelerator_millis: 0,",
        "                concurrent_turns: 100,\n"
        "                memory_mib: 1024,\n"
        "                tool_processes: 0,\n"
        "                turn_queue_slots: 0,",
        "authority grant fixture",
    )
    source = replace_exact(
        source,
        "                    cpu_millis: 1_000,\n"
        "                    memory_bytes: 1 << 20,\n"
        "                    accelerator_millis: 1_000,",
        "                    concurrent_turns: 1_000,\n"
        "                    memory_mib: 1 << 20,\n"
        "                    tool_processes: 1_000,\n"
        "                    turn_queue_slots: 4_096,",
        "authority host fixture",
    )
    source = replace_exact(
        source,
        "changed.resources.cpu_millis += 1;",
        "changed.resources.concurrent_turns += 1;",
        "authority mutation fixture",
    )
    source = source.replace(".unwrap_err()", '.expect_err("expected rejection")')
    source = source.replace(".unwrap()", '.expect("test setup or operation")')
    path.write_text(source)


def patch_lease_ledger() -> None:
    path = FLEET / "lease_ledger.rs"
    source = path.read_text()
    source = replace_exact(
        source,
        """            LeaseDisposition::Revoke => {
                let grant = self
                    .grants
                    .get_mut(allocation_id)
                    .ok_or(Error::AllocationNotFound)?;
                grant.revoked = true;
                grant.lease_generation = grant
                    .lease_generation
                    .checked_add(1)
                    .ok_or(Error::ArithmeticOverflow)?;
                Ok(receipt(grant, LeaseOutcome::Revoked))
            }
""",
        """            LeaseDisposition::Revoke => {
                let next_generation = current
                    .lease_generation
                    .checked_add(1)
                    .ok_or(Error::ArithmeticOverflow)?;
                let mut next = current.clone();
                next.revoked = true;
                next.lease_generation = next_generation;
                let result = receipt(&next, LeaseOutcome::Revoked);
                self.grants.insert(allocation_id.to_string(), next);
                Ok(result)
            }
""",
        "atomic revoke",
    )
    source = replace_exact(
        source,
        """            LeaseDisposition::Renew { expires_at_ms } => {
                let host = self
                    .hosts
                    .get(&current.host_id)
                    .ok_or(Error::HostNotFound)?;
                if now_ms >= host.valid_until_ms || host.generation != current.host_generation {
                    return Err(Error::StaleHost);
                }
                if expires_at_ms <= now_ms || expires_at_ms > host.valid_until_ms {
                    return Err(Error::InvalidTime);
                }
                if expires_at_ms == current.expires_at_ms {
                    return Ok(receipt(&current, LeaseOutcome::Unchanged));
                }
                let result = {
                    let grant = self
                        .grants
                        .get_mut(allocation_id)
                        .ok_or(Error::AllocationNotFound)?;
                    grant.expires_at_ms = expires_at_ms;
                    grant.lease_generation = grant
                        .lease_generation
                        .checked_add(1)
                        .ok_or(Error::ArithmeticOverflow)?;
                    receipt(grant, LeaseOutcome::Renewed)
                };
                // A release/holder observation for the predecessor lease fence
                // cannot be reused to settle the renewed lease.
                self.holder_observations.remove(allocation_id);
                Ok(result)
            }
""",
        """            LeaseDisposition::Renew { expires_at_ms } => {
                let host = self
                    .hosts
                    .get(&current.host_id)
                    .cloned()
                    .ok_or(Error::HostNotFound)?;
                if current.expires_at_ms <= now_ms {
                    return Err(Error::StaleLease);
                }
                if now_ms >= host.valid_until_ms || host.generation != current.host_generation {
                    return Err(Error::StaleHost);
                }
                if expires_at_ms <= now_ms || expires_at_ms > host.valid_until_ms {
                    return Err(Error::InvalidTime);
                }
                if expires_at_ms == current.expires_at_ms {
                    return Ok(receipt(&current, LeaseOutcome::Unchanged));
                }
                let reserved = self.reserved_resources_for_placement(&current.host_id, now_ms)?;
                if !reserved.fits(host.capacity) {
                    return Err(Error::CapacityExceeded);
                }
                let next_generation = current
                    .lease_generation
                    .checked_add(1)
                    .ok_or(Error::ArithmeticOverflow)?;
                let mut next = current.clone();
                next.expires_at_ms = expires_at_ms;
                next.lease_generation = next_generation;
                let result = receipt(&next, LeaseOutcome::Renewed);
                self.grants.insert(allocation_id.to_string(), next);
                // A release/holder observation for the predecessor lease fence
                // cannot be reused to settle the renewed lease.
                self.holder_observations.remove(allocation_id);
                Ok(result)
            }
""",
        "atomic live renewal",
    )
    path.write_text(source)


def append_lease_regressions() -> None:
    path = FLEET / "lease_ledger_tests.rs"
    source = path.read_text()
    marker = "fn expired_holder_still_reserves_capacity_until_release_is_observed()"
    if marker in source:
        return
    source += r'''

#[test]
fn expired_holder_still_reserves_capacity_until_release_is_observed() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    let mut first = grant("expired-holder", 1_000);
    first.expires_at_ms = 300;
    ledger.issue(200, first).expect("first grant");
    assert_eq!(
        ledger.issue(400, grant("replacement", 1_000)),
        Err(Error::CapacityExceeded)
    );
}

#[test]
fn revoked_holder_still_reserves_capacity_until_release_is_observed() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    ledger.issue(200, grant("revoked-holder", 1_000)).expect("grant");
    ledger
        .renew_or_revoke(
            250,
            "revoked-holder",
            1,
            3,
            &"1".repeat(64),
            LeaseDisposition::Revoke,
        )
        .expect("revoke");
    assert_eq!(
        ledger.issue(300, grant("replacement", 1_000)),
        Err(Error::CapacityExceeded)
    );
    let revoked = ledger.get("revoked-holder").expect("revoked grant").clone();
    ledger
        .reconcile_consumption(350, released(&revoked, 1, 350))
        .expect("release holder");
    ledger
        .issue(350, grant("replacement", 1_000))
        .expect("released capacity can be reused");
}

#[test]
fn expired_lease_cannot_be_renewed_after_replacement_admission_window() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    let mut expired = grant("expired", 1_000);
    expired.expires_at_ms = 300;
    ledger.issue(200, expired).expect("grant");
    let before = ledger.get("expired").expect("stored grant").clone();
    assert_eq!(
        ledger.renew_or_revoke(
            400,
            "expired",
            1,
            3,
            &"1".repeat(64),
            LeaseDisposition::Renew { expires_at_ms: 900 },
        ),
        Err(Error::StaleLease)
    );
    assert_eq!(ledger.get("expired"), Some(&before));
}

#[test]
fn failed_revoke_is_atomic_when_generation_overflows() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    let mut value = grant("overflow-revoke", 1);
    value.lease_generation = u64::MAX;
    ledger.issue(200, value).expect("grant");
    let before = ledger.get("overflow-revoke").expect("stored grant").clone();
    assert_eq!(
        ledger.renew_or_revoke(
            300,
            "overflow-revoke",
            u64::MAX,
            3,
            &"1".repeat(64),
            LeaseDisposition::Revoke,
        ),
        Err(Error::ArithmeticOverflow)
    );
    assert_eq!(ledger.get("overflow-revoke"), Some(&before));
}

#[test]
fn failed_renew_is_atomic_when_generation_overflows() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    let mut value = grant("overflow-renew", 1);
    value.lease_generation = u64::MAX;
    ledger.issue(200, value).expect("grant");
    let before = ledger.get("overflow-renew").expect("stored grant").clone();
    assert_eq!(
        ledger.renew_or_revoke(
            300,
            "overflow-renew",
            u64::MAX,
            3,
            &"1".repeat(64),
            LeaseDisposition::Renew { expires_at_ms: 900 },
        ),
        Err(Error::ArithmeticOverflow)
    );
    assert_eq!(ledger.get("overflow-renew"), Some(&before));
}
'''
    path.write_text(source)


def patch_lane_b_ci() -> None:
    path = ROOT / ".github/workflows/hepta-lane-b-truth.yml"
    source = path.read_text()
    source = source.replace(
        '      - "codex-rs/hepta-agentd/**"\n',
        '      - "codex-rs/hepta-fleet/**"\n'
        '      - "codex-rs/hepta-supervisor/**"\n'
        '      - "codex-rs/hepta-agentd/**"\n',
    )
    source = source.replace(
        '      - "docs/modules/**/IMPLEMENTATION_MAP.json"\n',
        '      - "docs/modules/runtime.fleet/**"\n'
        '      - "docs/modules/**/IMPLEMENTATION_MAP.json"\n',
    )
    source = replace_exact(
        source,
        "          cargo test -p codex-hepta-fleet --bin hepta-fleet-leased\n",
        "          cargo test --locked -p codex-hepta-fleet --lib\n"
        "          cargo clippy --locked -p codex-hepta-fleet --all-targets -- -D warnings\n",
        "Lane B exact-head Fleet commands",
    )
    source = replace_exact(
        source,
        "            cd codex-rs\n            cargo test -p codex-hepta-automation\n",
        "            cd codex-rs\n"
        "            cargo test --locked -p codex-hepta-fleet --lib\n"
        "            cargo test -p codex-hepta-automation\n",
        "Lane B merge Fleet command",
    )
    path.write_text(source)


def apply() -> None:
    restore_historical_core()
    patch_lib()
    patch_authority_port()
    patch_lease_ledger()
    append_lease_regressions()
    patch_lane_b_ci()
    run("git", "diff", "--check")


def rebind() -> None:
    source_sha = os.environ["SOURCE_SHA"]
    source_tree = os.environ["SOURCE_TREE"]
    path = ROOT / "docs/modules/runtime.fleet/IMPLEMENTATION_MAP.json"
    data = json.loads(path.read_text())
    data["sourceBase"] = {"commit": source_sha, "tree": source_tree}
    data["sourceMaturity"] = "durable_allocation_owner_source"
    data["stateOwnerDisposition"] = (
        "Implements a durable, generation-fenced allocation owner and holder reconciliation; "
        "named Supervisor product composition remains separately qualified."
    )
    data["repositoryControlledGaps"] = [
        "Compose the durable Fleet allocation owner into current Supervisor start, restart, upgrade, rollback and adoption paths with a named capacity observer."
    ]
    data["productCallerState"] = "not_composed"
    data["productionWriterState"] = "implemented_not_composed"
    data["productionImplementation"] = False
    boundary = data["claimBoundary"]
    boundary["repositoryControlledSourceBoundaryGapsClosed"] = False
    boundary["productExecutionComplete"] = False
    boundary["productionImplementation"] = False
    boundary["productExecutionProved"] = False
    boundary["activation"] = False
    boundary["release"] = False
    path.write_text(json.dumps(data, indent=2) + "\n")


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"apply", "rebind"}:
        raise SystemExit("usage: runtime_fleet_core_apply.py {apply|rebind}")
    if sys.argv[1] == "apply":
        apply()
    else:
        rebind()


if __name__ == "__main__":
    main()
