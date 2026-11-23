//! Exercise the actual protected-client wire contract against a local test peer.

use super::*;
use crate::PairedLearningDataUse::EvaluateOnlyAfterFreeze;
use crate::PairedLearningDataUse::TrainOnFailureAndCorrection;
use codex_hepta_types::Digest32;

fn ingress(text: String) -> crate::AuthBusTextIngress {
    crate::AuthBusTextIngress {
        issuer_id: "fixture-issuer".into(),
        key_epoch: 1,
        message_id: "fixture-message".into(),
        sequence: 2,
        expires_at_ms: 60_000,
        signature_hex: "11".repeat(64),
        body: crate::AuthBusTextBody {
            spawn_generation: 1,
            thread_id: "fixture-thread".into(),
            text,
        },
    }
}

#[test]
fn rejects_a_different_study_scope_or_record_before_requesting_owner_evidence() {
    let (provider, _peer) = fixture(Duration::from_secs(2));
    let study = Digest32::of_bytes(b"study");
    let failure = Digest32::of_bytes(b"failed");
    let correction = Digest32::of_bytes(b"corrected");
    let train = TrainOnFailureAndCorrection {
        failure,
        correction,
    };
    let evaluate = EvaluateOnlyAfterFreeze {
        freeze: failure,
        task: correction,
    };
    let original = ingress(train.consent_text(study));
    let swapped = TrainOnFailureAndCorrection {
        failure: correction,
        correction: failure,
    };
    for (study, expected) in [(correction, train), (study, evaluate), (study, swapped)] {
        assert_eq!(
            provider.verify_paired_learning_consent(&original, study, expected),
            Err(AgentdFinalUseIssuerError::BindingMismatch)
        );
    }
    let original = ingress(evaluate.consent_text(study));
    for expected in [
        EvaluateOnlyAfterFreeze {
            freeze: correction,
            task: correction,
        },
        EvaluateOnlyAfterFreeze {
            freeze: failure,
            task: failure,
        },
    ] {
        assert_eq!(
            provider.verify_paired_learning_consent(&original, study, expected),
            Err(AgentdFinalUseIssuerError::BindingMismatch)
        );
    }
}

#[test]
fn exact_statement_uses_the_existing_protected_human_verify_operation() {
    let (provider, mut peer) = fixture(Duration::from_secs(3));
    let study = Digest32::of_bytes(b"study");
    let expected = EvaluateOnlyAfterFreeze {
        freeze: Digest32::of_bytes(b"frozen pair"),
        task: Digest32::of_bytes(b"future task"),
    };
    let original = ingress(expected.consent_text(study));
    let retained = original.clone();
    let owner = json!({
        "schema_version": 1, "protocol": "hepta.ui-chat-owner.v1",
        "principal_id": "fixture-principal", "session_id": "fixture-session",
        "permission_revision": 1, "expires_at_ms": 60000, "can_interrupt": false,
        "intent_namespace": "fixture", "next_intent_sequence": 3,
        "route": {
            "control_socket": "/fixture/socket", "codex_home": "/fixture/home",
            "agent_id": "018f4f72-5f8f-7cc1-8f55-df9fb3aa2d18", "spawn_generation": 1,
            "thread_id": "fixture-thread", "app_server_session_id": "fixture-app-server"
        }
    });
    let expected_owner = serde_json::from_value(owner.clone()).unwrap();
    let server = thread::spawn(move || {
        let request = json!({
            "schema_version": 1,
            "operation": "runtime.authbus.human_text.verify.v1",
            "ingress": retained
        });
        let digest = Digest32::of_bytes(&serde_json::to_vec(&retained).unwrap()).to_string();
        for owner in [owner, json!({})] {
            assert_eq!(read(&mut peer), request);
            send(
                &mut peer,
                json!({
                    "schema_version": 1,
                    "operation": "runtime.authbus.human_text.verified.v1",
                    "ingress_sha256": digest,
                    "owner": owner
                }),
            );
        }
    });
    assert_eq!(
        provider.verify_paired_learning_consent(&original, study, expected),
        Ok(expected_owner)
    );
    assert_eq!(
        provider.verify_paired_learning_consent(&original, study, expected),
        Err(AgentdFinalUseIssuerError::MalformedResponse)
    );
    server.join().unwrap();
}
