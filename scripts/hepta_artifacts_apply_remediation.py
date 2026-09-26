#!/usr/bin/env python3
"""One-shot, preimage-checked remediation on the explicitly authorized branch."""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/learning-artifacts-remediation-20260927"
BASE = "a126987b84737dbc2ee2592442a314117bddb4a2"
CRATE = "codex-rs/hepta-learning-artifacts/src/"


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError("ambiguous or missing patch preimage: " + old[:100])
    return text.replace(old, new, 1)


def read_exact(path, expected):
    data = (ROOT / path).read_bytes()
    actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if actual != expected:
        raise ValueError("source changed: " + path)
    return data.decode()


def apply():
    if git("branch", "--show-current") != BRANCH:
        raise ValueError("refusing to edit any other branch")
    subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", BASE, "HEAD"], check=True)
    closure_path = "scripts/hepta-lane-e-closure.py"
    closure = read_exact(closure_path, "a68f55a8d1dffbe6381e37a5206e23334c1739a7")
    # Preserve every semantic gate. Only remove mutually inconsistent old pins.
    closure = replace_once(closure, '"cargo-llvm-cov@0.9.1"', '"cargo-llvm-cov@0.9.0"')
    closure = replace_once(closure, '"actions/attest-build-provenance@0f67c3f4856b2e3261c31976d6725780e5e4c373"', '"actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8"')

    service_path = CRATE + "owner_service.rs"
    service = read_exact(service_path, "1427589355efa2ea3ac12cc076d0e9a028b29f0b")
    service = replace_once(service, 'use std::error::Error as StdError;', '#[path = "owner/publication_recovery.rs"]\nmod publication_recovery;\nuse publication_recovery::*;\n\nuse std::error::Error as StdError;')
    service = replace_once(service, '        let operation_id = request.operation_id.clone();', '        validate_request_identity(&request)?;\n        let operation_id = request.operation_id.clone();')
    service = replace_once(service, '''            Err(error) => {
                if let Some(recovery) = self.host.recover_publication(&operation_id)?
                    && recovery.checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged
                {
                    self.recovery_required = Some(operation_id);
                }
                Err(error)
            }''', '''            Err(error) => {
                // Poison first: an unreadable checkpoint must not reopen admission.
                self.recovery_required = Some(operation_id.clone());
                match self.host.recover_publication(&operation_id) {
                    Ok(Some(recovery))
                        if recovery.checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged => {}
                    Ok(_) => self.recovery_required = None,
                    Err(recovery_error) => return Err(recovery_error.into()),
                }
                Err(error)
            }''')
    service = replace_once(service, '''            if recovery.checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged {
                return receipt_from_checkpoint(&recovery.checkpoint);
            }''', '''            let verified = self.host.verify_historical_retry_head(&request.signed_current_head)?;
            if let Some(witness) = recovery.checkpoint.witness_receipt
                && witness.witness_digest != verified
            {
                return Err(LearningArtifactOwnerServiceError::RequestMismatch);
            }
            if recovery.checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged {
                // Historical receipt lookup is not renewed runtime eligibility.
                return receipt_from_checkpoint(&recovery.checkpoint);
            }''')
    service = replace_once(service, '        assert_eq!(retry, receipt);', '''        assert_eq!(retry, receipt);
        for payload in [Vec::new(), b"PAYLOAD".to_vec(), b"payload-extra".to_vec()] {
            let mut drift = request.clone();
            drift.payload = payload;
            assert!(matches!(service.publish(drift), Err(LearningArtifactOwnerServiceError::RequestMismatch)));
            assert_eq!(service.registry().snapshot().head_digest, receipt.registry_head_digest);
        }
        let mut drift = request.clone();
        drift.admission.validated_manifest.manifest.runtime_tuple_digest = digest("changed-runtime");
        assert!(matches!(service.publish(drift), Err(LearningArtifactOwnerServiceError::RequestMismatch)));
        let mut drift = request.clone();
        drift.signed_current_head.signature[0] ^= 1;
        assert!(service.publish(drift).is_err());
        assert_eq!(service.publish(request.clone()).fixture("retry after rejection"), receipt);''')
    begin = service.index("\nfn validate_request_against_checkpoint(")
    end = service.index("\n#[derive(Debug)]\npub enum LearningArtifactOwnerServiceError", begin)
    helpers = service[begin:end]
    helpers = helpers.replace("\nfn ", "\npub(super) fn ").replace("\nconst fn ", "\npub(super) const fn ")
    helpers = '''//! Private publication replay helpers; no additional writer or public authority.
use super::*;

/// Validate all caller-constructible admission fields and bytes even on a
/// terminal retry. Current withdrawal eligibility is checked by new writes;
/// terminal receipts remain historical observations, never activation tokens.
pub(super) fn validate_request_identity(
    request: &LearningArtifactPublishRequestV1,
) -> Result<(), LearningArtifactOwnerServiceError> {
    let admission = &request.admission;
    crate::verify_artifact_admission_v3(
        admission,
        admission.withdrawal_head_digest,
        admission.admitted_at,
    ).map_err(|_| LearningArtifactOwnerServiceError::RequestMismatch)?;
    let manifest = &admission.validated_manifest.manifest;
    if request.now < admission.admitted_at
        || u64::try_from(request.payload.len()).ok() != Some(manifest.encoded_size_bytes)
        || Digest32::of_bytes(&request.payload) != manifest.bytes_digest
    {
        return Err(LearningArtifactOwnerServiceError::RequestMismatch);
    }
    Ok(())
}
''' + helpers
    service = service[:begin] + service[end:]

    host_path = CRATE + "owner_host.rs"
    host = read_exact(host_path, "cdde5193d614f464f4b6b917a2eeffa3e1ee126b")
    host = replace_once(host, 'impl LearningArtifactOwnerHost {\n    pub fn open(', '''impl LearningArtifactOwnerHost {
    /// Authenticate immutable historical retry evidence without renewing it.
    pub(crate) fn verify_historical_retry_head(
        &self,
        signed: &SignedCurrentArtifactHeadV1,
    ) -> Result<Digest32, ArtifactOwnerHostError> {
        let witness = &signed.witness;
        let requirement = RegistryHeadRequirementV1 {
            registry_id: witness.registry_id.clone(),
            minimum_generation: witness.generation,
            expected_predecessor_head_digest: witness.predecessor_head_digest,
            minimum_authority_epoch: witness.authority_epoch,
            now: witness.issued_at,
        };
        Ok(self.verifier.verify_signed_head(signed, &requirement, false)?.witness_digest)
    }

    pub fn open(''')
    paths = {closure_path: closure, service_path: service, host_path: host,
             CRATE + "owner/publication_recovery.rs": helpers}
    for path, content in paths.items():
        (ROOT / path).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / path).write_text(content)
    git("add", "--", *paths)
    return list(paths)


def refresh_map():
    path = "docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json"
    value = json.loads((ROOT / path).read_text())
    tree = git("write-tree")
    for operation in value["operations"]:
        operation["sourceBlob"] = git("rev-parse", tree + ":" + operation["sourcePath"])
    for entry in value["sourceObjects"]:
        entry["object"] = git("rev-parse", tree + ":" + entry["path"])
    value["qualificationState"] = "current_candidate_execution_required"
    value["qualificationWorkflow"] = ".github/workflows/hepta-learning-artifacts-qualification.yml"
    value["completionDimensions"] = {
        "nativeImplementation": "source_candidate",
        "currentHeadQualification": "requires_two_verified_lane_receipts",
        "readComposition": "explicit_host_attachment",
        "writerComposition": "named_service_not_deployed_daemon",
        "targetHostDurability": "external_qualification_required",
        "independentAcceptance": False, "activation": False, "release": False,
    }
    value["repositoryControlledGaps"] = [
        "Run exact-head and ordered-base-merge qualification with no skipped or zero-test receipts.",
        "Complete authenticated production transport and independently provisioned restart/withdrawal frontiers.",
        "Qualify directory-capability hardening, fault injection and key/backup/migration operations on target hosts.",
    ]
    (ROOT / path).write_text(json.dumps(value, indent=2) + "\n")
    git("add", "--", path)


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["refresh-map"]:
        refresh_map()
    elif not sys.argv[1:]:
        print(json.dumps({"changed": apply()}))
    else:
        raise SystemExit("unexpected arguments")
