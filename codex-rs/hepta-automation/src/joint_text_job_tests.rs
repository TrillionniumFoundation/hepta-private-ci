use super::*;
use pretty_assertions::assert_eq;

fn input(bytes: &[u8]) -> JointTextInputRefV1 {
    JointTextInputRefV1::from_manifest(JointTextInputManifestV1 {
        schema_version: 1,
        profile: JointTextProfileV1::VerifiedMemoryTextSgdV1,
        request_sha256: Sha256Digest::for_bytes(bytes),
        request_bytes: bytes.len() as u64,
        request_binding_digest: Sha256Digest::for_bytes(b"framed request binding"),
        predecessor_sha256: Sha256Digest::for_bytes(b"predecessor"),
        predecessor_bytes: 11,
        worker_execution_source_digest: Sha256Digest::for_bytes(b"worker closure"),
    })
    .expect("input binding")
}

fn start(input: &JointTextInputRefV1) -> JointTextJobCommandV1 {
    let payload = String::from_utf8(input.encode().expect("descriptor")).expect("UTF-8");
    let identity = JointTextJobIdentityV1::for_taskflow(
        "joint-provider",
        "original-run",
        "training",
        Sha256Digest::for_bytes(payload.as_bytes()),
    )
    .expect("identity");
    JointTextJobCommandV1::start(identity, payload).expect("start")
}

#[test]
fn descriptor_rejects_substitution_unknown_fields_and_noncanonical_json() {
    let reference = input(b"original request\n");
    let bytes = reference.encode().expect("encode");
    assert_eq!(JointTextInputRefV1::decode(&bytes), Ok(reference.clone()));
    let mut altered = reference;
    altered.manifest.request_sha256 = Sha256Digest::for_bytes(b"substituted");
    assert_eq!(
        altered.encode(),
        Err(JointTextSupervisorError::BeforeContact)
    );
    let mut value: serde_json::Value = serde_json::from_slice(&bytes).expect("JSON");
    value["path"] = "/untrusted/worker-input".into();
    assert!(JointTextInputRefV1::decode(&serde_json::to_vec(&value).expect("JSON")).is_err());
    let mut spaced = bytes.clone();
    spaced.push(b'\n');
    assert!(JointTextInputRefV1::decode(&spaced).is_err());
    let text = String::from_utf8(bytes).expect("UTF-8");
    let duplicate = text.replacen(
        "\"schema_version\":1",
        "\"schema_version\":1,\"schema_version\":1",
        1,
    );
    assert!(JointTextInputRefV1::decode(duplicate.as_bytes()).is_err());
}

#[test]
fn stable_identity_separates_hcsn_and_cancel_queries_the_original_target() {
    let command = start(&input(b"original request"));
    let repeated = start(&input(b"original request"));
    assert_eq!(repeated, command);
    let hcsn = crate::HcsnJobIdentityV1::for_key(
        command.target.key.clone(),
        command.target.payload_sha256.clone(),
    )
    .expect("old protocol identity");
    assert_ne!(hcsn.job_id, command.target.job_id);
    assert_ne!(hcsn.output_id, command.target.output_id);
    assert_eq!(
        JointTextJobCommandV1::cancel(command.target.clone(), command.target.clone()),
        Err(JointTextSupervisorError::BeforeContact)
    );
    let cancel_id = JointTextJobIdentityV1::for_taskflow(
        "joint-provider",
        "original-run",
        "cancel-training",
        Sha256Digest::for_bytes(b"explicit cancel"),
    )
    .expect("separate dispatch");
    let cancel = JointTextJobCommandV1::cancel(cancel_id, command.target).expect("cancel");
    let mut expected = cancel.clone();
    expected.action = JointTextSupervisorActionV1::Status;
    assert_eq!(cancel.status(), expected);
    assert_eq!(expected.validate(), Ok(()));
}

#[test]
fn success_requires_complete_evidence_for_the_original_input() {
    let reference = input(b"original request");
    let command = start(&reference);
    let file = JointTextFileDigestV1 {
        sha256: Sha256Digest::for_bytes(b"observed bytes"),
        bytes: 14,
    };
    let mut observed = JointTextJobObservationV1 {
        schema_version: 1,
        profile: JointTextProfileV1::VerifiedMemoryTextSgdV1,
        dispatch: command.dispatch.clone(),
        target: command.target.clone(),
        state: JointTextJobStateV1::Succeeded,
        process: Some(JointTextProcessIdentityV1 {
            host_id: Sha256Digest::for_bytes(b"host"),
            process_id: 123,
            incarnation: Sha256Digest::for_bytes(b"boot and start ticks"),
        }),
        evidence: Some(JointTextJobEvidenceV1::Completed {
            terminal: file.clone(),
            outputs: Box::new(JointTextJobOutputsV1 {
                input: reference,
                started: file.clone(),
                candidate: file.clone(),
                observation: file.clone(),
                completed: file.clone(),
            }),
        }),
    };
    assert_eq!(observed.validate_for(&command), Ok(()));
    if let Some(JointTextJobEvidenceV1::Completed { outputs, .. }) = &mut observed.evidence {
        outputs.input = input(b"another request");
    }
    assert_eq!(
        observed.validate_for(&command),
        Err(JointTextSupervisorError::Unknown)
    );
    observed.evidence = Some(JointTextJobEvidenceV1::Stopped { terminal: file });
    assert_eq!(
        observed.validate_for(&command),
        Err(JointTextSupervisorError::Unknown)
    );
    observed.state = JointTextJobStateV1::Failed;
    assert_eq!(observed.validate_for(&command), Ok(()));
}
