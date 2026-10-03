//! Recompute the original G plan and its actual public numeric inputs.
use crate::AuthenticatedPairedRegistrationV1;
use crate::PairedReviewSourcePlanV1;
use crate::PairedSupervisedPlanV1;
use crate::fixed_paired_generator_host::measured_contract;
use crate::initial_neuron_operational_source::HostResult;
use crate::initial_neuron_operational_source::Source;
use crate::paired_development_transport::Response;
use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_learning_ledger::ReviewTrustWireV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde_json::Value;
use std::collections::BTreeMap;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Publication {
    schema: String,
    original_source_digest: String,
    original_input_contract_digest: String,
    plan_inputs_hex: String,
    measurements: Vec<Value>,
    generator_evidence: ReviewEvidenceWireV1,
    generator_uid: u32,
    generator_gid: u32,
    generator_cgroup: String,
    trust: ReviewTrustWireV1,
    qualified: bool,
    final_holdout_consumed: bool,
    authority_grants_any: bool,
    production_activation: bool,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Measurement {
    source_record_digest: String,
    candidate_input_hex: String,
    baseline_input_hex: String,
    physical_response: Response,
}
pub(super) struct Inputs {
    pub original_contract: Digest32,
    pub source: PairedReviewSourcePlanV1,
    pub plan: PairedSupervisedPlanV1,
    pub generator: SignedLearningEvidenceV1,
    pub trust_wire: ReviewTrustWireV1,
    pub rows: BTreeMap<Digest32, [Vec<u8>; 2]>,
}
impl Inputs {
    pub fn read(pinned: &Source, trust: &ActivatedLearningTrustV1, now: u64) -> HostResult<Self> {
        let publication: Publication = serde_json::from_slice(&pinned.read(128 * 1024 * 1024)?)?;
        let source = PairedReviewSourcePlanV1::decode(&decode(&publication.plan_inputs_hex)?)?;
        let plan = source.freeze()?;
        let generator = publication.generator_evidence.native()?;
        trust.verifier().verify(
            LearningEvidenceRoleV1::Generator,
            &generator,
            plan.frozen_plan().plan_digest.as_array(),
            now,
        )?;
        if publication.schema != "hepta.eval.paired-supervised.public-generator-source.v1"
            || publication
                .original_source_digest
                .parse::<Digest32>()?
                .is_zero()
            || publication.generator_uid == 0
            || publication.generator_gid == 0
            || !publication
                .generator_cgroup
                .starts_with("0::/system.slice/hepta-native-generator-")
            || publication.qualified
            || publication.final_holdout_consumed
            || publication.authority_grants_any
            || publication.production_activation
            || publication.measurements.len() != source.tasks.len()
            || publication.trust.scope_digest != trust.verifier().scope_digest().to_string()
            || publication.trust.objective_digest != trust.verifier().objective_digest().to_string()
            || measured_contract(
                publication.original_input_contract_digest.parse()?,
                &serde_json::to_vec(&publication.measurements)?,
            ) != source.runtime.task_input_contract_digest
        {
            return Err("original actual G plan/measurement contract".into());
        }
        // The root signature and every native field are checked independently,
        // not inferred from G's descriptive UID or output success fields.
        let (root, distribution) = publication.trust.native()?;
        let original =
            codex_hepta_learning_ledger::activate_learning_trust(&root, distribution, None, now)?;
        if original.distribution_digest() != trust.distribution_digest() {
            return Err("G publication differs from original admitted distribution".into());
        }
        let mut rows = BTreeMap::new();
        for raw in &publication.measurements {
            let row: Measurement = serde_json::from_value(raw.clone())?;
            let id = row.source_record_digest.parse()?;
            let task = source
                .tasks
                .iter()
                .find(|task| task.source_record_digest == id)
                .ok_or("G row absent from original task graph")?;
            let pair = [
                decode(&row.candidate_input_hex)?,
                decode(&row.baseline_input_hex)?,
            ];
            if [Digest32::of_bytes(&pair[0]), Digest32::of_bytes(&pair[1])]
                != [task.candidate_input_digest, task.baseline_input_digest]
                || rows.insert(id, pair).is_some()
                || row.physical_response.source_row_sha256 != id.to_string()
                || row.physical_response.features_q24.len() != 512
            {
                return Err("G source/numeric input identity or complete coverage".into());
            }
            for (input, request) in rows
                .get(&id)
                .ok_or("G row")?
                .iter()
                .zip([&task.candidate_request_id, &task.baseline_request_id])
            {
                let parsed: Value = serde_json::from_slice(input)?;
                if parsed["request_id"] != request.as_str()
                    || parsed["feature_vector_q24"]
                        != serde_json::to_value(&row.physical_response.features_q24)?
                    || parsed["expected_output_width"] != 10
                    || !input.ends_with(b"\n")
                    || input.len() > 16 * 1024
                {
                    return Err("G exact original numeric input".into());
                }
            }
        }
        Ok(Self {
            original_contract: publication.original_input_contract_digest.parse()?,
            source,
            plan,
            generator,
            trust_wire: publication.trust,
            rows,
        })
    }
    pub fn verify_registration(
        &self,
        registration: &AuthenticatedPairedRegistrationV1,
    ) -> HostResult<()> {
        if registration.plan != self.plan || registration.generator_evidence != self.generator {
            return Err("original O registration differs from G plan".into());
        }
        Ok(())
    }
}
pub(super) fn decode(text: &str) -> HostResult<Vec<u8>> {
    if text.len() > 64 * 1024 * 1024 {
        return Err("bounded original G wire".into());
    }
    codex_hepta_learning_ledger::decode_review_payload_hex(text)
}
