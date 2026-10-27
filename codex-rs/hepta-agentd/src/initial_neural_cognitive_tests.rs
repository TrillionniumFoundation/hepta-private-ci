//! Port-contract regressions only; real model/ordinary socket tests live at the
//! native host. These doubles establish no loading, installation or efficacy.

use super::*;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

#[derive(Clone, Copy)]
enum Fault {
    None,
    Selection,
    Query,
    Actions,
    Receipt,
    PartialScores,
}

struct Port {
    fault: Fault,
    calls: AtomicUsize,
}

impl InitialNeuralCognitiveInferencePortV2 for Port {
    fn execute_initial(
        &self,
        request: &InitialNeuralCognitiveRequestV2,
        _execution: &NeuralCognitiveExecutionV1,
    ) -> Result<InitialNeuralCognitiveObservationV2, String> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let mut result = InitialNeuralCognitiveObservationV2 {
            request: request.clone(),
            scores_q32: Some(vec![7, -3]),
            execution_receipt_digest: Digest32::of_bytes(b"controlled port observation"),
            authority: AuthorityPosture::DENY_ALL,
        };
        match self.fault {
            Fault::None => {}
            Fault::Selection => result.request.pin.selection_digest = Digest32::ZERO,
            Fault::Query => result.request.query.push_str(" substituted"),
            Fault::Actions => result.request.action_ids.reverse(),
            Fault::Receipt => result.execution_receipt_digest = Digest32::ZERO,
            Fault::PartialScores => result.scores_q32 = Some(vec![7]),
        }
        Ok(result)
    }
}

#[test]
fn initial_observation_binds_selection_query_actions_receipt_and_complete_scores() {
    let owner = AgentId::parse("00000000-0000-4000-8000-000000000119").unwrap();
    let items = ["one", "two"].map(|name| CognitiveContextItem {
        memory_id: name.to_owned(),
        revision: 1,
        content: String::new(),
        content_sha256: Digest32::of_bytes(name.as_bytes()).to_string(),
    });
    for fault in [
        Fault::None,
        Fault::Selection,
        Fault::Query,
        Fault::Actions,
        Fault::Receipt,
        Fault::PartialScores,
    ] {
        let port = Arc::new(Port {
            fault,
            calls: AtomicUsize::new(0),
        });
        let model = InitialNeuralCognitiveModelV2 {
            pin: InitialNeuralCognitivePinV2 {
                payload_digest: Digest32::of_bytes(b"controlled selected bytes"),
                generation: Generation::new(1).unwrap(),
                selection_digest: Digest32::of_bytes(b"controlled selection"),
                family_digest: Digest32::of_bytes(b"controlled family"),
                execution_profile_digest: Digest32::of_bytes(b"controlled execution"),
            },
            inference: port.clone(),
        };
        let observed = model.score(
            &owner,
            1,
            "lemon",
            &items,
            &NeuralCognitiveExecutionV1::bounded_read(),
        );
        if matches!(fault, Fault::None) {
            std::assert_eq!(observed, Ok(Some(vec![7, -3])));
        } else {
            assert!(observed.is_err());
        }
        std::assert_eq!(port.calls.load(Ordering::SeqCst), 1);
        std::assert_eq!(
            model.score(
                &owner,
                1,
                "lemon",
                &[],
                &NeuralCognitiveExecutionV1::bounded_read()
            ),
            Ok(None)
        );
        assert!(
            model
                .score(
                    &owner,
                    1,
                    "",
                    &items,
                    &NeuralCognitiveExecutionV1::bounded_read()
                )
                .is_err()
        );
        std::assert_eq!(port.calls.load(Ordering::SeqCst), 1);
    }
}
