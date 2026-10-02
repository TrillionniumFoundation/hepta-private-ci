use super::*;

type TestResult<T> = Result<T, Box<dyn std::error::Error>>;

pub(super) fn fixture(
    prompt: &str,
) -> TestResult<(NativeRequest, NativeBoundSourceRecordV2, std::path::PathBuf)> {
    let socket = std::env::temp_dir().join("bound-source-agent.sock");
    let context = format!("{:x}", Sha256::digest(b"context"));
    let envelope = format!("{:x}", Sha256::digest(b"envelope"));
    let bytes = serde_json::to_vec(&(
        "hepta.native-intelligence-request.v2",
        prompt,
        None::<String>,
        &socket,
        1000_u128,
        "run-one",
        2_u64,
        &context,
        &envelope,
    ))?;
    let payload = format!("{:x}", Sha256::digest(bytes));
    Ok((
        NativeRequest {
            request_id: "request-one".to_string(),
            principal_id: "principal-one".to_string(),
            worker_generation: 1,
            model: "model".to_string(),
            payload_digest: payload.clone(),
        },
        NativeBoundSourceRecordV2 {
            schema_version: 2,
            request_id: "request-one".to_string(),
            request_payload_sha256: payload,
            run_id: "run-one".to_string(),
            owner_pre_dispatch_revision: 2,
            context_sha256: context,
            envelope_sha256: envelope,
        },
        socket,
    ))
}

#[test]
fn exact_v2_source_proof_retains_only_binding_metadata() {
    let prompt = "private prompt must not enter retained source metadata";
    let (request, record, socket) = fixture(prompt).unwrap();
    let proof =
        NativeBoundSourceProof::verify(&request, prompt, &None, &socket, 1000, record.clone())
            .unwrap();
    assert_eq!(proof.record(), &record);
    let retained = serde_json::to_string(proof.record()).unwrap();
    assert!(!retained.contains(prompt));
    assert!(!retained.contains("bound-source-agent.sock"));
}

#[test]
fn unchanged_signed_payload_cannot_be_relabelled_to_another_run_or_context() {
    let (request, record, socket) = fixture("prompt").unwrap();
    for field in 0..4 {
        let mut drift = record.clone();
        match field {
            0 => drift.run_id = "different-run".to_string(),
            1 => drift.context_sha256 = format!("{:x}", Sha256::digest(b"other context")),
            2 => drift.envelope_sha256 = format!("{:x}", Sha256::digest(b"other envelope")),
            3 => drift.owner_pre_dispatch_revision += 1,
            _ => unreachable!(),
        }
        assert!(
            NativeBoundSourceProof::verify(&request, "prompt", &None, &socket, 1000, drift)
                .is_err()
        );
    }
}

#[test]
fn original_binding_rejects_prompt_query_socket_or_timeout_drift() {
    let (request, record, socket) = fixture("prompt").unwrap();
    assert!(
        NativeBoundSourceProof::verify(&request, "changed", &None, &socket, 1000, record.clone())
            .is_err()
    );
    assert!(
        NativeBoundSourceProof::verify(
            &request,
            "prompt",
            &Some("query".to_string()),
            &socket,
            1000,
            record.clone()
        )
        .is_err()
    );
    assert!(
        NativeBoundSourceProof::verify(
            &request,
            "prompt",
            &None,
            &socket.with_extension("other"),
            1000,
            record.clone()
        )
        .is_err()
    );
    assert!(
        NativeBoundSourceProof::verify(&request, "prompt", &None, &socket, 1001, record).is_err()
    );
}

#[test]
fn source_preimage_is_bounded_before_encoding() {
    let prompt = "x".repeat(MAX_BOUND_SOURCE_BYTES + 1);
    let (request, record, socket) = fixture(&prompt).unwrap();
    assert!(
        NativeBoundSourceProof::verify(&request, &prompt, &None, &socket, 1000, record).is_err()
    );
    let (request, mut record, _) = fixture("prompt").unwrap();
    record.owner_pre_dispatch_revision = u64::MAX;
    assert!(record.validate(&request).is_err());
}
