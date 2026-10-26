//! Prepare/sign/execute local research admission. The private reviewer key is
//! external to this binary; its public key is pinned by the frozen protocol.

use crate::report::Inputs;
use crate::report::hash;
use crate::report::read;
use crate::report::string;
use crate::*;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

pub fn unhex(value: &str) -> Result<Vec<u8>> {
    ensure(
        value.is_ascii() && value.len().is_multiple_of(2) && value.len() <= 32768,
        "bounded hex required",
    )?;
    (0..value.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&value[i..i + 2], 16).map_err(Into::into))
        .collect()
}

fn evidence(
    protocol: &Value,
    inputs: &Inputs,
    gate: &Value,
    replay: &Path,
    statistics: &Path,
    conversion: &Path,
) -> Result<[Digest32; 3]> {
    let policy = &protocol["native_research_review"];
    ensure(
        policy["scope"] == "local-research-only"
            && policy["authority_epoch"] == 1
            && policy["signed_proposal_validity_seconds"] == 900
            && policy["required_audits"] == json!(["independent_replay", "independent_statistics"]),
        "review policy not installed",
    )?;
    let mut hashes = [Digest32::ZERO; 3];
    for (index, (path, kind)) in [
        (replay, "independent_replay"),
        (statistics, "independent_statistics"),
    ]
    .iter()
    .enumerate()
    {
        let bytes = read(path)?;
        let audit: Value = serde_json::from_slice(&bytes)?;
        hashes[index] = Digest32::of_bytes(&bytes);
        ensure(
            hashes[index] == hash(gate, &format!("{kind}_sha256"))?
                && audit["schema"] == "hepta.independent-research-audit.v1"
                && audit["kind"] == *kind
                && audit["all_checks_passed"] == true
                && audit["production_authority"] == false
                && hash(&audit, "protocol_sha256")? == inputs.policy.protocol_digest
                && hash(&audit, "report_sha256")? == inputs.report_digest
                && hash(&audit, "source_candidate_bundle_sha256")?
                    == hash(gate, "source_candidate_bundle_sha256")?,
            "independent audit scope or binding differs",
        )?;
    }
    hashes[2] = Digest32::of_bytes(&read(conversion)?);
    ensure(
        hashes[2] == hash(gate, "conversion_manifest_sha256")?,
        "conversion commitment changed",
    )?;
    Ok(hashes)
}

fn review(
    protocol: &Value,
    inputs: &Inputs,
    request: &LearningArtifactPublishRequestV1,
    issued: u64,
) -> Result<SignedScientificCandidateReviewV1> {
    Ok(SignedScientificCandidateReviewV1 {
        reviewer_id: owner::id(string(&protocol["native_research_review"], "reviewer_id")?)?,
        operation_id: request.operation_id.clone(),
        authority_epoch: 1,
        policy_digest: inputs.policy.digest(),
        admission_digest: request.admission.admission_digest,
        expected_registry_predecessor_head: request.expected_registry_predecessor_head,
        report_digest: inputs.report_digest,
        task: inputs.measurements[0].clone(),
        retention: inputs.measurements[1].clone(),
        total_cost: inputs.measurements[2].clone(),
        issued_at: issued,
        expires_at: issued + 900,
        signature: [0; 64],
    })
}

fn proposal(
    protocol: &Value,
    inputs: &Inputs,
    audits: [Digest32; 3],
    review: &SignedScientificCandidateReviewV1,
) -> Value {
    json!({"schema":"hepta.native-scientific-signing-proposal.v7","scope":"local-research-only",
        "issued_at":review.issued_at,"expires_at":review.expires_at,"reviewer_id":review.reviewer_id.as_str(),
        "reviewer_public_key_hex":protocol["native_research_review"]["ed25519_public_key_hex"],
        "protocol_sha256":inputs.policy.protocol_digest.to_string(),"report_sha256":inputs.report_digest.to_string(),
        "gate_input_sha256":inputs.gate_digest.to_string(),"candidate_sha256":Digest32::of_bytes(&inputs.candidate).to_string(),
        "predecessor_sha256":Digest32::of_bytes(&inputs.predecessor).to_string(),"conversion_manifest_sha256":audits[2].to_string(),
        "independent_replay_sha256":audits[0].to_string(),"independent_statistics_sha256":audits[1].to_string(),
        "operation_id":review.operation_id.as_str(),"admission_sha256":review.admission_digest.to_string(),"policy_sha256":review.policy_digest.to_string(),
        "review_signing_bytes_hex":owner::hex(&review.signing_bytes()),"review_signing_bytes_sha256":Digest32::of_bytes(&review.signing_bytes()).to_string(),
        "measurements":inputs.aggregate,"all_numeric_gates_pass":true,"production_authority":false,
        "reviewer_instruction":"Independently check the bound detailed replay/statistical evidence and actual scientific verdict before signing these exact native V1 bytes. This is local research trust, not external certification or production approval."})
}

pub fn run(
    mode: &str,
    protocol: &Value,
    inputs: &Inputs,
    gate: &Value,
    paths: [&Path; 4],
    output: &Path,
    signature_path: Option<&Path>,
) -> Result<Value> {
    ensure(
        inputs.all_numeric_gates_pass,
        "positive prepare/execute requires every frozen numerical, census and completion gate",
    )?;
    let [replay, statistics, conversion, parity_root] = paths;
    let audits = evidence(protocol, inputs, gate, replay, statistics, conversion)?;
    terminal_review::verify(inputs, gate, conversion, replay, statistics)?;
    let parity_inputs = parity::Inputs::load(parity_root)?;
    parity_inputs.verify_family(&inputs.policy.protocol_digest.to_string(), report::TASKS)?;
    ensure(
        parity_inputs.payloads == handoff_pair::serving_payloads(inputs)?,
        "parity input payload differs",
    )?;
    let preflight = [
        parity::compare_unpublished(&parity_inputs, 0)?,
        parity::compare_unpublished(&parity_inputs, 1)?,
    ];
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    if mode == "prepare" {
        ensure(signature_path.is_none(), "prepare cannot carry a signature")?;
        fs::create_dir(output)?;
        let context = positive_owner::open(
            inputs,
            audits,
            &output.join("owner"),
            now,
            positive_owner::Mode::Prepare,
        )?;
        let review = review(protocol, inputs, &context.request, now)?;
        let result = proposal(protocol, inputs, audits, &review);
        fs::write(
            output.join("proposal.json"),
            serde_json::to_vec_pretty(&result)?,
        )?;
        fs::write(
            output.join("preflight-parity.json"),
            serde_json::to_vec_pretty(&preflight)?,
        )?;
        ensure(
            context.owner.registry().records().len() == 1,
            "prepare published candidate",
        )?;
        return Ok(
            json!({"status":"awaiting_independent_research_signature","proposal_sha256":Digest32::of_bytes(&read(&output.join("proposal.json"))?).to_string(),"candidate_published":false,"production_authority":false}),
        );
    }
    ensure(mode == "execute", "unknown positive mode")?;
    let proposal_bytes = read(&output.join("proposal.json"))?;
    let prepared: Value = serde_json::from_slice(&proposal_bytes)?;
    let signature: Value =
        serde_json::from_slice(&read(signature_path.ok_or("signature receipt required")?)?)?;
    ensure(
        hash(&signature, "proposal_sha256")? == Digest32::of_bytes(&proposal_bytes),
        "signature names different proposal",
    )?;
    let public: [u8; 32] = unhex(string(
        &protocol["native_research_review"],
        "ed25519_public_key_hex",
    )?)?
    .try_into()
    .map_err(|_| "32-byte reviewer key required")?;
    let signature: [u8; 64] = unhex(string(&signature, "signature_hex")?)?
        .try_into()
        .map_err(|_| "64-byte Ed25519 signature required")?;
    let signing_bytes = unhex(string(&prepared, "review_signing_bytes_hex")?)?;
    VerifyingKey::from_bytes(&public)?
        .verify_strict(&signing_bytes, &Signature::from_bytes(&signature))?;
    let issued = prepared["issued_at"]
        .as_u64()
        .ok_or("proposal timestamp missing")?;
    ensure(
        issued <= now && now - issued <= 900,
        "review proposal expired or issued in future",
    )?;
    let context = positive_owner::open(
        inputs,
        audits,
        &output.join("owner"),
        issued,
        positive_owner::Mode::Execute,
    )?;
    let mut review = review(protocol, inputs, &context.request, issued)?;
    ensure(
        prepared == proposal(protocol, inputs, audits, &review)
            && signing_bytes == review.signing_bytes(),
        "prepared proposal differs from independently revalidated inputs",
    )?;
    review.signature = signature;
    let trust = TrustedArtifactSignerV1 {
        signer_id: review.reviewer_id.clone(),
        verifying_key: public,
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 1,
        valid_from: issued,
        expires_at: issued + 900,
        revoked_at: None,
    };
    let required_head = context.request.signed_current_head.clone();
    let mut publisher =
        ScientificCandidatePublisherV1::new(context.owner, inputs.policy.clone(), trust)?;
    let receipt = publisher.publish(
        context.request,
        ScientificReviewEvidenceV1::Signed(Box::new(review)),
    )?;
    ensure(
        !receipt.publication.authority.grants_any(),
        "research publication gained authority",
    )?;
    drop(publisher);
    let roundtrip = if inputs.candidate.starts_with(b"HPTHOF07") {
        serve_handoff::roundtrip
    } else {
        serve::roundtrip
    };
    let served = roundtrip(
        context.config,
        required_head,
        context.baseline,
        context.candidate,
        &parity_inputs,
        now,
    )?;
    let result = json!({"schema":"hepta.signed-research-native-publication.v7","status":"completed","scope":"local-research-only",
        "proposal_sha256":Digest32::of_bytes(&proposal_bytes).to_string(),"review_sha256":receipt.review_digest.to_string(),
        "policy_sha256":receipt.policy_digest.to_string(),"registry_head_sha256":receipt.publication.registry_head_digest.to_string(),
        "candidate_published":true,"all_numeric_gates_pass":true,"independent_research_signature_verified":true,
        "roundtrip":served,"preflight_parity":preflight,"production_authority":false,"production_activation":false});
    fs::write(
        output.join("publication.json"),
        serde_json::to_vec_pretty(&result)?,
    )?;
    Ok(result)
}

#[cfg(test)]
#[path = "positive_tests.rs"]
mod tests;
