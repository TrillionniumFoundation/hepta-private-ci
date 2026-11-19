//! Actual files and original writer locks; only the existing Current port
//! fixture is synthetic. These reads do not prove a Feature execution or ACK.

use pretty_assertions::assert_eq;

use super::*;

type TestResult = Result<(), Box<dyn std::error::Error>>;

#[test]
fn original_feature_boundary_keeps_genesis_digest_across_actual_drain() -> TestResult {
    let files = Files::new();
    let mut owner = owner(&files);
    let reader = observer(&files);
    let genesis = reader.observe()?;
    let (first, origin) = reader.observe_original_feature_boundary()?;
    assert_eq!(first, genesis);
    assert_eq!(origin, genesis.observation().digest()?);
    assert!(files.file("journal").try_lock().is_err());
    assert!(files.file("witness").try_lock().is_err());
    owner.drain()?;
    let bytes = (files.bytes(), fs::read(files.0.join("witness"))?);
    let (drained, retained_origin) = reader.observe_original_feature_boundary()?;
    assert!(drained.is_drained());
    assert!(!drained.is_genesis());
    assert_eq!(retained_origin, origin);
    assert_ne!(drained.observation().digest()?, origin);
    assert_eq!(drained.observation(), &owner.observe_generation()?);
    assert_eq!((files.bytes(), fs::read(files.0.join("witness"))?), bytes);
    drop(owner);
    let cold = observer(&files);
    assert_eq!(cold.observe_original_feature_boundary()?, (drained, origin));
    assert_eq!((files.bytes(), fs::read(files.0.join("witness"))?), bytes);
    Ok(())
}

#[test]
fn original_feature_boundary_refuses_revision_zero_with_resume_or_admission() -> TestResult {
    for admission in [false, true] {
        let files = Files::new();
        let mut owner = owner(&files);
        let reader = observer(&files);
        reader.observe_original_feature_boundary()?;
        if admission {
            let config = config();
            let request = CellGenerationRequestV2 {
                operation_id: "actual-admission-before-feature-read".into(),
                task_digest: config.task_digest,
                source_frontier: config.source_frontier,
                predecessor: config.initial,
                input: vec![2],
                admitted_at_micros: 10,
                deadline_micros: 100,
            };
            owner.admit(request, /*now_micros*/ 10)?;
        } else {
            owner.drain()?;
            owner.resume()?;
        }
        owner.drain()?;
        let before = (files.bytes(), fs::read(files.0.join("witness"))?);
        assert_eq!(reader.observe()?.observation().snapshot().revision, 0);
        assert_eq!(
            reader.observe_original_feature_boundary().err(),
            Some(CellGenerationErrorV2::InvalidBinding)
        );
        assert_eq!((files.bytes(), fs::read(files.0.join("witness"))?), before);
    }
    Ok(())
}
