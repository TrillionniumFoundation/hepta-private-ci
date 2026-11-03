use crate::policy::{Controller, Scores};

#[test]
fn structured_terminal_values_replace_only_terminal_coordinates() {
    let raw = Scores {
        q: [9.0, 0.2, 0.4, -0.1, 8.0, 7.0],
        belief_logit: 3.0,
        belief: 0.875,
    };
    let expected = Scores {
        q: [0.0, 0.2, 0.4, -0.1, -0.75, 0.75],
        belief_logit: 3.0,
        belief: 0.875,
    };
    assert_eq!(
        raw.clone().for_controller(Controller::StructuredValue),
        expected
    );
    assert_eq!(raw.clone().for_controller(Controller::Value), raw);
    assert_eq!(
        expected.clone().for_controller(Controller::StructuredValue),
        expected
    );
}

#[test]
fn learned_belief_controls_polarity_and_neutral_submission() {
    for belief in [0.0, 0.25, 0.5, 0.75, 1.0] {
        let scores = Scores {
            q: [4.0; 6],
            belief_logit: 0.0,
            belief,
        }
        .for_controller(Controller::StructuredValue);
        assert_eq!(scores.q[0], 0.0);
        assert_eq!(scores.q[4] + scores.q[5], 0.0);
        assert_eq!(scores.q[5], 2.0 * belief - 1.0);
    }
}
