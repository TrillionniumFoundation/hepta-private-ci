use super::*;
use pretty_assertions::assert_eq;
use std::error::Error;

#[test]
fn canonical_model_binds_the_original_identity_intent_and_terminal_receipt()
-> Result<(), Box<dyn Error>> {
    let contract: serde_json::Value =
        serde_json::from_str(include_str!("../tests/fixtures/notes-model-v1.json"))?;
    let target: NotesTargetIdentity = serde_json::from_value(contract["target"].clone())?;
    let payload = contract["wire"]["request_utf8"].as_str().ok_or("request")?;
    let response = contract["wire"]["response_utf8"]
        .as_str()
        .ok_or("response")?;
    let intent = notes_operation_intent(
        &target,
        payload,
        StableId::new("notes-model-subject")?,
        Generation::new(1)?,
    )?;
    assert_eq!(target.destination_id(), contract["destination_id"]);
    assert_eq!(intent.destination_id().as_str(), target.destination_id());
    assert_eq!(intent.scope_digest().to_string(), contract["scope_sha256"]);
    assert_eq!(
        intent
            .expected_predecessor()
            .ok_or("predecessor")?
            .to_string(),
        contract["predecessor_sha256"]
    );
    let receipt = NotesTerminalReceipt::from_json(payload, response)?;
    assert_eq!(receipt.outcome(), crate::LocalReconcileOutcome::Committed);
    assert_eq!(receipt.as_str(), response);
    for domain in ["checkpoint", "bootstrap"] {
        let key = if domain == "checkpoint" {
            "current_utf8"
        } else {
            "offer_utf8"
        };
        assert!(
            notes_operation_intent(
                &target,
                contract[domain][key].as_str().ok_or("other domain")?,
                StableId::new("notes-model-subject")?,
                Generation::new(1)?
            )
            .is_err()
        );
    }
    let mut changed: serde_json::Value = serde_json::from_str(response)?;
    changed["target"]["incarnation"] = serde_json::json!("4".repeat(32));
    assert!(NotesTerminalReceipt::from_json(payload, &serde_json::to_string(&changed)?).is_err());
    let mut rebound = target;
    rebound.incarnation = "4".repeat(32);
    assert!(
        notes_operation_intent(
            &rebound,
            payload,
            StableId::new("notes-model-subject")?,
            Generation::new(1)?
        )
        .is_err()
    );
    Ok(())
}
