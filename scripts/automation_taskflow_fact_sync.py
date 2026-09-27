#!/usr/bin/env python3
"""One-shot source-of-truth sync for automation.taskflow schema-v1 provider compatibility."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def replace_once(relative: str, old: str, new: str) -> None:
    path = Path(relative)
    body = path.read_text(encoding="utf-8")
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"{relative}: expected one fact-sync anchor, found {count}")
    path.write_text(body.replace(old, new, 1), encoding="utf-8")


def remove_all(relative: str, needle: str, expected: int) -> None:
    path = Path(relative)
    body = path.read_text(encoding="utf-8")
    count = body.count(needle)
    if count != expected:
        raise SystemExit(f"{relative}: expected {expected} stale entries, found {count}")
    path.write_text(body.replace(needle, ""), encoding="utf-8")


def sync_source_truth() -> None:
    technical = "docs/modules/automation.taskflow/TECHNICAL.md"
    replace_once(
        technical,
        """The async `ProviderEffectTaskFlowDriver` remains a reusable bridge. Product
closure is established by the Agentd host's authorized-effect entrypoint, not by
pretending every reusable bridge has a direct caller. Deployment still requires
an independently provisioned authority, provider endpoint and trusted terminal
observer.
""",
        """The async `ProviderEffectTaskFlowDriver` remains a reusable bridge. Product
closure is established by the Agentd host's authorized-effect entrypoint, not by
pretending every reusable bridge has a direct caller. Deployment still requires
an independently provisioned authority, provider endpoint and trusted terminal
observer.

Agentd effect-host schema v1 keeps its historical provider identity exactly as
`ProviderEffectKey::for_operation(provider_scope, run_id, step_id)` even though
physical dispatch delegates to the shared driver. Existing pending effects thus
query the same provider key after a schema-v19 binary upgrade. Under this
compatibility profile, provider `NotFound` and transport-unknown remain
unresolved quarantine and are never promoted to absence proof; an invalid ACK or
same-key payload conflict remains fail-closed. A different key profile requires
a new host schema with the selected profile and provider key durably recorded
before provider contact.
""",
    )

    runbook = "docs/modules/automation.taskflow/MIGRATION_V19_RUNBOOK.md"
    replace_once(
        runbook,
        """Any error keeps automation unavailable. Do not edit `_sqlx_migrations` by hand.

## 4. Backup restore
""",
        """Any error keeps automation unavailable. Do not edit `_sqlx_migrations` by hand.

### 3.1 Provider-effect identity compatibility

Agentd effect-host schema v1 predates the reusable driver's logical-effect key
profile. Its provider-visible identity remains
`ProviderEffectKey::for_operation(provider_scope, run_id, step_id)` for both new
and already-pending effects. A v19 upgrade must query that same key. `NotFound`
and transport-unknown remain unresolved and cannot prove absence; invalid ACKs
and same-key payload conflicts retain the pre-existing fail-closed behavior. A
future key profile requires a new host schema plus a durable profile/key field
written before provider contact.

## 4. Backup restore
""",
    )

    dossier = "qualification/module-execution-dossiers/detail/automation.taskflow.md"
    replace_once(
        dossier,
        """The reusable async `ProviderEffectTaskFlowDriver` is not falsely promoted as the
only possible product caller. Independent issuer/provider provisioning and
selected-host acceptance remain required.
""",
        """The reusable async `ProviderEffectTaskFlowDriver` is not falsely promoted as the
only possible product caller. Agentd schema-v1 composition delegates physical
dispatch to that bridge while preserving the pre-existing
`for_operation(provider_scope, run_id, step_id)` provider key. `NotFound` and
transport-unknown remain unresolved; invalid ACKs and same-key payload conflicts
remain fail-closed. An upgrade therefore cannot query a different key and
manufacture safe retry. Independent issuer/provider provisioning and
selected-host acceptance remain required.
""",
    )

    release = "docs/modules/automation.taskflow/RELEASE_QUALIFICATION.md"
    replace_once(
        release,
        "- [x] Agentd external-effect host wired through `ProviderEffectTaskFlowDriver`, final-use authority and the attested HTTP provider adapter\n",
        "- [x] Agentd external-effect host wired through `ProviderEffectTaskFlowDriver`, final-use authority and the attested HTTP provider adapter\n- [x] schema-v1 provider-key continuity, `NotFound` quarantine and conflict fail-closed regression\n",
    )

    schema_path = Path("docs/modules/automation.taskflow/SCHEMA_CONTRACT.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema.setdefault("productComposition", {})[
        "legacyProviderKeyCompatibility"
    ] = True
    schema_path.write_text(
        json.dumps(schema, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )

    verifier = "scripts/automation_taskflow_contract.py"
    replace_once(
        verifier,
        '    need(contract.get("storeSchemaVersion") == 19, "contract store schema must be 19")\n',
        """    need(contract.get("storeSchemaVersion") == 19, "contract store schema must be 19")
    need(
        contract.get("productComposition", {}).get(
            "legacyProviderKeyCompatibility"
        )
        is True,
        "schema-v1 provider-key compatibility must be explicit",
    )
""",
    )
    replace_once(
        verifier,
        """        "AgentdAutomationEffectHost",
        "ProviderEffectTaskFlowDriver::new",
        "execute_authorized_taskflow_effect_async",
        "FinalUseAuthority::open_state_dir",
        "HttpProviderEffectAdapter",
""",
        """        "AgentdAutomationEffectHost",
        "ProviderEffectTaskFlowDriver::new",
        "AgentdProviderEffectTaskFlowDriver",
        "ProviderEffectKey::for_operation",
        "ProviderEffectLookup::NotFound",
        "provider reports a same-key payload conflict",
        "execute_authorized_taskflow_effect_async",
        "FinalUseAuthority::open_state_dir",
        "HttpProviderEffectAdapter",
""",
    )
    replace_once(
        verifier,
        """        "crossHostRecoveryContractComplete",
        "selectedHostQualificationPathComplete",
""",
        """        "crossHostRecoveryContractComplete",
        "legacyProviderKeyCompatibilityComplete",
        "selectedHostQualificationPathComplete",
""",
    )
    replace_once(
        verifier,
        """        "crossHostOwnerBindingVerified": True,
        "selectedHostVerifierPresent": True,
""",
        """        "crossHostOwnerBindingVerified": True,
        "legacyProviderKeyCompatibilityVerified": True,
        "selectedHostVerifierPresent": True,
""",
    )

    verifier_test = "scripts/test_automation_taskflow_contract.py"
    replace_once(
        verifier_test,
        """        self.assertTrue(result["crossHostOwnerBindingVerified"])
        self.assertTrue(result["externalReleaseGatesRemainFalse"])
""",
        """        self.assertTrue(result["crossHostOwnerBindingVerified"])
        self.assertTrue(result["legacyProviderKeyCompatibilityVerified"])
        self.assertTrue(result["externalReleaseGatesRemainFalse"])
""",
    )

    focused = ".github/workflows/automation-taskflow-focused.yml"
    remove_all(
        focused,
        "      - .github/workflows/automation-taskflow-format-bootstrap.yml\n",
        2,
    )
    remove_all(
        focused,
        "      - .github/workflows/automation-taskflow-map-rebind-final.yml\n",
        2,
    )


def sync_map_claims() -> None:
    path = Path("docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    claims = data.setdefault("claimBoundary", {})
    claims.update(
        {
            "selectedHostQualificationPathComplete": True,
            "independentAcceptanceVerificationPathComplete": True,
            "boundedRecoveryFairnessComplete": True,
            "canonicalCircuitIngressComplete": True,
            "runtimeProfileReceiptBindingComplete": True,
            "crossHostOwnerBindingComplete": True,
            "legacyProviderKeyCompatibilityComplete": True,
        }
    )
    for key in (
        "deploymentQualificationComplete",
        "independentAcceptance",
        "activation",
        "promotion",
        "release",
    ):
        claims[key] = False

    operations = {
        row.get("designOperation"): row
        for row in data.get("operations", [])
        if isinstance(row, dict)
    }
    execute = operations.get("execute_step")
    if execute is None:
        raise SystemExit("implementation map is missing execute_step")
    execute["sourceSemantics"] = (
        "Verifies canonical final-use subject/destination/scope/payload binding, appends "
        "provider-attempt evidence before contact, and reconciles the Agentd schema-v1 "
        "provider identity for_operation(provider_scope,run,step). NotFound and transport "
        "unknown stay quarantined, while invalid acknowledgements and same-key payload "
        "conflicts fail closed. Neural Circuit execution recomputes canonical event "
        "identity, records bounded choices and organ/wait observations, binds the exact "
        "runtime-profile digest into terminal and boundary receipts, and returns Effect "
        "nodes to the same authorized seam."
    )
    compatibility = {
        "path": "codex-rs/hepta-agentd/src/automation_effect_host.rs",
        "kind": "schema_v1_provider_key_not_found_and_conflict_compatibility",
        "command": "cargo test -p codex-hepta-agentd --lib automation_effect_host",
    }
    tests = execute.setdefault("tests", [])
    if compatibility not in tests:
        tests.append(compatibility)

    observed = set(data.get("observedSourcePaths", []))
    observed.update(
        {
            ".github/workflows/automation-taskflow-focused.yml",
            ".github/workflows/automation-taskflow-selected-host.yml",
            ".github/workflows/automation-taskflow-independent-acceptance.yml",
            "scripts/automation_taskflow_contract.py",
            "scripts/test_automation_taskflow_contract.py",
            "scripts/verify_automation_taskflow_acceptance.py",
            "scripts/test_verify_automation_taskflow_acceptance.py",
            "docs/modules/automation.taskflow/INDEPENDENT_ACCEPTANCE.md",
            "docs/modules/automation.taskflow/RELEASE_QUALIFICATION.md",
            "docs/modules/automation.taskflow/SLO.md",
        }
    )
    data["observedSourcePaths"] = sorted(observed)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("source", "map"))
    args = parser.parse_args()
    if args.phase == "source":
        sync_source_truth()
    else:
        sync_map_claims()


if __name__ == "__main__":
    main()
