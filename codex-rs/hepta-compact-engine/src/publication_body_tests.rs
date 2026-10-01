use super::*;

use codex_hepta_cognitive_types::Citation;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use crate::CompactionInputRecordV2;
use crate::CompactionPolicyV2;
use crate::CompactionPublicationRequestV1;
use crate::CompactionSelectedStateV1;
use crate::authenticated::tests::evidence;
use crate::authenticated::tests::fixture;
use crate::authenticated::tests::trust;
use crate::build_qualified_candidate;
use crate::compaction_qualification_payload_v1;
use crate::prove_compaction_with_signed_evidence_v1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn readmit(
    mut request: CompactionPublicationRequestV1,
    host: &mut Host,
) -> CompactionPublicationProposalV1 {
    request.candidate = build_qualified_candidate(
        request.candidate.source_snapshot.clone(),
        request.candidate.checkpoint.generation,
        request.candidate.checkpoint.predecessor_digest,
        &request.policy,
        request.inputs.clone(),
    )
    .unwrap();
    let binding = request.authenticated_proof.source_binding().clone();
    let mut qualification = request.authenticated_proof.qualification().clone();
    qualification.candidate_digest = request.candidate.candidate_digest;
    let payload =
        compaction_qualification_payload_v1(&request.candidate, &binding, &qualification).unwrap();
    request.authenticated_proof = prove_compaction_with_signed_evidence_v1(
        &request.candidate,
        binding,
        qualification,
        &evidence(&host.verifier, &payload),
        &host.verifier,
        /*now*/ 30,
    )
    .unwrap();
    host.policy = request.policy.digest();
    CompactionPublicationProposalV1::new(request, &host.context(/*now*/ 30)).unwrap()
}

#[test]
fn complete_admitted_body_accepts_exact_transport_boundary_and_rejects_one_more_binary_byte() {
    let (original, mut host) = body_fixture(/*records*/ 150, CompactionSelectedStateV1::Empty);
    let mut remaining = MAX_BINARY_BYTES - codec::encode(&original).unwrap().len();
    let mut request = original.request().clone();
    // Protected IDs stay intact. Grow other legal record IDs without changing
    // count/length-prefix widths; each appended byte adds exactly one body byte.
    for input in request.inputs.iter_mut().skip(/*n*/ 2) {
        let additional = remaining.min(128 - input.record.record_id.as_str().len());
        input.record.record_id = id(&format!(
            "{}{}",
            input.record.record_id.as_str(),
            "x".repeat(additional)
        ));
        remaining -= additional;
    }
    assert_eq!(remaining, 0);
    let exact = readmit(request, &mut host);
    let body = exact.encode_restart_body_v1().unwrap();
    assert_eq!(body.len(), MAX_COMPACTION_PUBLICATION_BODY_BYTES_V1);
    let restored =
        restore_compaction_publication_body_v1(&body, &host.context(/*now*/ 40)).unwrap();
    assert_eq!(restored.request().inputs, exact.request().inputs);
    assert_eq!(restored.intent_digest(), exact.intent_digest());
    assert_eq!(restored.encode_restart_body_v1().unwrap(), body);
    let mut oversized = exact.request().clone();
    let input = oversized
        .inputs
        .iter_mut()
        .skip(/*n*/ 2)
        .find(|input| input.record.record_id.as_str().len() < 128)
        .expect("remaining legal ID capacity");
    input.record.record_id = id(&format!("{}x", input.record.record_id.as_str()));
    let oversized = readmit(oversized, &mut host);
    assert_eq!(
        oversized.encode_restart_body_v1(),
        Err(CompactionPublicationBodyError::BodyLimitExceeded)
    );
}

struct Host {
    owner: StableId,
    scope: StableId,
    purpose: StableId,
    selected: CompactionSelectedStateV1,
    policy: Digest32,
    cut: Digest32,
    verifier: LearningEvidenceVerifierV1,
}

impl Host {
    fn context(&self, now: u64) -> CompactionPublicationContextV1<'_> {
        CompactionPublicationContextV1 {
            owner_agent_id: &self.owner,
            scope_id: &self.scope,
            purpose_id: &self.purpose,
            selected: &self.selected,
            policy_generation: Generation::new(/*value*/ 1).unwrap(),
            policy_digest: self.policy,
            source_cut_digest: self.cut,
            verifier: &self.verifier,
            now,
        }
    }
}

fn body_fixture(
    records: usize,
    selected: CompactionSelectedStateV1,
) -> (CompactionPublicationProposalV1, Host) {
    let fixture = fixture();
    let mut inputs = (0..records)
        .map(|index| {
            let mut record = fixture.candidate.retained_records[0].clone();
            record.record_id = id(&format!("memory:{index}"));
            record.citations = vec![
                Citation {
                    source_id: id("source:b"),
                    source_digest: digest("b"),
                },
                Citation {
                    source_id: id("source:a"),
                    source_digest: digest("a"),
                },
            ];
            CompactionInputRecordV2 {
                record,
                retention_priority: index as u32,
                retention_reason_digest: digest(&format!("reason:{index}")),
            }
        })
        .collect::<Vec<_>>();
    inputs.reverse();
    let policy = CompactionPolicyV2 {
        policy_id: id("policy:restart"),
        algorithm_digest: digest("algorithm"),
        compatibility_digest: digest("compatibility"),
        maximum_retained_records: 2,
        protected_record_ids: inputs
            .iter()
            .take(/*n*/ 2)
            .map(|input| input.record.record_id.clone())
            .collect(),
    };
    let mut source = fixture.candidate.source_snapshot;
    let (generation, predecessor) = match selected {
        CompactionSelectedStateV1::Empty => (Generation::new(/*value*/ 1).unwrap(), None),
        CompactionSelectedStateV1::Selected {
            generation,
            checkpoint_digest,
        } => {
            source.vector.compact_checkpoint_generation = generation;
            (
                Generation::new(generation.get() + 1).unwrap(),
                Some(checkpoint_digest),
            )
        }
    };
    source.vector_digest = source.vector.digest();
    let candidate =
        build_qualified_candidate(source, generation, predecessor, &policy, inputs.clone())
            .unwrap();
    let mut qualification = fixture.qualification;
    qualification.candidate_digest = candidate.candidate_digest;
    let payload =
        compaction_qualification_payload_v1(&candidate, &fixture.binding, &qualification).unwrap();
    let proof = prove_compaction_with_signed_evidence_v1(
        &candidate,
        fixture.binding.clone(),
        qualification,
        &evidence(&fixture.verifier, &payload),
        &fixture.verifier,
        /*now*/ 30,
    )
    .unwrap();
    let host = Host {
        owner: id("owner:compact"),
        scope: candidate.source_snapshot.vector.scope_id.clone(),
        purpose: candidate.source_snapshot.vector.purpose_id.clone(),
        selected: selected.clone(),
        policy: policy.digest(),
        cut: fixture.binding.source_cut_digest,
        verifier: fixture.verifier,
    };
    let proposal = CompactionPublicationProposalV1::new(
        CompactionPublicationRequestV1 {
            owner_agent_id: host.owner.clone(),
            scope_id: host.scope.clone(),
            purpose_id: host.purpose.clone(),
            operation_id: id("operation:restart"),
            policy_generation: Generation::new(/*value*/ 1).unwrap(),
            expected_selected: selected,
            candidate,
            policy,
            inputs,
            authenticated_proof: proof,
        },
        &host.context(/*now*/ 30),
    )
    .unwrap();
    (proposal, host)
}

fn envelope(binary: &[u8]) -> Vec<u8> {
    let mut body = PREFIX.to_vec();
    for byte in binary {
        body.extend_from_slice(format!("{byte:02x}").as_bytes());
    }
    body.extend_from_slice(SUFFIX);
    body
}

fn position(bytes: &[u8], needle: &[u8]) -> usize {
    bytes
        .windows(needle.len())
        .position(|slice| slice == needle)
        .expect("fixture field")
}

#[test]
fn restart_bootstrap_and_successor_readmit_full_preimages_under_fresh_current_host() {
    for selected in [
        CompactionSelectedStateV1::Empty,
        CompactionSelectedStateV1::Selected {
            generation: Generation::new(/*value*/ 8).unwrap(),
            checkpoint_digest: digest("selected"),
        },
    ] {
        let (proposal, host) = body_fixture(/*records*/ 2, selected);
        let body = proposal.encode_restart_body_v1().unwrap();
        assert!(body.len() <= MAX_COMPACTION_PUBLICATION_BODY_BYTES_V1);
        assert_ne!(Digest32::of_bytes(&body), proposal.intent_digest());
        // Only persisted bytes and independently provisioned current state are used.
        let binding = proposal
            .request()
            .authenticated_proof
            .source_binding()
            .clone();
        let fresh_host = Host {
            verifier: LearningEvidenceVerifierV1::new(trust(&binding)).unwrap(),
            ..host
        };
        let restored =
            restore_compaction_publication_body_v1(&body, &fresh_host.context(/*now*/ 40)).unwrap();
        assert_eq!(&restored, &proposal);
        assert_eq!(restored.encode_restart_body_v1().unwrap(), body);
        assert_eq!(restored.authority(), AuthorityPosture::DENY_ALL);
        assert!(
            restored.request().policy.protected_record_ids[0]
                > restored.request().policy.protected_record_ids[1]
        );
        assert!(
            restored.request().inputs[0].record.citations[0].source_id
                > restored.request().inputs[0].record.citations[1].source_id
        );
    }
}

#[test]
fn restart_rebuilds_semantically_equivalent_candidate_without_serializing_its_raw_citation_order() {
    let (original, host) = body_fixture(/*records*/ 2, CompactionSelectedStateV1::Empty);
    let mut request = original.request().clone();
    request.candidate.retained_records[0].citations.reverse();
    let proposal =
        CompactionPublicationProposalV1::new(request, &host.context(/*now*/ 30)).unwrap();
    let body = proposal.encode_restart_body_v1().unwrap();
    let restored =
        restore_compaction_publication_body_v1(&body, &host.context(/*now*/ 40)).unwrap();
    assert_ne!(restored.request().candidate, proposal.request().candidate);
    assert_eq!(restored.request().inputs, proposal.request().inputs);
    assert_eq!(restored.request().policy, proposal.request().policy);
    assert_eq!(
        restored.request().authenticated_proof,
        proposal.request().authenticated_proof
    );
    assert_eq!(
        restored.request().candidate.candidate_digest,
        proposal.request().candidate.candidate_digest
    );
    assert_eq!(restored.intent_digest(), proposal.intent_digest());
    assert_eq!(restored.encode_restart_body_v1().unwrap(), body);
}

#[test]
fn complete_body_profile_rejects_oversized_native_proposal_and_raw_transport() {
    let (proposal, host) = body_fixture(/*records*/ 512, CompactionSelectedStateV1::Empty);
    assert_eq!(
        proposal.encode_restart_body_v1(),
        Err(CompactionPublicationBodyError::BodyLimitExceeded)
    );
    assert_eq!(
        restore_compaction_publication_body_v1(
            &vec![b'a'; MAX_COMPACTION_PUBLICATION_BODY_BYTES_V1 + 1],
            &host.context(/*now*/ 30)
        ),
        Err(CompactionPublicationBodyError::BodyLimitExceeded)
    );
}

#[test]
fn json_wrapper_rejects_unknown_duplicate_noncanonical_schema_hex_and_trailing_fields() {
    let (_, host) = body_fixture(/*records*/ 1, CompactionSelectedStateV1::Empty);
    for body in [
        b"{\"bodyHex\":\"\",\"schemaVersion\":2}".as_slice(),
        b"{\"bodyHex\":\"\",\"schemaVersion\":1,\"extra\":0}",
        b"{\"bodyHex\":\"\",\"bodyHex\":\"\",\"schemaVersion\":1}",
        b"{\"schemaVersion\":1,\"bodyHex\":\"\"}",
        b" {\"bodyHex\":\"\",\"schemaVersion\":1}",
        b"{\"bodyHex\":\"a\",\"schemaVersion\":1}",
        b"{\"bodyHex\":\"AA\",\"schemaVersion\":1}",
        b"{\"bodyHex\":\"gg\",\"schemaVersion\":1}",
        b"{\"bodyHex\":\"\\u0061\\u0061\",\"schemaVersion\":1}",
        b"{\"bodyHex\":\"\",\"schemaVersion\":1}\n",
    ] {
        assert_eq!(
            restore_compaction_publication_body_v1(body, &host.context(/*now*/ 30)),
            Err(CompactionPublicationBodyError::NonCanonicalEnvelope)
        );
    }
}

#[test]
fn every_truncated_binary_and_additional_binary_byte_fails_closed() {
    let (proposal, host) = body_fixture(/*records*/ 1, CompactionSelectedStateV1::Empty);
    let binary = codec::encode(&proposal).unwrap();
    for length in 0..binary.len() {
        assert!(
            restore_compaction_publication_body_v1(
                &envelope(&binary[..length]),
                &host.context(/*now*/ 30)
            )
            .is_err()
        );
    }
    let mut extended = binary;
    extended.push(0);
    assert_eq!(
        restore_compaction_publication_body_v1(&envelope(&extended), &host.context(/*now*/ 30)),
        Err(CompactionPublicationBodyError::InvalidBinary(
            "trailing_bytes"
        ))
    );
}

#[test]
fn binary_count_identifier_enum_and_boolean_mutations_reject_before_admission() {
    let (proposal, host) = body_fixture(/*records*/ 1, CompactionSelectedStateV1::Empty);
    let binary = codec::encode(&proposal).unwrap();
    let policy_end = position(&binary, b"policy:restart") + b"policy:restart".len();
    let protected_count = policy_end + 32 + 32 + 4;
    // One protected ID precedes the input count; fixture record IDs have length 8.
    let input_count = protected_count + 4 + 4 + b"memory:0".len();
    let record_start = input_count + 4;
    let kind = record_start + 4 + b"memory:0".len() + 8;
    let citation_count = kind + 1 + 1 + 32 + 1;
    let qualification = position(&binary, b"evaluator");
    let flags = qualification + b"evaluator".len() + 4 * 32;
    let generator = position(&binary, b"evidence:generator");
    let role = generator + b"evidence:generator".len() + 4 + b"generator".len();
    for (offset, replacement) in [
        (protected_count, u32::MAX.to_be_bytes().to_vec()),
        (input_count, u32::MAX.to_be_bytes().to_vec()),
        (citation_count, 65_u32.to_be_bytes().to_vec()),
        (0, vec![0]),
        (record_start, 129_u32.to_be_bytes().to_vec()),
        (kind, vec![4]),
        (kind + 1, vec![2]),
        (kind + 1 + 1 + 32, vec![2]),
        (flags, vec![2]),
        (role, vec![1]),
    ] {
        let mut changed = binary.clone();
        changed[offset..offset + replacement.len()].copy_from_slice(&replacement);
        assert!(
            restore_compaction_publication_body_v1(&envelope(&changed), &host.context(/*now*/ 30))
                .is_err()
        );
    }
}

#[test]
fn source_input_signature_and_each_commitment_substitution_cannot_restore_admission() {
    let (proposal, host) = body_fixture(/*records*/ 1, CompactionSelectedStateV1::Empty);
    let binary = codec::encode(&proposal).unwrap();
    let content = position(
        &binary,
        proposal.request().inputs[0]
            .record
            .content_digest
            .as_array(),
    );
    let signed = position(
        &binary,
        &proposal
            .request()
            .authenticated_proof
            .signed_evidence()
            .generator
            .signature,
    );
    let source = position(
        &binary,
        proposal
            .request()
            .authenticated_proof
            .source_cut_digest()
            .as_array(),
    );
    for offset in [
        content,
        signed,
        source,
        binary.len() - 128,
        binary.len() - 96,
        binary.len() - 64,
        binary.len() - 32,
    ] {
        let mut changed = binary.clone();
        changed[offset] ^= 1;
        assert!(
            restore_compaction_publication_body_v1(&envelope(&changed), &host.context(/*now*/ 30))
                .is_err()
        );
    }
}

#[test]
fn persisted_body_is_rejected_by_changed_current_owner_policy_selection_source_trust_and_expiry() {
    for field in ["owner", "policy", "selected", "source", "trust", "time"] {
        let (proposal, mut host) =
            body_fixture(/*records*/ 1, CompactionSelectedStateV1::Empty);
        let body = proposal.encode_restart_body_v1().unwrap();
        let mut now = 40;
        match field {
            "owner" => host.owner = id("owner:other"),
            "policy" => host.policy = digest("different-policy"),
            "selected" => {
                host.selected = CompactionSelectedStateV1::Selected {
                    generation: Generation::new(/*value*/ 1).unwrap(),
                    checkpoint_digest: digest("selected"),
                }
            }
            "source" => host.cut = digest("different-cut"),
            "trust" => {
                let mut trust = trust(proposal.request().authenticated_proof.source_binding());
                trust.signers[0].controller_id = id("different-controller");
                host.verifier = LearningEvidenceVerifierV1::new(trust).unwrap();
            }
            "time" => now = 91,
            _ => unreachable!(),
        }
        let error = restore_compaction_publication_body_v1(&body, &host.context(now)).unwrap_err();
        assert!(std::error::Error::source(&error).is_some());
    }
}
