#!/usr/bin/env python3
"""Finalize runtime.codex source convergence and documentation mappings."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, value: str) -> None:
    (ROOT / path).write_text(value, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one anchor, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def append_once(path: str, marker: str, addition: str) -> None:
    text = read(path)
    if marker in text:
        return
    write(path, text.rstrip() + "\n" + addition)


def run_phase3() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/runtime-codex-converge-phase3.py")],
        cwd=ROOT,
        check=True,
    )


def patch_move_safe_typestate() -> None:
    path = "codex-rs/hepta-infer-worker-host/src/native_app_server.rs"
    replace_once(
        path,
        '''        intelligence: Option<&NativeIntelligenceRunBinding>,
        owner_dispatch_revision: Option<u64>,
        reason: String,
''',
        '''        intelligence: Option<&NativeIntelligenceRunBinding>,
        reason: String,
''',
    )
    replace_once(
        path,
        '''        let owner_dispatch_revision = owner_dispatch_revision
            .ok_or("bound pre-effect abort omitted the Agentd dispatch revision")?;
''',
        '''        let owner_dispatch_revision = self
            .owner_dispatch_revision
            .ok_or("bound pre-effect abort omitted the Agentd dispatch revision")?;
''',
    )
    text = read(path)
    text = text.replace(
        '''                        intelligence,
                        prepared_effect.owner_dispatch_revision,
                        reason.clone(),
''',
        '''                        intelligence,
                        reason.clone(),
''',
    )
    text = text.replace(
        '''                            intelligence,
                            prepared_effect.owner_dispatch_revision,
                            reason,
''',
        '''                            intelligence,
                            reason,
''',
    )
    text = text.replace(
        '''                        intelligence,
                        prepared_effect.owner_dispatch_revision,
                        "cognitive final-use revalidation returned a mismatched receipt".to_string(),
''',
        '''                        intelligence,
                        "cognitive final-use revalidation returned a mismatched receipt".to_string(),
''',
    )
    text = text.replace(
        '''                    intelligence,
                    prepared_effect.owner_dispatch_revision,
                    "cancelled before model dispatch".to_string(),
''',
        '''                    intelligence,
                    "cancelled before model dispatch".to_string(),
''',
    )
    text = text.replace(
        '''                    intelligence,
                    prepared_effect.owner_dispatch_revision,
                    reason.clone(),
''',
        '''                    intelligence,
                    reason.clone(),
''',
    )
    # The mismatched owner receipt is already a committed bound dispatch; bind
    # its revision before consuming PreparedEffectEntry in the abort branch.
    text = text.replace(
        '''                let reason =
                    "Agentd did not commit this exact bound intelligence dispatch".to_string();
                prepared_effect
                    .abort(
                        control,
                        &owner,
                        intelligence,
                        Some(dispatched.revision),
                        reason.clone(),
                    )
''',
        '''                let reason =
                    "Agentd did not commit this exact bound intelligence dispatch".to_string();
                prepared_effect.owner_dispatch_revision = Some(dispatched.revision);
                prepared_effect
                    .abort(
                        control,
                        &owner,
                        intelligence,
                        reason.clone(),
                    )
''',
    )
    if "prepared_effect.owner_dispatch_revision," in text:
        raise RuntimeError("native_app_server still reads a field after moving its typestate")
    write(path, text)


def patch_security_and_clock_warnings() -> None:
    path = "codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs"
    replace_once(
        path,
        '''        let actual = Sha256::digest(std::fs::read(proc_root.join("cgroup"))?);
        if actual.as_slice() != expected_digest {
''',
        '''        let actual: [u8; 32] =
            Sha256::digest(std::fs::read(proc_root.join("cgroup"))?).into();
        if actual != expected_digest {
''',
    )
    app = "codex-rs/hepta-infer-worker-host/src/native_app_server.rs"
    replace_once(
        app,
        '''    wall_anchor_ms: u64,
    instant_anchor: Instant,
    wall_deadline_ms: u64,
    instant_deadline: Instant,
''',
        '''    wall_anchor_ms: u64,
    instant_anchor: Instant,
    instant_deadline: Instant,
''',
    )
    replace_once(
        app,
        '''            wall_anchor_ms,
            instant_anchor,
            wall_deadline_ms,
            instant_deadline,
''',
        '''            wall_anchor_ms,
            instant_anchor,
            instant_deadline,
''',
    )


def patch_adapter_digest_tests() -> None:
    path = "codex-rs/hepta-codex-adapter/src/lib_tests.rs"
    append_once(
        path,
        "fn request_digest_is_length_framed_and_field_sensitive()",
        r'''

#[test]
fn request_digest_is_length_framed_and_field_sensitive() {
    let base = product_intent();
    let base_digest = request_digest(&base);
    let mut variants = Vec::new();

    let mut operation = base.clone();
    operation.operation_id = id("operation:test-2");
    variants.push(operation);

    let mut thread = base.clone();
    thread.thread_id = id("thread:test-2");
    variants.push(thread);

    let mut deadline = base.clone();
    deadline.deadline_ms += 1;
    variants.push(deadline);

    let mut session = base.clone();
    session
        .app_server_binding
        .as_mut()
        .expect("product binding")
        .session_id = id("session:test-2");
    variants.push(session);

    let mut connection = base.clone();
    connection
        .app_server_binding
        .as_mut()
        .expect("product binding")
        .connection_id += 1;
    variants.push(connection);

    let mut seen = std::collections::BTreeSet::new();
    seen.insert(base_digest.to_string());
    for variant in variants {
        let digest = request_digest(&variant).to_string();
        assert!(seen.insert(digest), "distinct bound field collided");
    }
}
''',
    )


def patch_docs() -> None:
    append_once(
        "docs/modules/runtime.codex/TECHNICAL.md",
        "## 17. Cross-owner pre-effect abort and exact qualification",
        r'''

## 17. Cross-owner pre-effect abort and exact qualification

The composed native caller uses a two-owner abort saga for a final-use failure after both sides have recorded dispatch but before `VerifiedUseToken::enter()`:

1. the local native journal creates a random, live-only abort nonce and sends only its domain-separated commitment with the exact dispatch binding to Agentd;
2. Agentd atomically records `Dispatched`, the binding and commitment;
3. a pre-effect failure first commits local `AbortPending`, including the reason-bound nonce opening;
4. Agentd validates the opening and transitions to nonterminal `AbortedBeforeEffect`;
5. only after that owner acknowledgement does the local journal confirm and release capacity.

`AbortPending` recovery is ordered before generic App Server reconciliation and cannot call `thread/read`, consume final-use authority or send `turn/start`. A legacy unbound dispatch cannot use the cross-owner abort transition. `AbortedBeforeEffect` is closed for owner capacity but never sets provider `terminal_observed`.

The physical App Server call accepts a private `EnteredEffect` typestate produced only after the exact final-use token is consumed. The pre-effect token is destroyed by that conversion, so the abort path is unavailable after effect entry.

Runtime deadlines use a monotonic budget anchored to the absolute wall-clock deadline. A wall clock that falls behind the monotonic projection by more than the bounded tolerance fails closed. The final-use issuer may additionally pin Linux peer executable digest, boot ID, cgroup digest and process start time; UID and signature checks remain mandatory.

Repository qualification is split into exact-head and deterministic synthetic-merge jobs. Each retains command outcomes and hashes in a canonical JSON receipt with GitHub provenance attestation. The receipt keeps target-host identity, production key custody, trusted time/revocation distribution, real-provider execution, canary, rollback, independent acceptance, activation, promotion and release false until external evidence exists.

See `STATE_MACHINE.md`, `FAULT_INJECTION_MATRIX.json`, `QUARANTINE_AND_RELEASE.md`, `OPERATIONS.md` and `PRODUCTION_QUALIFICATION.md` for the closed-world state, crash and operational contracts.
''',
    )
    fault_path = "docs/modules/runtime.codex/FAULT_MATRIX.md"
    text = read(fault_path)
    marker = "## Cross-owner pre-effect abort\n"
    if marker not in text:
        section = r'''
## Cross-owner pre-effect abort

| Fault / observation | Required result | Retry posture | Durable behavior |
| --- | --- | --- | --- |
| Bound Agentd dispatch ACK is lost | query the same run and require exact request binding plus nonce commitment | no second physical send permit from an unbound/idempotent ACK | local state remains dispatching until exact owner status is known |
| Final-use check fails after exact owner dispatch | local `AbortPending`, then Agentd `AbortedBeforeEffect`, then local release | exact reason-bound proof replay only | capacity remains owned until both journals converge |
| Process dies with local `AbortPending` | abort-only startup reconciliation | never `thread/read` and never `turn/start` | replay stored nonce opening against the exact owner run |
| Agentd abort ACK is lost | status query or identical proof replay | idempotent only for identical binding, nonce, proof and reason | mismatches quarantine as conflicts |
| Same run is marked by a competing worker with a different commitment | hard conflict | none | original state remains unchanged |
| Issuer socket path changes during connect | fail closed | reconnect only after full identity validation | no grant claim and no external effect |
| Issuer UID matches but configured executable/boot/cgroup/start identity differs | fail closed | none until target-host identity is corrected | no grant claim |
| Wall clock rolls backward beyond monotonic tolerance | fail closed before effect entry | new operation only after trusted-time recovery | original dispatch follows exact abort or quarantine semantics |

The complete closed-world boundary inventory is `FAULT_INJECTION_MATRIX.json`. Repository tests are source evidence; target-host kill and real-provider cases remain externally required.

'''
        anchor = "## Correlation contract\n"
        if anchor not in text:
            raise RuntimeError("FAULT_MATRIX.md correlation anchor missing")
        write(fault_path, text.replace(anchor, section + anchor, 1))

    append_once(
        "qualification/module-execution-dossiers/detail/runtime.codex.md",
        "## 9. Convergence implementation addendum",
        r'''

## 9. Convergence implementation addendum

The current convergence candidate adds an exact cross-owner pre-effect abort protocol, `AbortPending` restart reconciliation, typed effect entry, bounded thread cleanup accounting, optional Linux issuer process pins, monotonic runtime deadlines, a machine-readable crash matrix, exact-head/synthetic-merge qualification and provenance-attested receipts.

These are repository-controlled implementation claims only. `productionImplementation`, target-host qualification, real-provider evidence, independent acceptance, activation and release remain false until the corresponding external gates in `PRODUCTION_QUALIFICATION.md` pass for the exact candidate.
''',
    )


def patch_implementation_map() -> None:
    path = ROOT / "docs/modules/runtime.codex/IMPLEMENTATION_MAP.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["preEffectAbortProtocol"] = {
        "version": 1,
        "localStates": ["dispatching", "abort_pending", "released"],
        "ownerState": "aborted_before_effect",
        "dispatchBinding": "codex request digest",
        "proof": "domain-separated random nonce commitment and reason-bound opening",
        "terminalObserved": False,
        "capacityRelease": "after exact Agentd abort acknowledgement",
        "restart": "abort-only reconciliation before App Server history lookup",
    }
    value["runtimeClock"] = {
        "deadline": "absolute wall deadline plus monotonic execution budget",
        "wallRollback": "fail_closed_beyond_tolerance",
        "trustedTimeStillExternal": True,
    }
    value["issuerProcessIdentity"] = {
        "mandatory": ["signature", "socket permissions", "peer uid"],
        "optionalLinuxPins": [
            "executable sha256",
            "boot id",
            "cgroup sha256",
            "process start ticks",
        ],
        "targetHostQualificationRequired": True,
    }
    value["qualificationReceipts"] = {
        "exactHead": ".github/workflows/runtime-codex-qualification.yml",
        "syntheticMerge": ".github/workflows/runtime-codex-qualification.yml",
        "faultMatrix": "docs/modules/runtime.codex/FAULT_INJECTION_MATRIX.json",
        "canonicalReceipt": "hepta.runtime-codex.qualification-receipt.v1",
        "provenanceAttestation": "GitHub artifact attestation",
        "externalGatesRemainFalse": True,
    }
    gaps = value.setdefault("repositoryControlledGaps", [])
    new_gap = (
        "the convergence candidate must obtain current exact-head and deterministic "
        "synthetic-merge receipts after all source migrations are committed"
    )
    if new_gap not in gaps:
        gaps.append(new_gap)
    claim = value.setdefault("claimBoundary", {})
    claim["repositoryControlledMappingGapsClosed"] = True
    claim["repositoryControlledSourceBoundaryGapsClosed"] = False
    claim["productExecutionComplete"] = False
    claim["deploymentQualificationComplete"] = False
    claim["independentAcceptanceComplete"] = False
    claim["productionImplementation"] = False
    claim["activation"] = False
    claim["release"] = False
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    run_phase3()
    patch_move_safe_typestate()
    patch_security_and_clock_warnings()
    patch_adapter_digest_tests()
    patch_docs()
    patch_implementation_map()


if __name__ == "__main__":
    main()
