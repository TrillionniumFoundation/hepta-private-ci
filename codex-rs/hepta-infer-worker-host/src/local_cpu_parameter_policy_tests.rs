use super::*;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

fn envelope(
    mut change: impl FnMut(&mut serde_json::Value),
) -> TestResult<CanonicalIterationEnvelopeV1> {
    let mut value = serde_json::json!({
        "envelopeId": "sparse.window.one",
        "baseCommit": "1".repeat(40),
        "baseTree": "2".repeat(40),
        "objectiveDigest": "3".repeat(64),
        "grammarDigest": "4".repeat(64),
        "allowedPaths": [CPU_PARAMETER_OPERAND_V1],
        "deniedAuthorities": DENIED_MODEL_AUTHORITIES,
        "maximumFiles": 1, "maximumBytes": 4096, "maximumCandidates": 4,
        "wallTimeMicros": 300_000_000,
        "computeBudget": {"profile": "hepta.iteration-compute-budget.v1",
            "maximumParallelSandboxes": 1, "maximumMemoryBytes": 134_217_728,
            "maximumProcesses": 1},
        "mandatoryChecks": CPU_PARAMETER_CHECKS_V1,
        "expiresUnixMs": 4_000_000_000_000_u64
    });
    change(&mut value);
    Ok(CanonicalIterationEnvelopeV1::decode(&serde_json::to_vec(
        &value,
    )?)?)
}

#[test]
fn independent_pin_retains_every_policy_byte_and_rejects_other_git_identity() -> TestResult {
    let original = envelope(|_| {})?;
    let pinned = CpuNeuronParameterPolicyV2::new(original.clone(), original.digest())?;
    assert_eq!(
        pinned.canonical().canonical_bytes(),
        original.canonical_bytes()
    );
    let changed = envelope(|value| value["baseCommit"] = "5".repeat(40).into())?;
    assert!(CpuNeuronParameterPolicyV2::new(changed, original.digest()).is_err());
    assert!(CpuNeuronParameterPolicyV2::new(original, Digest32::ZERO).is_err());
    Ok(())
}

#[test]
fn even_a_matching_pin_cannot_expand_sparse_operation_or_drop_owner_checks() -> TestResult {
    for change in [
        |value: &mut serde_json::Value| value["allowedPaths"] = serde_json::json!(["src/runtime"]),
        |value: &mut serde_json::Value| value["mandatoryChecks"] = serde_json::json!(["unit"]),
        |value: &mut serde_json::Value| value["deniedAuthorities"] = serde_json::json!(["release"]),
    ] {
        let unsupported = envelope(change)?;
        let pin = unsupported.digest();
        assert!(CpuNeuronParameterPolicyV2::new(unsupported, pin).is_err());
    }
    Ok(())
}

#[test]
fn actual_operand_diff_is_checked_before_any_physical_generation_can_open() -> TestResult {
    let envelope = envelope(|value| value["maximumBytes"] = 8.into())?;
    let policy = CpuNeuronParameterPolicyV2::new(envelope.clone(), envelope.digest())?;
    policy.check_diff(b"12345678")?;
    assert!(policy.check_diff(b"123456789").is_err());
    Ok(())
}
