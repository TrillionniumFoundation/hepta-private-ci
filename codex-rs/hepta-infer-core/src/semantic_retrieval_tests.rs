use super::*;

fn request() -> SemanticRetrievalRequestV1 {
    SemanticRetrievalRequestV1 {
        operation_id: "op.1".to_string(),
        workspace_id: "ws.1".to_string(),
        generation: 3,
        objective_digest: "1".repeat(64),
        observation_digest: "2".repeat(64),
        bundle_digest: "3".repeat(64),
        deadline_ms: 9000,
        query: "q".to_string(),
        sources: vec![RetrievalSourceV1 {
            source_id: "src.1".to_string(),
            revision: 7,
            content_sha256: Digest32::of_bytes(b"alpha").to_string(),
            text: "alpha".to_string(),
        }],
    }
}

fn golden_reply() -> Vec<u8> {
    let hex = "4850544152530100268a20079cee413b0d086ada8cb77a6e677a4759f66f40e6b6424fa4a915a2ef333333333333333333333333333333333333333333333333333333333333333300000002000186a0000dbba0000000000000000c00000000000000000000000000000007";
    hex.as_bytes()
        .chunks_exact(2)
        .map(|pair| {
            u8::from_str_radix(std::str::from_utf8(pair).expect("hex text"), 16).expect("hex byte")
        })
        .collect()
}

#[test]
fn request_identity_matches_python_wire_golden() {
    let encoded = request().encode().expect("request");
    assert_eq!(encoded.len(), 203);
    assert_eq!(
        Digest32::of_bytes(&encoded).to_string(),
        "268a20079cee413b0d086ada8cb77a6e677a4759f66f40e6b6424fa4a915a2ef"
    );
}

#[test]
fn decodes_exact_python_reply_without_action_authority() {
    let selected = request();
    assert_eq!(
        selected.decode_reply(&golden_reply()).expect("reply"),
        SemanticRetrievalReplyV1 {
            request_digest: Digest32::of_bytes(&selected.encode().expect("request")),
            bundle_digest: Digest32::from_str(&"3".repeat(64)).expect("digest"),
            prediction_ppm: vec![100_000, 900_000],
            input_tokens: 12,
            output_tokens: 0,
            latency_micros: 7,
        }
    );
}

#[test]
fn rejects_every_truncated_reply() {
    let raw = golden_reply();
    for length in 0..raw.len() {
        assert!(request().decode_reply(&raw[..length]).is_err());
    }
}

#[test]
fn rejects_reply_for_changed_scope_or_observation() {
    let raw = golden_reply();
    let mut changed = request();
    changed.workspace_id = "ws.2".to_string();
    assert_eq!(changed.decode_reply(&raw), Err(RetrievalWireError::Binding));
    let mut changed = request();
    changed.generation += 1;
    assert_eq!(changed.decode_reply(&raw), Err(RetrievalWireError::Binding));
    let mut changed = request();
    changed.sources[0].revision += 1;
    assert_eq!(changed.decode_reply(&raw), Err(RetrievalWireError::Binding));
    let mut changed = request();
    changed.deadline_ms += 1;
    assert_eq!(changed.decode_reply(&raw), Err(RetrievalWireError::Binding));
}

#[test]
fn rejects_trailing_or_wrong_profile_data() {
    let mut raw = golden_reply();
    raw.push(0);
    assert_eq!(
        request().decode_reply(&raw),
        Err(RetrievalWireError::Trailing)
    );
    let mut raw = golden_reply();
    raw[6] = 2;
    assert_eq!(
        request().decode_reply(&raw),
        Err(RetrievalWireError::Profile)
    );
}

#[test]
fn rejects_source_substitution_and_duplicate_ids() {
    let mut changed = request();
    changed.sources[0].text.push('!');
    assert_eq!(changed.encode(), Err(RetrievalWireError::SourceChanged));
    let mut changed = request();
    changed.sources.push(changed.sources[0].clone());
    assert_eq!(changed.encode(), Err(RetrievalWireError::DuplicateSource));
}

#[test]
fn enforces_utf8_byte_and_generation_bounds() {
    let mut changed = request();
    changed.query = "检索".repeat(400);
    assert_eq!(changed.encode(), Err(RetrievalWireError::Bounds));
    let mut changed = request();
    changed.generation = 0;
    assert_eq!(changed.encode(), Err(RetrievalWireError::Bounds));
    let mut changed = request();
    changed.bundle_digest = "A".repeat(64);
    assert_eq!(changed.encode(), Err(RetrievalWireError::Digest));
}

#[test]
fn rejects_invalid_prediction_mass() {
    let mut raw = golden_reply();
    raw[76..80].copy_from_slice(&100_001_u32.to_be_bytes());
    assert_eq!(
        request().decode_reply(&raw),
        Err(RetrievalWireError::Probability)
    );
    let mut raw = golden_reply();
    raw[72..76].copy_from_slice(&16_u32.to_be_bytes());
    assert_eq!(
        request().decode_reply(&raw),
        Err(RetrievalWireError::Binding)
    );
}

#[test]
fn checks_deadline_at_the_exact_boundary() {
    assert_eq!(request().validate_at(8999), Ok(()));
    assert_eq!(
        request().validate_at(9000),
        Err(RetrievalWireError::Expired)
    );
}
