//! Test-control serialization of already held original Material constructor
//! inputs. The parent verifier, scope and exact freeze predate the report.
//! This is not a production authority format or a way to reconstruct an owner.

use super::*;
use crate::OriginalCellQ24MaterialReceiptConfigV1 as Material;
use crate::learning_iteration_checkpoint::decode_original_owner_snapshot_v1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use serde::Deserialize;
use serde::Serialize;

const PURPOSE: &str = "hepta.fixture.original-material-control.v1";
const CONTROL_LIMIT: usize = 64 * 1024;
const SNAPSHOT_LIMIT: usize = 8192;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Freeze {
    evidence_id: String,
    principal_id: String,
    role: String,
    trust: String,
    scope: String,
    objective: String,
    authority_epoch: u64,
    issued_at: u64,
    expires_at: u64,
    payload_digest: String,
    signature: String,
}

impl Freeze {
    fn from_original(original: &SignedLearningEvidenceV1) -> anyhow::Result<Self> {
        anyhow::ensure!(
            original.role == LearningEvidenceRoleV1::Evaluator,
            "the original Material freeze is an Evaluator signature"
        );
        Ok(Self {
            evidence_id: original.evidence_id.to_string(),
            principal_id: original.principal_id.to_string(),
            role: "evaluator".into(),
            trust: original.trust_digest.to_string(),
            scope: original.scope_digest.to_string(),
            objective: original.objective_digest.to_string(),
            authority_epoch: original.authority_epoch,
            issued_at: original.issued_at,
            expires_at: original.expires_at,
            payload_digest: original.payload_digest.to_string(),
            signature: STANDARD_NO_PAD.encode(original.signature),
        })
    }

    fn original(&self) -> anyhow::Result<SignedLearningEvidenceV1> {
        anyhow::ensure!(self.role == "evaluator", "fixed original freeze purpose");
        let signature = STANDARD_NO_PAD.decode(&self.signature)?;
        anyhow::ensure!(
            signature.len() == 64 && STANDARD_NO_PAD.encode(&signature) == self.signature,
            "complete canonical original signature"
        );
        let signature: [u8; 64] = signature
            .try_into()
            .map_err(|_| anyhow::anyhow!("complete original signature"))?;
        Ok(SignedLearningEvidenceV1 {
            evidence_id: StableId::new(self.evidence_id.as_str())?,
            principal_id: StableId::new(self.principal_id.as_str())?,
            role: LearningEvidenceRoleV1::Evaluator,
            trust_digest: self.trust.parse()?,
            scope_digest: self.scope.parse()?,
            objective_digest: self.objective.parse()?,
            authority_epoch: self.authority_epoch,
            issued_at: self.issued_at,
            expires_at: self.expires_at,
            payload_digest: self.payload_digest.parse()?,
            signature,
        })
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Report {
    purpose: String,
    snapshot: String,
    update_scope: String,
    update_rule: String,
    scope_binding: String,
    head: String,
    head_index: u16,
    unit: String,
    freeze_snapshot_id: String,
    freeze_objective: String,
    freeze_policy: String,
    freeze: Freeze,
    freeze_payload: String,
    experience_actor: String,
    dataset_actor: String,
    maximum_signature_lifetime_seconds: u64,
}

/// A private, parent-held comparison capability. It contains the complete
/// original typed inputs, not a trust digest learned from a child. No method
/// opens a LedgerWriter, source, witness, role channel, signer or Root store.
pub(super) struct ParentMaterialControl {
    original: Material,
    trust: LearningEvidenceTrustV1,
    inputs: material::OriginalMaterialConstructorInputs,
}

impl ParentMaterialControl {
    pub(super) fn from_original(
        original: &Material,
        original_trust: &LearningEvidenceTrustV1,
        inputs: &material::OriginalMaterialConstructorInputs,
    ) -> anyhow::Result<Self> {
        // Only the caller's already trusted full state constructs this verifier.
        // The Report schema deliberately contains no signer list or trust input.
        let verifier = LearningEvidenceVerifierV1::new(original_trust.clone())?;
        anyhow::ensure!(
            verifier.trust_digest() == original.verifier.trust_digest()
                && verifier.scope_digest() == original.verifier.scope_digest()
                && verifier.objective_digest() == original.verifier.objective_digest()
                && verifier.authority_epoch() == original.verifier.authority_epoch(),
            "the independently held host trust is the exact original trust"
        );
        let scope = FrozenLearningScopeV2::freeze(
            &original.initial.request,
            &original.initial.owners,
            inputs.update_scope,
            inputs.update_rule,
        )?;
        anyhow::ensure!(
            scope == original.scope,
            "same original scope, components and rule"
        );
        let mut original = original.clone();
        original.verifier = verifier;
        let held = Self {
            original,
            trust: original_trust.clone(),
            inputs: inputs.clone(),
        };
        held.require_current_inputs()?;
        Ok(held)
    }

    fn require_current_inputs(&self) -> anyhow::Result<()> {
        let at = now()?;
        let verifier = LearningEvidenceVerifierV1::new(self.trust.clone())?;
        anyhow::ensure!(verifier.trust_digest() == self.original.verifier.trust_digest());
        for signer in [
            &self.original.experience_signer,
            &self.original.dataset_signer,
        ] {
            verifier.require_signer_binding(LearningEvidenceRoleV1::Observer, signer, at)?;
        }
        verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &self.original.freeze_evidence,
            &self.inputs.freeze_payload,
            at,
        )?;
        let _ = Material::require_original_command_initial(&self.original)?;
        let initial = LearningIterationCoordinatorV1::new(
            self.original.initial.request.clone(),
            self.original.initial.owners.clone(),
        )?;
        anyhow::ensure!(
            initial.snapshot() == &self.original.initial
                && self.original.initial.receipts.is_empty(),
            "no completed stage imported as initial"
        );
        Ok(())
    }

    fn report(&self) -> anyhow::Result<Report> {
        let snapshot = encode_original_owner_snapshot_v1(&self.original.initial)?;
        anyhow::ensure!(
            snapshot.len() <= SNAPSHOT_LIMIT,
            "the original 8 KiB snapshot limit"
        );
        let (head, head_index) = match self.original.rule.head {
            crate::CellQ24PrivateHeadV1::Drive { index } => ("drive", index),
            crate::CellQ24PrivateHeadV1::Prediction { index } => ("prediction", index),
        };
        let update_scope = match self.inputs.update_scope {
            LearningUpdateScopeV2::Cell => "cell",
            LearningUpdateScopeV2::Organ => "organ",
            LearningUpdateScopeV2::BaseRelease => {
                anyhow::bail!("no base-release fixture authority")
            }
        };
        Ok(Report {
            purpose: PURPOSE.into(),
            snapshot: STANDARD_NO_PAD.encode(snapshot),
            update_scope: update_scope.into(),
            update_rule: self.inputs.update_rule.to_string(),
            scope_binding: self.original.scope.binding().to_string(),
            head: head.into(),
            head_index,
            unit: self.original.rule.unit_profile_digest.to_string(),
            freeze_snapshot_id: self.original.freeze_plan.snapshot_id.to_string(),
            freeze_objective: self.original.freeze_plan.objective_digest.to_string(),
            freeze_policy: self
                .original
                .freeze_plan
                .inclusion_policy_digest
                .to_string(),
            freeze: Freeze::from_original(&self.original.freeze_evidence)?,
            freeze_payload: STANDARD_NO_PAD.encode(&self.inputs.freeze_payload),
            experience_actor: self
                .original
                .experience_signer
                .principal
                .principal_id
                .to_string(),
            dataset_actor: self
                .original
                .dataset_signer
                .principal
                .principal_id
                .to_string(),
            maximum_signature_lifetime_seconds: self.original.maximum_signature_lifetime_seconds,
        })
    }

    pub(super) fn encode_original(&self) -> anyhow::Result<Vec<u8>> {
        self.require_current_inputs()?;
        let bytes = serde_json::to_vec(&self.report()?)?;
        anyhow::ensure!(
            !bytes.is_empty() && bytes.len() <= CONTROL_LIMIT,
            "one bounded original test-control datagram"
        );
        Ok(bytes)
    }

    pub(super) fn decode_report(&self, bytes: &[u8]) -> anyhow::Result<Material> {
        anyhow::ensure!(
            !bytes.is_empty() && bytes.len() <= CONTROL_LIMIT,
            "one bounded original test-control datagram"
        );
        let report: Report = serde_json::from_slice(bytes)?;
        anyhow::ensure!(
            report.purpose == PURPOSE && serde_json::to_vec(&report)? == bytes,
            "exact purpose and canonical full report, without trailing bytes"
        );
        // Pin every original constructor input. This deliberately rejects an
        // otherwise valid newly signed or renewed freeze as a different input.
        anyhow::ensure!(
            self.encode_original()? == bytes,
            "unchanged pre-held original constructor inputs"
        );
        let snapshot = STANDARD_NO_PAD.decode(&report.snapshot)?;
        anyhow::ensure!(
            snapshot.len() <= SNAPSHOT_LIMIT
                && STANDARD_NO_PAD.encode(&snapshot) == report.snapshot,
            "original canonical snapshot bytes"
        );
        let initial = decode_original_owner_snapshot_v1(&snapshot)?;
        anyhow::ensure!(
            initial == self.original.initial
                && encode_original_owner_snapshot_v1(&initial)? == snapshot,
            "full original request, seven owner IDs, envelope, budgets and empty cut"
        );
        let scope = FrozenLearningScopeV2::freeze(
            &initial.request,
            &initial.owners,
            self.inputs.update_scope,
            self.inputs.update_rule,
        )?;
        anyhow::ensure!(
            scope == self.original.scope && scope.binding().to_string() == report.scope_binding,
            "the original frozen scope"
        );
        let freeze_evidence = report.freeze.original()?;
        anyhow::ensure!(
            freeze_evidence == self.original.freeze_evidence,
            "all original freeze fields and signature, without renewal"
        );
        let freeze_payload = STANDARD_NO_PAD.decode(&report.freeze_payload)?;
        anyhow::ensure!(
            freeze_payload == self.inputs.freeze_payload
                && STANDARD_NO_PAD.encode(&freeze_payload) == report.freeze_payload,
            "the same original signed ledger freeze payload"
        );
        // No decoded metadata chooses signers, root trust, dataset rule or plan.
        let verifier = LearningEvidenceVerifierV1::new(self.trust.clone())?;
        verifier.verify(
            LearningEvidenceRoleV1::Evaluator,
            &freeze_evidence,
            &freeze_payload,
            now()?,
        )?;
        let decoded = Material {
            initial,
            scope,
            freeze_evidence,
            verifier,
            ..self.original.clone()
        };
        anyhow::ensure!(
            Material::require_original_command_initial(&decoded)?.0
                == Material::require_original_command_initial(&self.original)?.0,
            "exact original Material command binding"
        );
        self.require_current_inputs()?;
        Ok(decoded)
    }
}

fn canonical_report(value: &serde_json::Value) -> anyhow::Result<Vec<u8>> {
    let report: Report = serde_json::from_value(value.clone())?;
    Ok(serde_json::to_vec(&report)?)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn fresh_original_material_control_preserves_complete_inputs_and_rejects_substitution()
-> anyhow::Result<()> {
    use super::super::evaluation_provider::fresh_training::PreparedBPanel;
    use super::original_material::ProviderAdmission;
    use super::original_material::UnstartedProvider;
    let admission = ProviderAdmission::new().await?;
    // This is actual original fixture trust, held before the child-report codec
    // is constructed. It does not use a decoded digest to select a signer set.
    let (_, _, expected_trust) =
        material::original_fixture_trust_at(admission.objective, admission.trust_time)?;
    let panel = PreparedBPanel::new(admission.objective, admission.trust_time)?;
    let fixture = Box::pin(UnstartedProvider::new(
        admission,
        panel.registration().evaluation_profile(),
    ))
    .await?;
    let result: anyhow::Result<()> = (|| {
        anyhow::ensure!(fixture.original_trust == expected_trust);
        let before = fixture.original_bytes()?;
        let held = ParentMaterialControl::from_original(
            &fixture.material,
            &expected_trust,
            &fixture.original_material_inputs,
        )?;
        let raw = held.encode_original()?;
        let decoded = held.decode_report(&raw)?;
        anyhow::ensure!(decoded.initial == fixture.material.initial);
        anyhow::ensure!(decoded.scope == fixture.material.scope);
        anyhow::ensure!(decoded.rule == fixture.material.rule);
        anyhow::ensure!(decoded.freeze_evidence == fixture.material.freeze_evidence);
        anyhow::ensure!(
            decoded.experience_signer == fixture.material.experience_signer
                && decoded.dataset_signer == fixture.material.dataset_signer
        );
        anyhow::ensure!(
            ParentMaterialControl::from_original(
                &decoded,
                &expected_trust,
                &fixture.original_material_inputs
            )?
            .encode_original()?
                == raw
        );

        let base: serde_json::Value = serde_json::from_slice(&raw)?;
        for key in [
            "purpose",
            "update_scope",
            "update_rule",
            "scope_binding",
            "head",
            "unit",
            "freeze_snapshot_id",
            "freeze_objective",
            "freeze_policy",
            "experience_actor",
            "dataset_actor",
        ] {
            let mut altered = base.clone();
            altered[key] = serde_json::json!("not-the-original-input");
            anyhow::ensure!(
                held.decode_report(&canonical_report(&altered)?).is_err(),
                "{key}"
            );
        }
        for key in ["head_index", "maximum_signature_lifetime_seconds"] {
            let mut altered = base.clone();
            altered[key] = serde_json::json!(u16::MAX);
            anyhow::ensure!(
                held.decode_report(&canonical_report(&altered)?).is_err(),
                "{key}"
            );
        }
        for key in [
            "evidence_id",
            "principal_id",
            "role",
            "trust",
            "scope",
            "objective",
            "payload_digest",
            "signature",
        ] {
            let mut altered = base.clone();
            altered["freeze"][key] = serde_json::json!("replacement");
            anyhow::ensure!(
                held.decode_report(&canonical_report(&altered)?).is_err(),
                "freeze {key}"
            );
        }
        for key in ["authority_epoch", "issued_at", "expires_at"] {
            let mut altered = base.clone();
            altered["freeze"][key] = serde_json::json!(u64::MAX);
            anyhow::ensure!(
                held.decode_report(&canonical_report(&altered)?).is_err(),
                "freeze {key}"
            );
        }
        let mut alternate = fixture.material.initial.clone();
        alternate.request.budget.maximum_training_steps += 1;
        let alternate = LearningIterationCoordinatorV1::new(alternate.request, alternate.owners)?;
        let mut altered = base.clone();
        altered["snapshot"] = serde_json::json!(
            STANDARD_NO_PAD.encode(encode_original_owner_snapshot_v1(alternate.snapshot())?)
        );
        anyhow::ensure!(
            held.decode_report(&canonical_report(&altered)?).is_err(),
            "valid different request cannot replace the original complete snapshot"
        );
        let mut oversized = base.clone();
        oversized["snapshot"] =
            serde_json::json!(STANDARD_NO_PAD.encode(vec![0_u8; SNAPSHOT_LIMIT + 1]));
        anyhow::ensure!(held.decode_report(&canonical_report(&oversized)?).is_err());
        let mut extra = base.clone();
        extra["host_trust"] = serde_json::json!({"digest": "claim"});
        anyhow::ensure!(
            held.decode_report(&serde_json::to_vec(&extra)?).is_err(),
            "report cannot add host trust"
        );
        let mut changed_freeze_payload = fixture.original_material_inputs.freeze_payload.clone();
        changed_freeze_payload.push(0);
        let mut changed_payload = base.clone();
        changed_payload["freeze_payload"] =
            serde_json::json!(STANDARD_NO_PAD.encode(changed_freeze_payload));
        anyhow::ensure!(
            held.decode_report(&canonical_report(&changed_payload)?)
                .is_err()
        );
        let mut trailing = raw.clone();
        trailing.push(b' ');
        anyhow::ensure!(held.decode_report(&trailing).is_err());
        anyhow::ensure!(held.decode_report(&vec![0_u8; CONTROL_LIMIT + 1]).is_err());
        let mut wrong_trust = expected_trust.clone();
        wrong_trust.signers[0].controller_id = id("changed-original-controller");
        anyhow::ensure!(
            ParentMaterialControl::from_original(
                &fixture.material,
                &wrong_trust,
                &fixture.original_material_inputs
            )
            .is_err(),
            "complete host trust, not only key equality"
        );
        let mut invalid_signature = fixture.material.clone();
        invalid_signature.freeze_evidence.signature[0] ^= 1;
        anyhow::ensure!(
            ParentMaterialControl::from_original(
                &invalid_signature,
                &expected_trust,
                &fixture.original_material_inputs
            )
            .is_err(),
            "original verifier rejects a full-length changed signature"
        );
        let mut wrong_inputs = fixture.original_material_inputs.clone();
        wrong_inputs.update_rule = d("not-the-original-update-rule");
        anyhow::ensure!(
            ParentMaterialControl::from_original(&fixture.material, &expected_trust, &wrong_inputs)
                .is_err()
        );
        wrong_inputs = fixture.original_material_inputs.clone();
        wrong_inputs.freeze_payload.push(0);
        anyhow::ensure!(
            ParentMaterialControl::from_original(&fixture.material, &expected_trust, &wrong_inputs)
                .is_err(),
            "original full signed freeze payload"
        );
        anyhow::ensure!(
            fixture.original_bytes()? == before,
            "codec performs no owner I/O or mutation"
        );
        Ok(())
    })();
    drop(panel);
    let cleanup = fixture.finish().await;
    match (result, cleanup) {
        (Ok(()), Ok(_)) => Ok(()),
        (Err(error), cleanup) => {
            Err(error.context(format!("original fixture cleanup: {cleanup:?}")))
        }
        (Ok(()), Err(error)) => Err(error),
    }
}
