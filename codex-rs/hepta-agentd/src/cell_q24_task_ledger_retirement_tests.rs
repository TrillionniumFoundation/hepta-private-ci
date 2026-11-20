//! Actual task owner retirement after independently signed Terminal history.

use std::io::Read;

use super::*;

fn generation_bytes(f: &Fixture) -> anyhow::Result<Vec<Vec<u8>>> {
    ["target-journal", "target-witness"]
        .map(|name| {
            let mut bytes = Vec::new();
            f._version.file(name)?.read_to_end(&mut bytes)?;
            Ok(bytes)
        })
        .into_iter()
        .collect()
}

#[tokio::test]
async fn original_task_terminal_outcome_drains_once_and_readback_never_writes() -> anyhow::Result<()>
{
    let mut f = Fixture::new(
        "ordinary-ledger-actual-retirement",
        /*lifetime*/ 600,
        /*automatic*/ true,
    )
    .await?;
    let initial = generation_bytes(&f)?;
    let original_task = f.task_bytes()?;
    assert!(matches!(
        f.producer.readback()?,
        Status::AwaitingOutcome { .. }
    ));
    assert_eq!(generation_bytes(&f)?, initial);
    let outcome = f.outcome();
    let signed = f.sign_outcome(&outcome, /*lifetime*/ 300);
    let mut invalid = signed.clone();
    invalid.signature[0] ^= 1;
    assert!(
        f.producer
            .submit_original_terminal_outcome(outcome.clone(), &invalid)
            .is_err()
    );
    assert_eq!(generation_bytes(&f)?, initial);
    let completed = f
        .producer
        .submit_original_terminal_outcome(outcome.clone(), &signed)?;
    assert!(matches!(completed, Status::Complete { .. }));
    let drained = generation_bytes(&f)?;
    assert_ne!(drained[0], initial[0]);
    assert_ne!(drained[1], initial[1]);
    assert_eq!(f.producer.readback()?, completed);
    assert_eq!(generation_bytes(&f)?, drained);
    assert_eq!(f.producer.resume_from_original_source()?, completed);
    assert_eq!(generation_bytes(&f)?, drained);
    assert_eq!(
        f.producer
            .submit_original_terminal_outcome(outcome, &signed)?,
        completed
    );
    assert_eq!(generation_bytes(&f)?, drained);
    f.require_task_unchanged(&original_task)?;
    f.session.stop().await
}
