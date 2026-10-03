use super::*;

fn view() -> RuntimeView {
    RuntimeView {
        session_id: "session.one".into(),
        session_generation: 1,
        generation: 1,
        revision: 1,
        digest: "1".repeat(64),
        modules: vec!["ui.native".into()],
    }
}

#[test]
fn readiness_requires_later_callback_and_resets() {
    let mut frames = ReadinessFrames::default();
    let view = view();
    assert!(frames.observe(1, &view).unwrap().is_none());
    assert!(frames.observe(1, &view).is_err());
    frames
        .observe(2, &view)
        .unwrap()
        .unwrap()
        .verify_view(&view)
        .unwrap();
    frames.reset();
    assert!(frames.observe(3, &view).unwrap().is_none());
}

#[test]
fn readiness_binds_every_view_axis() {
    let current = view();
    let mut frames = ReadinessFrames::default();
    frames.observe(1, &current).unwrap();
    let witness = frames.observe(2, &current).unwrap().unwrap();
    for axis in 0..6 {
        let mut changed = current.clone();
        match axis {
            0 => changed.session_id = "session.two".into(),
            1 => changed.session_generation += 1,
            2 => changed.generation += 1,
            3 => changed.revision += 1,
            4 => changed.digest = "2".repeat(64),
            _ => changed.modules = vec!["runtime.agentd".into()],
        }
        assert!(witness.verify_view(&changed).is_err());
        frames.reset();
        assert!(frames.observe(3, &current).unwrap().is_none());
        assert!(frames.observe(4, &changed).unwrap().is_none());
        assert!(frames.observe(5, &changed).unwrap().is_some());
    }
}
