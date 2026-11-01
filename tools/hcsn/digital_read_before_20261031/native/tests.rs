use crate::cell;
use crate::policy;
use crate::store;
use crate::task;

fn public(delay: usize) -> task::Public {
    task::Public {
        schema: "digital-read-before-public-v1".into(),
        id: "fixture".into(),
        deadline: 6,
        initial_budget: 3,
        duration: vec![1.; 6],
        reliability: vec![0.75; 6],
        read_price: vec![0.1; 6],
        read_delay: vec![delay; 6],
        packets: (0..6).map(|i| format!("p{i}.json")).collect(),
        packet_sha256: vec!["a".repeat(64); 6],
        latency_price: 0.02,
        repair_price: 0.3,
        failure_probability: 0.1,
    }
}

#[test]
fn delay_two_requires_another_advancing_action_and_retains_source_reliability() {
    let mut p = public(2);
    p.reliability[1] = 0.9;
    let before = task::State::initial();
    assert_eq!(before.due(&p, 2).unwrap(), None);
    let pending = before.successor(&p, 2, None).unwrap();
    assert_eq!(pending.tick, 1);
    assert_eq!(pending.budget, 2);
    assert!(pending.history.is_empty());
    assert!((pending.charges - 0.12).abs() < 1e-12);
    assert_eq!(pending.due(&p, 1).unwrap(), Some(0));
    let success = task::Completion {
        failure: false,
        observation: Some(1),
    };
    let after = pending.successor(&p, 1, Some(&success)).unwrap();
    assert!(after.pending.is_none());
    assert_eq!(after.last_symbol, 1);
    assert_eq!(after.last_reliability, 0.75);
    assert_eq!(after.history[0].source_tick, 0);
}

#[test]
fn terminal_actions_cancel_pending_without_completion_time_or_refund() {
    let p = public(2);
    let pending = task::State::initial().successor(&p, 2, None).unwrap();
    for action in [0, 4, 5] {
        assert_eq!(pending.due(&p, action).unwrap(), None);
        let after = pending.successor(&p, action, None).unwrap();
        assert!(after.terminal && after.pending.is_none());
        assert_eq!(after.elapsed, pending.elapsed);
        assert_eq!(after.charges, pending.charges);
        assert_eq!(after.budget, pending.budget);
        assert!(after.history.is_empty());
    }
}

#[test]
fn failed_read_preserves_cost_and_repair_is_explicit() {
    let p = public(1);
    let failure = task::Completion {
        failure: true,
        observation: None,
    };
    let broken = task::State::initial()
        .successor(&p, 2, Some(&failure))
        .unwrap();
    assert!(broken.broken && broken.pending.is_none());
    assert!(!broken.legal(&p)[2] && broken.legal(&p)[3]);
    assert!((broken.charges - 0.12).abs() < 1e-12);
    let waiting = broken.successor(&p, 1, None).unwrap();
    assert!(waiting.broken);
    let repaired = waiting.successor(&p, 3, None).unwrap();
    assert!(!repaired.broken);
    assert!((repaired.charges - 0.46).abs() < 1e-12);
}

#[test]
fn illegal_actions_and_unsolicited_completion_are_rejected() {
    let p = public(2);
    let s = task::State::initial();
    assert!(s.successor(&p, 3, None).is_err());
    assert!(s.successor(&p, 6, None).is_err());
    let completion = task::Completion {
        failure: false,
        observation: Some(0),
    };
    assert!(s.successor(&p, 1, Some(&completion)).is_err());
    let pending = s.successor(&p, 2, None).unwrap();
    assert!(pending.successor(&p, 2, None).is_err());
    assert!(pending.successor(&p, 1, None).is_err());
    assert_eq!(s, task::State::initial());
}

#[test]
fn deadline_masks_all_advancing_actions_and_raw_history_has_no_hidden_target() {
    let p = public(1);
    let mut s = task::State::initial();
    for _ in 0..6 {
        s = s.successor(&p, 1, None).unwrap();
    }
    assert_eq!(s.legal(&p), [true, false, false, false, true, true]);
    assert_eq!(s.history_features(), [0.; 12]);
    assert_eq!(s.public_features(&p).len(), 36);
    assert_eq!(task::public_names().len(), 36);
    assert_eq!(cell::representation_names("raw_history").len(), 12);
}

#[test]
fn splitmix64_known_vector_and_exact_hard_event_transition() {
    let mut context = cell::Context {
        dt: 1.,
        symbol: 0.,
        reliability: 0.5,
        transition: [[0.; 17]; 17],
        event_probability: [0.; 17],
        features: [[0.; 12]; 17],
    };
    for i in 0..17 {
        context.transition[i][i] = 1.;
    }
    context.transition[7][7] = 0.;
    context.transition[7][16] = 1.;
    context.event_probability[7] = 1.;
    let mut s = cell::State::new(0);
    let draw = s.advance(&context).unwrap();
    assert_eq!(s.rng_hex, "9e3779b97f4a7c15");
    assert_eq!(
        draw.uniform,
        (0xe220a8397b1dcdaf_u64 >> 11) as f64 * 2_f64.powi(-53)
    );
    assert_eq!(s.index, 16);
    assert_eq!(s.events, 1);
    assert_eq!(s.draws, 1);
    let next = s.advance(&context).unwrap();
    assert!(!next.event);
    assert_eq!(s.events, 1);
    let recovered: cell::State = serde_json::from_str(&serde_json::to_string(&s).unwrap()).unwrap();
    assert_eq!(s, recovered);
}

#[test]
fn fixed_and_value_controllers_use_learned_scores_and_first_tie() {
    let p = public(1);
    let s = task::State::initial();
    let scores = policy::Scores {
        q: [0.; 6],
        belief_logit: 0.,
        belief: 0.5,
    };
    assert_eq!(
        policy::select(&scores, s.legal(&p), &s, policy::Controller::Fixed).unwrap(),
        2
    );
    assert_eq!(
        policy::select(&scores, s.legal(&p), &s, policy::Controller::Value).unwrap(),
        0
    );
    let confident = policy::Scores {
        q: [0.; 6],
        belief_logit: 2.,
        belief: 0.9,
    };
    assert_eq!(
        policy::select(&confident, s.legal(&p), &s, policy::Controller::Fixed).unwrap(),
        5
    );
}

#[test]
fn content_paths_cannot_use_subdirectories_or_escape_basename() {
    let root = std::path::Path::new("/tmp/research-packets");
    for name in ["", "..", "../a", "/tmp/a", "subdir/a", "."] {
        assert!(store::relative_packet(root, name).is_err());
    }
    assert_eq!(
        store::relative_packet(root, "packet.json").unwrap(),
        root.join("packet.json")
    );
}
