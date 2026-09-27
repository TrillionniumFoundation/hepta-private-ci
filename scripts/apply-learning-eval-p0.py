#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one source match, found {count}: {old[:80]!r}")
    write(path, text.replace(old, new, 1))


def append_once(path: str, marker: str, content: str) -> None:
    text = read(path)
    if marker in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    write(path, text + "\n" + content.rstrip() + "\n")


SIGNED_ADMISSION = r'''//! Consumer-bound public admission for independently signed evaluation evidence.
//!
//! The low-level V2 decision primitive remains crate-private. Product consumers
//! use this facade so the terminal decision is sealed to one nonzero consumer
//! context and cannot be replayed as a generic qualification or effect authority.

use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::IndependentEvaluationBundleV1;
use crate::IndependentEvaluationDispositionV1;
use crate::MetricRoleContractV2;
use crate::SignedEvaluationDecisionV1;
use crate::SignedEvaluationError;
use crate::SignedEvaluationEvidenceV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SignedEvaluationAdmissionV1 {
    pub candidate_id: StableId,
    pub objective_digest: Digest32,
    pub consumer_binding_digest: Digest32,
    pub decision: SignedEvaluationDecisionV1,
    pub admission_digest: Digest32,
    pub authority: AuthorityPosture,
    receipt_seal: Digest32,
}

impl SignedEvaluationAdmissionV1 {
    pub fn validate_integrity(&self) -> Result<(), SignedEvaluationError> {
        if self.objective_digest.is_zero()
            || self.consumer_binding_digest.is_zero()
            || self.decision.decision.evidence_digest.is_zero()
            || self.decision.trust_digest.is_zero()
            || self.decision.authentication_digest.is_zero()
            || self.admission_digest.is_zero()
            || self.candidate_id != self.decision.decision.candidate_id
            || self.authority.grants_any()
            || self.decision.decision.authority.grants_any()
            || self.admission_digest != admission_evidence_digest(self)
            || self.receipt_seal != admission_receipt_seal(self)
        {
            return Err(SignedEvaluationError::Timing(
                "consumer_admission_integrity",
            ));
        }
        Ok(())
    }
}

pub fn admit_signed_evaluation_v2(
    bundle: IndependentEvaluationBundleV1,
    roles: Vec<MetricRoleContractV2>,
    evidence: &SignedEvaluationEvidenceV1,
    verifier: &LearningEvidenceVerifierV1,
    consumer_binding_digest: Digest32,
    now: u64,
) -> Result<SignedEvaluationAdmissionV1, SignedEvaluationError> {
    if consumer_binding_digest.is_zero() {
        return Err(SignedEvaluationError::Timing("consumer_binding"));
    }
    let candidate_id = bundle.candidate_id.clone();
    let objective_digest = bundle.objective_digest;
    let decision = crate::decide_with_signed_evidence_v2(bundle, roles, evidence, verifier, now)?;
    let mut receipt = SignedEvaluationAdmissionV1 {
        candidate_id,
        objective_digest,
        consumer_binding_digest,
        decision,
        admission_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
        receipt_seal: Digest32::ZERO,
    };
    receipt.admission_digest = admission_evidence_digest(&receipt);
    receipt.receipt_seal = admission_receipt_seal(&receipt);
    receipt.validate_integrity()?;
    Ok(receipt)
}

fn admission_evidence_digest(receipt: &SignedEvaluationAdmissionV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.consumer-admission.v1\0".to_vec();
    push_id(&mut bytes, &receipt.candidate_id);
    for digest in [
        receipt.objective_digest,
        receipt.consumer_binding_digest,
        receipt.decision.decision.evidence_digest,
        receipt.decision.trust_digest,
        receipt.decision.authentication_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.push(match receipt.decision.decision.disposition {
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection => 0,
        IndependentEvaluationDispositionV1::Ineligible => 1,
        IndependentEvaluationDispositionV1::InsufficientEvidence => 2,
    });
    bytes.push(u8::from(receipt.authority.grants_any()));
    bytes.push(u8::from(receipt.decision.decision.authority.grants_any()));
    Digest32::of_bytes(&bytes)
}

fn admission_receipt_seal(receipt: &SignedEvaluationAdmissionV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.consumer-admission-receipt.v1\0".to_vec();
    bytes.extend_from_slice(admission_evidence_digest(receipt).as_array());
    bytes.extend_from_slice(receipt.admission_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let length = u64::try_from(value.as_str().len()).unwrap_or(u64::MAX);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::IndependentEvaluationDecisionV1;

    fn id(value: &str) -> StableId {
        match StableId::new(value.to_owned()) {
            Ok(value) => value,
            Err(error) => panic!("invalid test id {value}: {error}"),
        }
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn receipt() -> SignedEvaluationAdmissionV1 {
        let decision = SignedEvaluationDecisionV1 {
            decision: IndependentEvaluationDecisionV1 {
                evaluation_id: id("evaluation"),
                candidate_id: id("candidate"),
                baseline_id: id("baseline"),
                disposition: IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
                failed_metrics: Vec::new(),
                evidence_digest: digest("decision"),
                authority: AuthorityPosture::DENY_ALL,
            },
            trust_digest: digest("trust"),
            authentication_digest: digest("authentication"),
        };
        let mut receipt = SignedEvaluationAdmissionV1 {
            candidate_id: id("candidate"),
            objective_digest: digest("objective"),
            consumer_binding_digest: digest("consumer"),
            decision,
            admission_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
            receipt_seal: Digest32::ZERO,
        };
        receipt.admission_digest = admission_evidence_digest(&receipt);
        receipt.receipt_seal = admission_receipt_seal(&receipt);
        receipt
    }

    #[test]
    fn sealed_consumer_admission_detects_context_mutation() {
        let mut value = receipt();
        assert_eq!(value.validate_integrity(), Ok(()));
        value.consumer_binding_digest = digest("other-consumer");
        assert!(matches!(
            value.validate_integrity(),
            Err(SignedEvaluationError::Timing(
                "consumer_admission_integrity"
            ))
        ));
    }
}
'''

PRIVATE_API_FIXTURE_TOML = r'''[package]
name = "learning-eval-private-api-fixture"
version = "0.0.0"
edition = "2024"
publish = false

[workspace]

[dependencies]
codex-hepta-intelligence-eval = { path = "../../../codex-rs/hepta-intelligence-eval" }
'''

PRIVATE_API_FIXTURE_RS = r'''use codex_hepta_intelligence_eval::decide_with_signed_evidence_v2;

pub fn forbidden_external_import() {
    let _ = decide_with_signed_evidence_v2;
}
'''

PRIVATE_API_PROBE = r'''#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="${ROOT}/qualification/fixtures/learning-eval-private-api/Cargo.toml"
OUTPUT="$(mktemp)"
trap 'rm -f "${OUTPUT}" "${ROOT}/qualification/fixtures/learning-eval-private-api/Cargo.lock"' EXIT

set +e
cargo check \
  --manifest-path "${MANIFEST}" \
  --offline \
  --target-dir "${ROOT}/target/learning-eval-private-api" \
  >"${OUTPUT}" 2>&1
STATUS=$?
set -e

if [[ ${STATUS} -eq 0 ]]; then
  cat "${OUTPUT}"
  echo "low-level learning.eval decision API unexpectedly compiled outside its owner crate" >&2
  exit 1
fi
if ! grep -Eq 'E0603|private (function|item)' "${OUTPUT}"; then
  cat "${OUTPUT}"
  echo "private API fixture failed for an unrelated reason" >&2
  exit 1
fi
printf '%s\n' 'private low-level learning.eval API probe passed'
'''


def patch_sources() -> None:
    write("codex-rs/hepta-intelligence-eval/src/signed_admission.rs", SIGNED_ADMISSION)

    replace_once(
        "codex-rs/hepta-intelligence-eval/src/lib.rs",
        "mod sequential;\nmod signed_evaluation;\nmod temporal_evaluation;",
        "mod sequential;\nmod signed_admission;\nmod signed_evaluation;\nmod temporal_evaluation;",
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/lib.rs",
        "pub use signed_evaluation::SignedEvaluationDecisionV1;\npub use signed_evaluation::SignedEvaluationError;\npub use signed_evaluation::SignedEvaluationEvidenceV1;",
        "pub use signed_admission::SignedEvaluationAdmissionV1;\npub use signed_admission::admit_signed_evaluation_v2;\npub use signed_evaluation::SignedEvaluationDecisionV1;\npub use signed_evaluation::SignedEvaluationError;\npub use signed_evaluation::SignedEvaluationEvidenceV1;",
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/lib.rs",
        "pub use signed_evaluation::decide_with_signed_evidence_v2;",
        "pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;",
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/src/signed_evaluation.rs",
        "pub fn decide_with_signed_evidence_v2(\n",
        "pub(crate) fn decide_with_signed_evidence_v2(\n",
    )

    replace_once(
        "codex-rs/hepta-agentd/src/intelligence_evaluation.rs",
        "use codex_hepta_intelligence_eval::decide_with_signed_evidence_v2;",
        "use codex_hepta_intelligence_eval::admit_signed_evaluation_v2;",
    )
    replace_once(
        "codex-rs/hepta-agentd/src/intelligence_evaluation.rs",
        "        let result = decide_with_signed_evidence_v2(\n            self.signed.bundle,\n            self.signed.roles,\n            &self.signed.evidence,\n            self.trust.verifier(),\n            now,\n        )\n        .map_err(AgentdIntelligenceEvaluationError::Evaluation)?;\n        if result.decision.authority.grants_any()\n            || result.decision.disposition\n                != IndependentEvaluationDispositionV1::EligibleForIndependentSelection\n        {\n            return Err(AgentdIntelligenceEvaluationError::Ineligible);\n        }\n        let mut receipt = b\"hepta.agentd.evaluation-consumption.v1\\0\".to_vec();\n        receipt.extend_from_slice(Digest32::of_bytes(&payload).as_array());\n        receipt.extend_from_slice(result.authentication_digest.as_array());",
        "        let admission = admit_signed_evaluation_v2(\n            self.signed.bundle,\n            self.signed.roles,\n            &self.signed.evidence,\n            self.trust.verifier(),\n            Digest32::of_bytes(&payload),\n            now,\n        )\n        .map_err(AgentdIntelligenceEvaluationError::Evaluation)?;\n        if admission.decision.decision.authority.grants_any()\n            || admission.decision.decision.disposition\n                != IndependentEvaluationDispositionV1::EligibleForIndependentSelection\n        {\n            return Err(AgentdIntelligenceEvaluationError::Ineligible);\n        }\n        let mut receipt = b\"hepta.agentd.evaluation-consumption.v1\\0\".to_vec();\n        receipt.extend_from_slice(Digest32::of_bytes(&payload).as_array());\n        receipt.extend_from_slice(admission.admission_digest.as_array());\n        receipt.extend_from_slice(admission.decision.authentication_digest.as_array());",
    )

    replace_once(
        "codex-rs/hepta-intelligence/src/plasticity_product.rs",
        "use codex_hepta_intelligence_eval::decide_with_signed_evidence_v2;",
        "use codex_hepta_intelligence_eval::admit_signed_evaluation_v2;",
    )
    replace_once(
        "codex-rs/hepta-intelligence/src/plasticity_product.rs",
        "        let decision =\n            decide_with_signed_evidence_v2(bundle, metric_roles, &evidence, verifier, now)\n                .map_err(E::Evaluation)?;\n        if decision.decision.disposition\n            != IndependentEvaluationDispositionV1::EligibleForIndependentSelection\n        {\n            return Err(E::Ineligible(decision.decision.disposition));\n        }\n        push_id(&mut evaluation_binding, &candidate_id);\n        evaluation_binding.extend_from_slice(decision.decision.evidence_digest.as_array());\n        evaluation_binding.extend_from_slice(decision.authentication_digest.as_array());\n        evaluation_binding.extend_from_slice(decision.trust_digest.as_array());",
        "        let mut consumer_binding =\n            b\"hepta.intelligence.plasticity-evaluation-use.v1\\0\".to_vec();\n        push_id(&mut consumer_binding, &candidate_id);\n        for digest in [\n            request.admission.owner_evidence_set_digest,\n            request.admission.selected_artifact_digest,\n            request.admission.qualification_evidence_head_digest,\n            Digest32::of_bytes(&evaluator_payload),\n        ] {\n            consumer_binding.extend_from_slice(digest.as_array());\n        }\n        let admission = admit_signed_evaluation_v2(\n            bundle,\n            metric_roles,\n            &evidence,\n            verifier,\n            Digest32::of_bytes(&consumer_binding),\n            now,\n        )\n        .map_err(E::Evaluation)?;\n        if admission.decision.decision.disposition\n            != IndependentEvaluationDispositionV1::EligibleForIndependentSelection\n        {\n            return Err(E::Ineligible(admission.decision.decision.disposition));\n        }\n        push_id(&mut evaluation_binding, &candidate_id);\n        evaluation_binding.extend_from_slice(admission.admission_digest.as_array());\n        evaluation_binding\n            .extend_from_slice(admission.decision.decision.evidence_digest.as_array());\n        evaluation_binding\n            .extend_from_slice(admission.decision.authentication_digest.as_array());\n        evaluation_binding.extend_from_slice(admission.decision.trust_digest.as_array());",
    )


def patch_private_api_verifier() -> None:
    path = "scripts/hepta-lane-e-closure.py"
    text = read(path)
    marker = "def verify_learning_eval_private_api(findings: Findings) -> None:"
    if marker not in text:
        function = r'''

def verify_learning_eval_private_api(findings: Findings) -> None:
    owner_root = ROOT / "codex-rs/hepta-intelligence-eval"
    forbidden = re.compile(
        r"\bdecide_with_signed_(?:longitudinal_)?evidence_v[23]\b"
    )
    for source in (ROOT / "codex-rs").rglob("*.rs"):
        if source == owner_root or owner_root in source.parents:
            continue
        source_text = source.read_text(encoding="utf-8")
        findings.require(
            forbidden.search(source_text) is None,
            "learning_eval_private_api_bypass",
            f"{source.relative_to(ROOT)} directly imports a crate-private learning.eval decision primitive",
        )

    expected_callers = {
        ROOT / "codex-rs/hepta-agentd/src/intelligence_evaluation.rs",
        ROOT / "codex-rs/hepta-intelligence/src/plasticity_product.rs",
    }
    for source in expected_callers:
        findings.require(
            source.is_file(),
            "learning_eval_admission_caller_missing",
            f"missing high-level learning.eval caller: {source.relative_to(ROOT)}",
        )
        if source.is_file():
            source_text = source.read_text(encoding="utf-8")
            findings.require(
                "admit_signed_evaluation_v2" in source_text,
                "learning_eval_admission_caller_unmigrated",
                f"{source.relative_to(ROOT)} does not consume the high-level admission facade",
            )

    fixture = ROOT / "qualification/fixtures/learning-eval-private-api/src/lib.rs"
    findings.require(
        fixture.is_file() and "decide_with_signed_evidence_v2" in fixture.read_text(encoding="utf-8"),
        "learning_eval_private_api_fixture_missing",
        "the external compile-fail fixture for the low-level evaluator is missing",
    )
'''
        text = text.replace("\ndef verify() -> Findings:\n", function + "\n\ndef verify() -> Findings:\n", 1)
    if "    verify_learning_eval_private_api(findings)\n" not in text:
        text = text.replace(
            "    verify_learning_eval_production_boundary(findings)\n",
            "    verify_learning_eval_production_boundary(findings)\n    verify_learning_eval_private_api(findings)\n",
            1,
        )
    write(path, text)


def patch_workflow_and_fixture() -> None:
    write(
        "qualification/fixtures/learning-eval-private-api/Cargo.toml",
        PRIVATE_API_FIXTURE_TOML,
    )
    write(
        "qualification/fixtures/learning-eval-private-api/src/lib.rs",
        PRIVATE_API_FIXTURE_RS,
    )
    write("scripts/hepta-learning-eval-private-api.sh", PRIVATE_API_PROBE)

    path = ".github/workflows/hepta-lane-e-gap-closure.yml"
    text = read(path)
    needle = "          python3 scripts/hepta-lane-e-closure.py verify\n"
    addition = needle + "          bash scripts/hepta-learning-eval-private-api.sh\n"
    if "bash scripts/hepta-learning-eval-private-api.sh" not in text:
        count = text.count(needle)
        if count < 2:
            raise RuntimeError(f"{path}: expected at least two Lane E verifier calls, found {count}")
        text = text.replace(needle, addition)
        write(path, text)


def patch_docs() -> None:
    replace_once(
        "codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md",
        "External or production callers enter through `ProductEvaluationRunnerV1`; the runner invokes signature-verified V2/V3 admission internally. Asserted `AuthenticatedPrincipalV1` values are not external authentication, and direct signed-decision functions are intentionally not part of the default cross-crate surface.",
        "Qualification issuance enters through `ProductEvaluationRunnerV1`; the runner invokes signature-verified V2/V3 admission internally. Downstream product consumers that must revalidate an already frozen signed bundle use `admit_signed_evaluation_v2`, which seals the decision to one nonzero consumer-context digest and still grants no authority. Asserted `AuthenticatedPrincipalV1` values are not external authentication, and direct signed-decision functions are not part of the default cross-crate surface.",
    )
    replace_once(
        "codex-rs/hepta-intelligence-eval/PRODUCTION_CONTRACT.md",
        "| `decide_with_signed_evidence_v2` / `decide_with_signed_longitudinal_evidence_v3` | **Crate-internal verification primitives** | Not default cross-crate APIs; only the product runner may turn them into product qualification |",
        "| `admit_signed_evaluation_v2` | **Public consumer admission facade** | Revalidates signed V2 evidence and seals the terminal `DENY_ALL` decision to one consumer binding; it cannot issue final-holdout, publication, selection or release evidence |\n| `decide_with_signed_evidence_v2` / `decide_with_signed_longitudinal_evidence_v3` | **Crate-internal verification primitives** | Not cross-crate APIs; only owner-crate facades may invoke them |",
    )
    append_once(
        "codex-rs/hepta-intelligence-eval/NATIVE_MAPPING.md",
        "## Consumer-bound admission facade",
        """## Consumer-bound admission facade

`admit_signed_evaluation_v2` is the only default cross-crate V2 revalidation
surface. It invokes the crate-private decision primitive, requires a nonzero
consumer-context digest, and returns a privately sealed
`SignedEvaluationAdmissionV1` whose authority remains `DENY_ALL`. Agentd and the
plasticity product compose this facade; no external crate imports the low-level
V2/V3 decision functions.
""",
    )
    append_once(
        "codex-rs/hepta-intelligence-eval/EVIDENCE_ADMISSION.md",
        "## Consumer-bound revalidation",
        """## Consumer-bound revalidation

Repository product consumers do not import low-level signed-decision functions.
They call `admit_signed_evaluation_v2` with a digest of the exact prepared use
context. The returned `SignedEvaluationAdmissionV1` binds that digest, the
candidate, objective, signed decision, trust and authentication digests under a
private integrity seal and retains `DENY_ALL`. This facade is revalidation only:
it cannot substitute for `ProductEvaluationRunnerV1`, final-holdout consumption,
durable qualification publication, selection or release.
""",
    )
    append_once(
        "docs/modules/learning.eval/TECHNICAL.md",
        "### Consumer admission boundary",
        """### Consumer admission boundary

The default cross-crate V2 surface is `admit_signed_evaluation_v2`, which binds a
signed decision to an exact consumer context and returns a sealed, authority-free
admission receipt. `decide_with_signed_evidence_v2` and the V3 longitudinal
primitive are crate-private. Closed-world verification rejects every direct
external reference and CI compiles an external fixture that must fail with Rust
privacy error E0603.
""",
    )
    append_once(
        "qualification/module-execution-dossiers/detail/learning.eval.md",
        "## 10. API closure update",
        """## 10. API closure update

Agentd and governed plasticity consume `admit_signed_evaluation_v2`; both bind the
admission to their exact prepared-use context. The underlying V2/V3 decision
functions are crate-private and an external compile-fail fixture is a required
Lane E gate. This closes the repository-controlled low-level API bypass without
turning consumer revalidation into qualification, activation or release.
""",
    )


def patch_implementation_map() -> None:
    path = ROOT / "docs/modules/learning.eval/IMPLEMENTATION_MAP.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    operations = data.setdefault("operations", [])
    for operation in operations:
        if operation.get("operation") == "decide_with_signed_evidence_v2":
            operation["state"] = "crate_internal_verification_primitive"
            operation["nativeSymbol"] = "signed_evaluation::decide_with_signed_evidence_v2"
    if not any(operation.get("operation") == "admit_signed_evaluation_v2" for operation in operations):
        operations.append(
            {
                "operation": "admit_signed_evaluation_v2",
                "nativeSymbol": "admit_signed_evaluation_v2",
                "sourcePath": "codex-rs/hepta-intelligence-eval/src/signed_admission.rs",
                "state": "source_consumer_bound_public_facade_implemented",
                "authority": "deny_all",
                "tests": [
                    "codex-rs/hepta-intelligence-eval/src/signed_admission.rs",
                    "codex-rs/hepta-agentd/src/intelligence_evaluation_tests.rs",
                    "codex-rs/hepta-intelligence/src/plasticity_product_tests.rs",
                ],
                "sourcePathExists": True,
                "designOperation": "consumer_bound_signed_evaluation_admission",
                "mappingClass": "owner_native",
                "delegatedCallees": [
                    {
                        "path": "codex-rs/hepta-intelligence-eval/src/signed_evaluation.rs",
                        "symbol": "decide_with_signed_evidence_v2",
                    }
                ],
            }
        )
    callers = data.setdefault("productCallers", [])
    additions = [
        {
            "sourcePath": "codex-rs/hepta-agentd/src/intelligence_evaluation.rs",
            "nativeSymbol": "AgentdEvaluationSessionV1::evaluate",
            "state": "consumer_bound_signed_admission",
        },
        {
            "sourcePath": "codex-rs/hepta-intelligence/src/plasticity_product.rs",
            "nativeSymbol": "propose_authenticated_parameter_plasticity_v1",
            "state": "consumer_bound_signed_admission",
        },
    ]
    known = {(item.get("sourcePath"), item.get("nativeSymbol")) for item in callers}
    for item in additions:
        key = (item["sourcePath"], item["nativeSymbol"])
        if key not in known:
            callers.append(item)
    boundary = data.setdefault("claimBoundary", {})
    boundary["lowLevelSignedDecisionApiPrivate"] = True
    boundary["externalDirectDecisionCallers"] = 0
    data["callerInventorySemantics"] = (
        "All repository-controlled cross-crate consumers use sealed high-level admission or product qualification receipts; low-level V2/V3 decision primitives are owner-crate private."
    )
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main() -> None:
    patch_sources()
    patch_private_api_verifier()
    patch_workflow_and_fixture()
    patch_docs()
    patch_implementation_map()


if __name__ == "__main__":
    main()
