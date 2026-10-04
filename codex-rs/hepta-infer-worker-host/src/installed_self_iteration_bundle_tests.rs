use super::*;

fn source(id: &str, purpose: &str) -> PreparedCandidateAdmissionV1 {
    PreparedCandidateAdmissionV1 {
        candidate_id: id.into(),
        configuration: InstalledCpuSourceV1 {
            path: format!("/original/{id}/{purpose}-configuration.json").into(),
            digest: Digest32::of_bytes(format!("{id}:{purpose}:configuration").as_bytes())
                .to_string(),
        },
        selection: InstalledCpuSourceV1 {
            path: format!("/original/{id}/{purpose}-selection.json").into(),
            digest: Digest32::of_bytes(format!("{id}:{purpose}:selection").as_bytes()).to_string(),
        },
    }
}

#[test]
fn complete_distinct_pairs_preserve_every_whole_original_source() -> Result<(), AgentdError> {
    let candidates = [source("first", "candidate"), source("second", "candidate")];
    let legacy = source("first", "rollback");
    let pairs = [source("second", "rollback"), source("first", "rollback")];
    assert_eq!(
        sources(&candidates, &legacy, &pairs)?,
        vec![&pairs[0], &pairs[1]]
    );
    for bad in [
        vec![source("first", "rollback")],
        vec![source("first", "rollback"), source("first", "rollback")],
        vec![source("first", "rollback"), source("foreign", "rollback")],
        vec![
            source("first", "other-purpose"),
            source("second", "rollback"),
        ],
    ] {
        assert!(sources(&candidates, &legacy, &bad).is_err());
    }
    assert!(sources(&candidates, &legacy, &[]).is_err());
    assert!(sources(&candidates, &source("second", "rollback"), &pairs).is_err());
    Ok(())
}

#[test]
fn legacy_one_update_retains_its_original_complete_admission() -> Result<(), AgentdError> {
    let candidates = [source("first", "candidate")];
    let legacy = source("first", "rollback");
    assert_eq!(sources(&candidates, &legacy, &[])?, vec![&legacy]);
    assert!(sources(&candidates, &source("foreign", "rollback"), &[]).is_err());
    assert!(sources(&[], &legacy, &[]).is_err());
    Ok(())
}

#[test]
fn maximum_frontier_preserves_every_distinct_long_source_and_rejects_an_extra_pair()
-> Result<(), AgentdError> {
    let long_directory = format!("/original/{}", "retained-round/".repeat(64));
    let entry = |ordinal: usize, purpose: &str| {
        let mut entry = source(&format!("candidate-{ordinal}"), purpose);
        entry.configuration.path = format!("{long_directory}/{ordinal}/{purpose}-config.json").into();
        entry.selection.path = format!("{long_directory}/{ordinal}/{purpose}-selection.json").into();
        entry
    };
    let mut candidates: Vec<_> = (0..32).map(|ordinal| entry(ordinal, "candidate")).collect();
    let mut rollbacks: Vec<_> = (0..32).rev().map(|ordinal| entry(ordinal, "rollback")).collect();
    let legacy = entry(0, "rollback");
    let bytes = serde_json::to_vec(&(&candidates, &rollbacks))?;
    assert!(bytes.len() > 64 * 1024);
    assert!(bytes.len() as u64 <= crate::local_cpu_parameter_root_materials_v2::MAX_PARAMETER_ROUND_DESCRIPTOR_BYTES_V2);
    let (decoded_candidates, decoded_rollbacks): (
        Vec<PreparedCandidateAdmissionV1>, Vec<PreparedCandidateAdmissionV1>,
    ) = serde_json::from_slice(&bytes)?;
    assert_eq!(sources(&decoded_candidates, &legacy, &decoded_rollbacks)?, rollbacks.iter().collect::<Vec<_>>());
    candidates.push(entry(32, "candidate"));
    rollbacks.push(entry(32, "rollback"));
    assert!(sources(&candidates, &legacy, &rollbacks).is_err());
    Ok(())
}
