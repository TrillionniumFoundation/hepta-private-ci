#!/usr/bin/env python3
"""One-shot repair for Agentd schema-v1 provider-effect identity compatibility."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def replace_once(relative: str, old: str, new: str) -> None:
    path = Path(relative)
    body = path.read_text(encoding="utf-8")
    count = body.count(old)
    if count != 1:
        raise SystemExit(
            f"{relative}: expected exactly one compatibility anchor, found {count}"
        )
    path.write_text(body.replace(old, new, 1), encoding="utf-8")


def remove_all(relative: str, needle: str, expected: int) -> None:
    path = Path(relative)
    body = path.read_text(encoding="utf-8")
    count = body.count(needle)
    if count != expected:
        raise SystemExit(
            f"{relative}: expected {expected} obsolete markers, found {count}"
        )
    path.write_text(body.replace(needle, ""), encoding="utf-8")


def patch_source() -> None:
    host = "codex-rs/hepta-agentd/src/automation_effect_host.rs"
    replace_once(
        host,
        """use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AuthorizedEffectPending;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AuthorizedEffectRecoveryResult;
use codex_hepta_automation::AuthorizedProviderEffectLookup;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::ProviderEffectTaskFlowDriver;
""",
        """use codex_hepta_automation::AsyncAuthorizedEffectDriver;
use codex_hepta_automation::AuthorizedEffectDriverError;
use codex_hepta_automation::AuthorizedEffectFuture;
use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::AuthorizedEffectOutcome;
use codex_hepta_automation::AuthorizedEffectPending;
use codex_hepta_automation::AuthorizedEffectProviderReceipt;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AuthorizedEffectRecoveryResult;
use codex_hepta_automation::AuthorizedProviderEffectLookup;
use codex_hepta_automation::AuthorizedProviderEffectRequest;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::ProviderEffectTaskFlowDriver;
""",
    )
    replace_once(
        host,
        """use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
""",
        """use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::ProviderEffectAck;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
""",
    )
    replace_once(
        host,
        """        let mut driver =
            ProviderEffectTaskFlowDriver::new(self.destination_id.clone(), self.adapter.clone())
                .map_err(|error| {
                    AgentdError::Protocol(format!(
                        \"configure automation provider-effect bridge: {error}\"
                    ))
                })?;
""",
        """        let mut driver = AgentdProviderEffectTaskFlowDriver::new(
            self.destination_id.clone(),
            self.provider_scope.clone(),
            self.adapter.clone(),
        )
        .map_err(|error| {
            AgentdError::Protocol(format!(
                \"configure automation provider-effect bridge: {error}\"
            ))
        })?;
""",
    )
    replace_once(
        host,
        """        let driver =
            ProviderEffectTaskFlowDriver::new(self.destination_id.clone(), self.adapter.clone())
                .map_err(|error| {
                    AgentdError::Protocol(format!(
                        \"configure automation provider-effect lookup bridge: {error}\"
                    ))
                })?;
""",
        """        let driver = AgentdProviderEffectTaskFlowDriver::new(
            self.destination_id.clone(),
            self.provider_scope.clone(),
            self.adapter.clone(),
        )
        .map_err(|error| {
            AgentdError::Protocol(format!(
                \"configure automation provider-effect lookup bridge: {error}\"
            ))
        })?;
""",
    )

    bridge = r'''
/// Agentd host schema v1 predates the generic TaskFlow provider-key profile.
/// Keep its provider-visible identity byte-for-byte stable while delegating the
/// physical dispatch to the shared `ProviderEffectTaskFlowDriver`. Changing
/// this key on upgrade could turn an already-executed legacy effect into a
/// false `NotFound` under a different key and permit a duplicate send.
struct AgentdProviderEffectTaskFlowDriver {
    provider_scope: String,
    inner: ProviderEffectTaskFlowDriver<HttpProviderEffectAdapter>,
}

impl AgentdProviderEffectTaskFlowDriver {
    fn new(
        destination_id: String,
        provider_scope: String,
        adapter: HttpProviderEffectAdapter,
    ) -> Result<Self, AuthorizedEffectDriverError> {
        Ok(Self {
            provider_scope,
            inner: ProviderEffectTaskFlowDriver::new(destination_id, adapter)?,
        })
    }

    async fn lookup(
        &self,
        pending: &AuthorizedEffectPending,
    ) -> AuthorizedProviderEffectLookup {
        let Ok(provider_intent) = agentd_schema_v1_provider_intent(
            &self.provider_scope,
            &pending.run_id,
            &pending.step_id,
            &pending.payload_digest,
        ) else {
            return AuthorizedProviderEffectLookup::Unresolved;
        };
        let lookup = self
            .inner
            .adapter()
            .lookup_for_intent(&provider_intent)
            .await;
        agentd_schema_v1_provider_lookup(&provider_intent, lookup)
    }
}

impl AsyncAuthorizedEffectDriver for AgentdProviderEffectTaskFlowDriver {
    fn dispatch<'a>(
        &'a mut self,
        mut request: AuthorizedProviderEffectRequest<'a>,
    ) -> AuthorizedEffectFuture<'a> {
        let provider_intent = match agentd_schema_v1_provider_intent(
            &self.provider_scope,
            &request.intent.run_id,
            &request.intent.step_id,
            &request.intent.payload_digest,
        ) {
            Ok(provider_intent) => provider_intent,
            Err(error) => return Box::pin(async move { Err(error) }),
        };
        request.provider_intent = provider_intent;
        self.inner.dispatch(request)
    }
}

fn agentd_schema_v1_provider_intent(
    provider_scope: &str,
    run_id: &str,
    step_id: &str,
    payload_digest: &Sha256Digest,
) -> Result<ProviderEffectIntent, AuthorizedEffectDriverError> {
    let key = ProviderEffectKey::for_operation(provider_scope, run_id, step_id)
        .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)?;
    Ok(ProviderEffectIntent::new(key, payload_digest.clone()))
}

fn agentd_schema_v1_provider_lookup(
    provider_intent: &ProviderEffectIntent,
    lookup: ProviderEffectLookup,
) -> AuthorizedProviderEffectLookup {
    match lookup {
        ProviderEffectLookup::Ack(ack) if ack.validate_for(provider_intent).is_ok() => {
            agentd_schema_v1_terminal_receipt(&ack).map_or(
                AuthorizedProviderEffectLookup::Unresolved,
                AuthorizedProviderEffectLookup::Observed,
            )
        }
        ProviderEffectLookup::Ack(_)
        | ProviderEffectLookup::NotFound
        | ProviderEffectLookup::Conflict { .. }
        | ProviderEffectLookup::Unknown => AuthorizedProviderEffectLookup::Unresolved,
    }
}

fn agentd_schema_v1_terminal_receipt(
    ack: &ProviderEffectAck,
) -> Option<AuthorizedEffectProviderReceipt> {
    let outcome = match ack.status {
        ProviderEffectAckStatus::Accepted => return None,
        ProviderEffectAckStatus::Completed => AuthorizedEffectOutcome::Succeeded,
        ProviderEffectAckStatus::Rejected => AuthorizedEffectOutcome::Failed,
    };
    let mut bytes = b"hepta.agentd.provider-effect.lookup.v1\0".to_vec();
    if let Ok(encoded) = serde_json::to_vec(ack) {
        bytes.extend_from_slice(&encoded);
    } else {
        bytes.extend_from_slice(b"serialization-unavailable");
    }
    Some(AuthorizedEffectProviderReceipt {
        outcome,
        receipt_digest: Sha256Digest::for_bytes(&bytes),
    })
}
'''
    replace_once(host, "}\n\nfn read_host_file", "}\n" + bridge + "\nfn read_host_file")

    replace_once(
        host,
        """        let logical_effect_id = format!(\"taskflow:{}:{}\", intent.run_id, intent.step_id);
        let provider_key =
            ProviderEffectKey::for_logical_effect(&intent.destination_id, &logical_effect_id)
                .expect(\"provider key\");
""",
        """        let provider_key = ProviderEffectKey::for_operation(
            \"provider/fixture-v1\",
            &intent.run_id,
            &intent.step_id,
        )
        .expect(\"provider key\");
""",
    )
    replace_once(
        host,
        "async fn host_dispatches_exact_wire_payload_once()",
        "async fn host_preserves_schema_v1_provider_key_and_dispatches_exact_wire_payload_once()",
    )
    compatibility_test = r'''
    #[test]
    fn schema_v1_provider_key_and_not_found_semantics_survive_shared_driver_composition() {
        let payload_digest = Sha256Digest::for_bytes(b"compatibility-payload");
        let provider_intent = agentd_schema_v1_provider_intent(
            "provider/fixture-v1",
            "legacy-run",
            "legacy-step",
            &payload_digest,
        )
        .expect("schema-v1 provider intent");
        let expected = ProviderEffectKey::for_operation(
            "provider/fixture-v1",
            "legacy-run",
            "legacy-step",
        )
        .expect("legacy provider key");
        let replacement = ProviderEffectKey::for_logical_effect(
            "provider:fixture",
            "taskflow:legacy-run:legacy-step",
        )
        .expect("new provider key profile");
        assert_eq!(provider_intent.key, expected);
        assert_ne!(provider_intent.key, replacement);
        assert_eq!(
            agentd_schema_v1_provider_lookup(&provider_intent, ProviderEffectLookup::NotFound),
            AuthorizedProviderEffectLookup::Unresolved
        );
    }

'''
    replace_once(
        host,
        "    #[tokio::test(flavor = \"multi_thread\", worker_threads = 2)]\n    async fn host_preserves_schema_v1_provider_key_and_dispatches_exact_wire_payload_once()",
        compatibility_test
        + "    #[tokio::test(flavor = \"multi_thread\", worker_threads = 2)]\n    async fn host_preserves_schema_v1_provider_key_and_dispatches_exact_wire_payload_once()",
    )

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
physical dispatch now delegates to the shared driver. Existing pending effects
therefore query the same provider key after a schema-v19 binary upgrade. For this
compatibility profile, provider `NotFound`, conflict and transport-unknown remain
unresolved quarantine; they are not promoted to absence proof. A different key
profile requires a new host schema that durably records the selected profile and
provider key before contact.
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
and already-pending effects. A v19 upgrade must query that same key; `NotFound`,
conflict or transport-unknown remains unresolved and cannot prove absence. A
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
`for_operation(provider_scope, run_id, step_id)` provider key. Status `NotFound`
under this compatibility profile remains unresolved, so an upgrade cannot query
a different key and manufacture safe retry. Independent issuer/provider
provisioning and selected-host acceptance remain required.
""",
    )

    release = "docs/modules/automation.taskflow/RELEASE_QUALIFICATION.md"
    replace_once(
        release,
        "- [x] Agentd external-effect host wired through `ProviderEffectTaskFlowDriver`, final-use authority and the attested HTTP provider adapter\n",
        "- [x] Agentd external-effect host wired through `ProviderEffectTaskFlowDriver`, final-use authority and the attested HTTP provider adapter\n- [x] schema-v1 provider-key continuity and `NotFound` quarantine regression\n",
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
        "    need(contract.get(\"storeSchemaVersion\") == 19, \"contract store schema must be 19\")\n",
        """    need(contract.get(\"storeSchemaVersion\") == 19, \"contract store schema must be 19\")
    need(
        contract.get(\"productComposition\", {}).get(
            \"legacyProviderKeyCompatibility\"
        )
        is True,
        \"schema-v1 provider-key compatibility must be explicit\",
    )
""",
    )
    replace_once(
        verifier,
        """        \"ProviderEffectTaskFlowDriver::new\",
        \"execute_authorized_taskflow_effect_async\",
        \"FinalUseAuthority::open_state_dir\",
        \"HttpProviderEffectAdapter\",
""",
        """        \"ProviderEffectTaskFlowDriver::new\",
        \"AgentdProviderEffectTaskFlowDriver\",
        \"ProviderEffectKey::for_operation\",
        \"ProviderEffectLookup::NotFound\",
        \"execute_authorized_taskflow_effect_async\",
        \"FinalUseAuthority::open_state_dir\",
        \"HttpProviderEffectAdapter\",
""",
    )
    replace_once(
        verifier,
        """        \"crossHostOwnerBindingVerified\": True,
        \"selectedHostVerifierPresent\": True,
""",
        """        \"crossHostOwnerBindingVerified\": True,
        \"legacyProviderKeyCompatibilityVerified\": True,
        \"selectedHostVerifierPresent\": True,
""",
    )
    replace_once(
        verifier,
        """        \"crossHostRecoveryContractComplete\",
        \"selectedHostQualificationPathComplete\",
""",
        """        \"crossHostRecoveryContractComplete\",
        \"legacyProviderKeyCompatibilityComplete\",
        \"selectedHostQualificationPathComplete\",
""",
    )

    verifier_test = "scripts/test_automation_taskflow_contract.py"
    replace_once(
        verifier_test,
        """        self.assertTrue(result[\"crossHostOwnerBindingVerified\"])
        self.assertTrue(result[\"externalReleaseGatesRemainFalse\"])
""",
        """        self.assertTrue(result[\"crossHostOwnerBindingVerified\"])
        self.assertTrue(result[\"legacyProviderKeyCompatibilityVerified\"])
        self.assertTrue(result[\"externalReleaseGatesRemainFalse\"])
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


def patch_map() -> None:
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
    materialize = operations.get("materialize_due")
    if materialize is not None:
        materialize["sourceSemantics"] = (
            "Runs a bounded sequential admission batch over the unchanged V1 durable tick "
            "operation, samples a fresh clock per occurrence, persists TaskFlow intent before "
            "contact, and stops on unknown outcome. Recovery snapshots distinct unknown and "
            "terminal frontiers, reserves terminal progress under sustained unknown pressure, "
            "and blocks new admission while recovery transport is retrying."
        )
        fairness = {
            "path": "codex-rs/hepta-agentd/src/automation_recovery.rs",
            "kind": "distinct_frontier_unknown_priority_and_terminal_liveness",
            "command": "cargo test -p codex-hepta-agentd --lib",
        }
        tests = materialize.setdefault("tests", [])
        if fairness not in tests:
            tests.append(fairness)

    claim = operations.get("claim_occurrence")
    if claim is not None:
        claim["sourceSemantics"] = (
            "Binds one due lease to a deterministic durable occurrence and generation/timer "
            "fence; safe reclaim preserves identity, unresolved provider contact remains "
            "quarantined, and cross-host target admission requires checkpoint and external-fence "
            "receipts, schema 19, exactly the next writer epoch, and the same owner Agent read "
            "from the copied target store."
        )

    execute = operations.get("execute_step")
    if execute is not None:
        execute["sourceSemantics"] = (
            "Verifies canonical final-use subject/destination/scope/payload binding, appends "
            "provider-attempt evidence before contact, and reconciles by the stable schema-v1 "
            "for_operation(provider_scope,run,step) identity without blind redispatch or "
            "promoting NotFound to absence. Neural Circuit execution recomputes canonical event "
            "identity, records bounded choices and organ/wait observations, binds the exact "
            "runtime-profile digest into terminal and boundary receipts, and returns Effect "
            "nodes to the same authorized seam."
        )
        compatibility = {
            "path": "codex-rs/hepta-agentd/src/automation_effect_host.rs",
            "kind": "schema_v1_provider_key_and_not_found_compatibility",
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
        patch_source()
    else:
        patch_map()


if __name__ == "__main__":
    main()
