#!/usr/bin/env python3
"""Close intelligence.control authority rollback and traceability on one exact tree.

This deterministic finalizer runs after the existing owner/product finalizer. It
only edits the reviewed intelligence boundary files, refuses ambiguous source
matches, and leaves formatting plus native verification to the workflow.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one source match in {relative}, found {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(relative: str, marker: str, text: str) -> None:
    path = ROOT / relative
    current = path.read_text(encoding="utf-8")
    if marker in current:
        return
    path.write_text(current.rstrip() + "\n\n" + text.rstrip() + "\n", encoding="utf-8")


ROLLBACK_MODULE = "codex-rs/hepta-agentd/src/intelligence_authority_rollback.rs"
if not (ROOT / ROLLBACK_MODULE).is_file():
    raise SystemExit("missing reviewed authority rollback module")

# Register and export the owner-independent monotonic witness.
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "mod intelligence_ingress;\nmod intelligence_learning;",
    "mod intelligence_authority_rollback;\nmod intelligence_ingress;\nmod intelligence_learning;",
)
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "pub use intelligence_ingress::AgentdIntelligenceInvocationProviderV1;",
    "pub use intelligence_authority_rollback::IntelligenceAuthorityRollbackErrorV1;\n"
    "pub use intelligence_authority_rollback::IntelligenceAuthorityRollbackGuardV1;\n"
    "pub use intelligence_ingress::AgentdIntelligenceInvocationProviderV1;",
)
replace_once(
    "codex-rs/hepta-agentd/src/lib.rs",
    "pub use intelligence_product::intelligence_evaluation_binding_payload_v1;",
    "pub use intelligence_product::intelligence_authority_manifest_digest_v1;\n"
    "pub use intelligence_product::intelligence_evaluation_binding_payload_v1;",
)

# Every signed manifest read is checked against one independently retained
# monotonic epoch/digest floor. Existing constructors stay source-compatible for
# qualification-only callers; the canonical runner supplies the guard.
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "struct FileBackedFreshnessOracleV1 {\n"
    "    path: PathBuf,\n"
    "    verifier: IntelligenceAuthorityVerifierV1,\n"
    "    telemetry: Option<Arc<crate::AgentdIntelligenceTelemetryV1>>,\n"
    "}",
    "struct FileBackedFreshnessOracleV1 {\n"
    "    path: PathBuf,\n"
    "    verifier: IntelligenceAuthorityVerifierV1,\n"
    "    rollback: Option<Arc<crate::IntelligenceAuthorityRollbackGuardV1>>,\n"
    "    telemetry: Option<Arc<crate::AgentdIntelligenceTelemetryV1>>,\n"
    "}",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "    fn new(path: PathBuf, verifier: IntelligenceAuthorityVerifierV1) -> Self {\n"
    "        Self { path, verifier, telemetry: None }\n"
    "    }",
    "    fn new(path: PathBuf, verifier: IntelligenceAuthorityVerifierV1) -> Self {\n"
    "        Self { path, verifier, rollback: None, telemetry: None }\n"
    "    }",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "        Self { path, verifier, telemetry: Some(telemetry) }\n"
    "    }\n\n"
    "    fn read(&self, requested: &StableId)",
    "        Self { path, verifier, rollback: None, telemetry: Some(telemetry) }\n"
    "    }\n\n"
    "    fn with_rollback(\n"
    "        mut self,\n"
    "        rollback: Option<Arc<crate::IntelligenceAuthorityRollbackGuardV1>>,\n"
    "    ) -> Self {\n"
    "        self.rollback = rollback;\n"
    "        self\n"
    "    }\n\n"
    "    fn read(&self, requested: &StableId)",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "        if file.schema_version != 1 || file.authority_epoch == 0 || file.owners.len() != 7 {\n"
    "            return Err(unavailable());\n"
    "        }\n"
    "        if let Some(telemetry) = self.telemetry.as_ref() {",
    "        if file.schema_version != 1 || file.authority_epoch == 0 || file.owners.len() != 7 {\n"
    "            return Err(unavailable());\n"
    "        }\n"
    "        if let Some(rollback) = self.rollback.as_ref() {\n"
    "            let manifest_digest = intelligence_authority_manifest_digest_v1(&file)\n"
    "                .map_err(|_| unavailable())?;\n"
    "            rollback\n"
    "                .admit(file.authority_epoch, manifest_digest)\n"
    "                .map_err(|_| unavailable())?;\n"
    "        }\n"
    "        if let Some(telemetry) = self.telemetry.as_ref() {",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "    InvalidAuthorityVerifier,\n    InvalidWorkerPolicy,",
    "    InvalidAuthorityVerifier,\n    InvalidAuthorityRollback,\n    InvalidWorkerPolicy,",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "    authority_verifier: IntelligenceAuthorityVerifierV1,\n"
    "    evaluation_trust: Option<Arc<codex_hepta_learning_ledger::ActivatedLearningTrustV1>>,",
    "    authority_verifier: IntelligenceAuthorityVerifierV1,\n"
    "    authority_rollback: Option<Arc<crate::IntelligenceAuthorityRollbackGuardV1>>,\n"
    "    evaluation_trust: Option<Arc<codex_hepta_learning_ledger::ActivatedLearningTrustV1>>,",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "fn verify_authority_file(\n",
    "/// Exact identity of one already signed authority manifest, including its\n"
    "/// signature bytes. The monotonic guard consumes this only after signature\n"
    "/// verification; the digest itself grants no authority.\n"
    "pub fn intelligence_authority_manifest_digest_v1(\n"
    "    file: &IntelligenceAuthorityFileV1,\n"
    ") -> Result<Digest32, serde_json::Error> {\n"
    "    let mut bytes = b\"hepta.agentd.intelligence-authority-manifest.v1\\0\".to_vec();\n"
    "    bytes.extend_from_slice(&authority_signing_payload(file)?);\n"
    "    bytes.extend_from_slice(&file.signature);\n"
    "    Ok(Digest32::of_bytes(&bytes))\n"
    "}\n\n"
    "fn verify_authority_file(\n",
)

# Canonical runner composition is guard-aware, includes the guard location in
# its profile identity, and supplies the guard at every owner/final-use read.
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "            authority_verifier,\n            evaluation_trust: None,",
    "            authority_verifier,\n            authority_rollback: None,\n            evaluation_trust: None,",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "    pub fn with_evaluation_trust(\n",
    "    /// Install the independently retained monotonic witness used by every\n"
    "    /// signed owner-manifest read. The witness must not be the manifest.\n"
    "    pub fn with_authority_rollback_guard(\n"
    "        mut self,\n"
    "        guard: Arc<crate::IntelligenceAuthorityRollbackGuardV1>,\n"
    "    ) -> Result<Self, AgentdIntelligenceProductError> {\n"
    "        if self.authority_rollback.is_some() || guard.path() == self.authority_file {\n"
    "            return Err(AgentdIntelligenceProductError::InvalidAuthorityRollback);\n"
    "        }\n"
    "        self.authority_rollback = Some(guard);\n"
    "        Ok(self)\n"
    "    }\n\n"
    "    pub fn with_evaluation_trust(\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "    pub fn telemetry(&self) -> Arc<crate::AgentdIntelligenceTelemetryV1> {\n"
    "        Arc::clone(&self.telemetry)\n"
    "    }\n\n"
    "    #[must_use]\n"
    "    pub fn capability_profile_digest",
    "    pub fn telemetry(&self) -> Arc<crate::AgentdIntelligenceTelemetryV1> {\n"
    "        Arc::clone(&self.telemetry)\n"
    "    }\n\n"
    "    #[must_use]\n"
    "    pub fn canonical_profile_ready(&self) -> bool {\n"
    "        self.authority_rollback.is_some()\n"
    "    }\n\n"
    "    #[must_use]\n"
    "    pub fn authority_rollback_path(&self) -> Option<&std::path::Path> {\n"
    "        self.authority_rollback.as_deref().map(|guard| guard.path())\n"
    "    }\n\n"
    "    #[must_use]\n"
    "    pub fn capability_profile_digest",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "        match self.evaluation_trust.as_ref() {",
    "        match self.authority_rollback.as_ref() {\n"
    "            Some(guard) => {\n"
    "                bytes.push(1);\n"
    "                bytes.extend_from_slice(guard.profile_digest().as_array());\n"
    "            }\n"
    "            None => bytes.push(0),\n"
    "        }\n"
    "        match self.evaluation_trust.as_ref() {",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "        let authority_verifier = self.authority_verifier.clone();\n"
    "        let evaluation_trust = self.evaluation_trust.clone();",
    "        let authority_verifier = self.authority_verifier.clone();\n"
    "        let authority_rollback = self.authority_rollback.clone();\n"
    "        let evaluation_trust = self.evaluation_trust.clone();",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "            let mut oracle = FileBackedFreshnessOracleV1::new_observed(\n"
    "                authority_file, authority_verifier, Arc::clone(&worker_telemetry),\n"
    "            );",
    "            let mut oracle = FileBackedFreshnessOracleV1::new_observed(\n"
    "                authority_file, authority_verifier, Arc::clone(&worker_telemetry),\n"
    "            )\n"
    "            .with_rollback(authority_rollback);",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "                let verifier = self.authority_verifier.clone();\n"
    "                let telemetry = Arc::clone(&self.telemetry);",
    "                let verifier = self.authority_verifier.clone();\n"
    "                let rollback = self.authority_rollback.clone();\n"
    "                let telemetry = Arc::clone(&self.telemetry);",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "                    let mut oracle = FileBackedFreshnessOracleV1::new_observed(\n"
    "                        authority_file, verifier, telemetry,\n"
    "                    );",
    "                    let mut oracle = FileBackedFreshnessOracleV1::new_observed(\n"
    "                        authority_file, verifier, telemetry,\n"
    "                    )\n"
    "                    .with_rollback(rollback);",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "        let mut oracle = FileBackedFreshnessOracleV1::new(self.authority_file.clone(), self.authority_verifier.clone());",
    "        let mut oracle = FileBackedFreshnessOracleV1::new(\n"
    "            self.authority_file.clone(),\n"
    "            self.authority_verifier.clone(),\n"
    "        )\n"
    "        .with_rollback(self.authority_rollback.clone());",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "        let mut oracle = FileBackedFreshnessOracleV1::new(self.authority_file.clone(), self.authority_verifier.clone());",
    "        let mut oracle = FileBackedFreshnessOracleV1::new(\n"
    "            self.authority_file.clone(),\n"
    "            self.authority_verifier.clone(),\n"
    "        )\n"
    "        .with_rollback(self.authority_rollback.clone());",
)

# The product configuration and direct state attachment both fail closed. The
# guard path must be canonical and outside the Agent home/run trees so restoring
# an old Agent snapshot cannot roll the witness back with it.
replace_once(
    "codex-rs/hepta-agentd/src/config.rs",
    "    pub fn with_intelligence_invocation_provider(\n"
    "        mut self,\n"
    "        provider: std::sync::Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>,\n"
    "    ) -> Result<Self, AgentdError> {\n"
    "        if self.intelligence_invocation_provider.is_some() {",
    "    pub fn with_intelligence_invocation_provider(\n"
    "        mut self,\n"
    "        provider: std::sync::Arc<dyn crate::AgentdIntelligenceInvocationProviderV1>,\n"
    "    ) -> Result<Self, AgentdError> {\n"
    "        let runner = self.intelligence_product_runner.as_ref().ok_or_else(|| {\n"
    "            AgentdError::Invalid(\n"
    "                \"canonical intelligence invocation requires its guarded product runner first\"\n"
    "                    .to_string(),\n"
    "            )\n"
    "        })?;\n"
    "        self.require_canonical_intelligence_runner(runner)?;\n"
    "        if self.intelligence_invocation_provider.is_some() {",
)
replace_once(
    "codex-rs/hepta-agentd/src/config.rs",
    "        runner.telemetry().set_provider_configured(true);\n"
    "        self.intelligence_product_runner = Some(runner);",
    "        self.require_canonical_intelligence_runner(&runner)?;\n"
    "        runner.telemetry().set_provider_configured(true);\n"
    "        self.intelligence_product_runner = Some(runner);",
)
replace_once(
    "codex-rs/hepta-agentd/src/config.rs",
    "        if self.intelligence_learning_runtime.is_some() {",
    "        if let Some(runner) = self.intelligence_product_runner.as_ref() {\n"
    "            self.require_canonical_intelligence_runner(runner)?;\n"
    "        }\n"
    "        if self.intelligence_learning_runtime.is_some() {",
)
replace_once(
    "codex-rs/hepta-agentd/src/config.rs",
    "    pub fn identity(&self) -> &AgentdIdentity {",
    "    fn require_canonical_intelligence_runner(\n"
    "        &self,\n"
    "        runner: &crate::AgentdIntelligenceProductRunnerV1,\n"
    "    ) -> Result<(), AgentdError> {\n"
    "        if !runner.canonical_profile_ready() {\n"
    "            return Err(AgentdError::Invalid(\n"
    "                \"canonical intelligence requires an independent authority rollback guard\"\n"
    "                    .to_string(),\n"
    "            ));\n"
    "        }\n"
    "        let path = runner.authority_rollback_path().ok_or_else(|| {\n"
    "            AgentdError::Invalid(\n"
    "                \"canonical intelligence rollback witness is unavailable\".to_string(),\n"
    "            )\n"
    "        })?;\n"
    "        require_canonical(path, \"intelligence authority rollback witness\")?;\n"
    "        if path.starts_with(&self.identity.home_root) || path.starts_with(&self.identity.run_root) {\n"
    "            return Err(AgentdError::Invalid(\n"
    "                \"intelligence authority rollback witness must be retained outside Agent home/run roots\"\n"
    "                    .to_string(),\n"
    "            ));\n"
    "        }\n"
    "        Ok(())\n"
    "    }\n\n"
    "    pub fn identity(&self) -> &AgentdIdentity {",
)

replace_once(
    "codex-rs/hepta-agentd/src/state.rs",
    "    pub(crate) fn canonical_intelligence_enabled(&self) -> bool {\n"
    "        self.intelligence_product.get().is_some() && self.intelligence_invocation.get().is_some()\n"
    "    }",
    "    pub(crate) fn canonical_intelligence_enabled(&self) -> bool {\n"
    "        self.intelligence_product\n"
    "            .get()\n"
    "            .is_some_and(|runner| runner.canonical_profile_ready())\n"
    "            && self.intelligence_invocation.get().is_some()\n"
    "    }",
)
replace_once(
    "codex-rs/hepta-agentd/src/state.rs",
    "        let invocation = provider.build(&self.identity, record)?;",
    "        if !runner.canonical_profile_ready() {\n"
    "            return Err(AgentdError::Invalid(\n"
    "                \"canonical intelligence runner has no independent authority rollback witness\"\n"
    "                    .to_string(),\n"
    "            ));\n"
    "        }\n\n"
    "        let invocation = provider.build(&self.identity, record)?;",
)

# Add the guard regression to explicit source/test/requirement declarations.
replace_once(
    "scripts/hepta-intelligence-control-status.py",
    '    "utility_universe_rejects_foreign_and_missing_candidates",\n}',
    '    "utility_universe_rejects_foreign_and_missing_candidates",\n'
    '    "guard_rejects_rollback_and_same_epoch_drift_and_survives_reopen",\n}',
)

implementation_path = ROOT / "docs/modules/intelligence.control/IMPLEMENTATION_MAP.json"
implementation = json.loads(implementation_path.read_text(encoding="utf-8"))
implementation["statusMatrix"]["authorityManifestAntiRollbackPresent"] = True
binding = {
    "sourcePath": ROLLBACK_MODULE,
    "symbols": [
        "IntelligenceAuthorityRollbackGuardV1",
        "SameEpochConflict",
        "persist_record",
        "parent-directory fsync",
    ],
}
if not any(row["sourcePath"] == ROLLBACK_MODULE for row in implementation["sourceBindings"]):
    implementation["sourceBindings"].append(binding)
operation = {
    "operation": "IntelligenceAuthorityRollbackGuardV1::admit",
    "sourcePath": ROLLBACK_MODULE,
    "requirements": ["authority_manifest_anti_rollback"],
}
if not any(row["operation"] == operation["operation"] for row in implementation["canonicalOperations"]):
    implementation["canonicalOperations"].append(operation)
implementation["capabilityBoundary"][
    "advertisedOnlyWhenRunnerProviderAndRollbackGuardPresent"
] = True
implementation["openAcceptanceGaps"] = [
    (
        "Authority manifest reads still need parent-directory-anchored no-follow opening and "
        "target-host restore/crash qualification."
        if value.startswith("Authority manifest reads still need")
        else value
    )
    for value in implementation["openAcceptanceGaps"]
]
implementation_path.write_text(json.dumps(implementation, indent=2) + "\n", encoding="utf-8")

trace_path = ROOT / "docs/modules/intelligence.control/TEST_TRACEABILITY.json"
trace = json.loads(trace_path.read_text(encoding="utf-8"))
requirement = {
    "id": "authority_manifest_anti_rollback",
    "tests": ["guard_rejects_rollback_and_same_epoch_drift_and_survives_reopen"],
    "supportScope": (
        "independently retained epoch/digest floor with locked durable reopen; "
        "target-host backup separation and crash injection remain open"
    ),
}
if not any(row["id"] == requirement["id"] for row in trace["requirements"]):
    trace["requirements"].append(requirement)
test = {
    "name": "guard_rejects_rollback_and_same_epoch_drift_and_survives_reopen",
    "sourcePath": ROLLBACK_MODULE,
    "package": "codex-hepta-agentd",
    "executionStatus": "pending",
}
if not any(row["name"] == test["name"] for row in trace["ordinaryProductTests"]):
    trace["ordinaryProductTests"].append(test)
for row in trace["requirements"]:
    if row["id"] == "seven_owner_currentness":
        row["supportScope"] = (
            "canonical oracle/port invariants plus an independently retained signed-manifest "
            "rollback floor; target-host backup/restore qualification remains open"
        )
trace_path.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")

append_once(
    "docs/modules/intelligence.control/PRODUCT_CLOSURE.md",
    "## 10. Independent authority-manifest rollback floor",
    """## 10. Independent authority-manifest rollback floor

The canonical runner now requires a host-owned `IntelligenceAuthorityRollbackGuardV1` before
runner/provider composition can be advertised or executed. The witness is retained outside the
Agent home and run roots, holds a single-process lock, and durably records the greatest admitted
authority epoch together with the exact signed-manifest digest. Lower epochs and same-epoch byte
substitution fail closed after reopen. Signature verification still occurs on every use; the
rollback record grants no authority and cannot replace current owner, key, epoch, or revocation
checks.

This closes the repository-owned signed-backup replay primitive. Target-host backup separation,
parent-directory-anchored no-follow open, process-crash injection, independent security review,
and activation remain separate evidence gates.""",
)
append_once(
    "docs/modules/intelligence.control/TECHNICAL.md",
    "### Independent authority-manifest rollback floor",
    """### Independent authority-manifest rollback floor

The configured canonical profile is fail-closed unless the runner carries an independently
retained `IntelligenceAuthorityRollbackGuardV1`. The witness path must be canonical and outside
both Agent home and run roots. Each signature-verified authority manifest is then checked against
the durable maximum epoch and exact same-epoch digest before its owner bindings can satisfy a
currentness read. Compatibility-only runner construction may omit the witness, but such a runner
cannot be advertised or entered as `intelligence.canonical_v1`.""",
)

print("finalized intelligence.control authority rollback and traceability")
