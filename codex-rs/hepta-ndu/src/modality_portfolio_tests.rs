use pretty_assertions::assert_eq;

use super::*;

fn config(policy: PolicyV1) -> ConfigV1 {
    ConfigV1 {
        session_id: 7,
        q_index: 2,
        q_digest: Digest32::of_bytes(b"q"),
        budget_macs: 351_232,
        init_macs: 3_584,
        max_refinements: 2,
        decoder_macs: [6_656, 69_632, 53_248, 200_704],
        refine_macs: [8_704; 4],
        latent_digests: [b"t".as_slice(), b"a", b"i", b"v"].map(Digest32::of_bytes),
        policy,
    }
}

fn table(values: [f64; 5]) -> [ActionValueV1; 5] {
    [
        ActionV1::Emit,
        ActionV1::Refine(ModalityV1::Text),
        ActionV1::Refine(ModalityV1::Audio),
        ActionV1::Refine(ModalityV1::Image),
        ActionV1::Refine(ModalityV1::Video),
    ]
    .map(|action| ActionValueV1 {
        action,
        value: values[match action {
            ActionV1::Emit => 0,
            ActionV1::Refine(m) => 1 + m as usize,
        }],
        cost_macs: if action == ActionV1::Emit {
            330_240
        } else {
            8_704
        },
    })
}

fn choose(owner: &mut SessionV1, values: [f64; 5]) -> Result<ActionValueV1, PortfolioError> {
    let s = owner.snapshot();
    owner.choose(s.session_id, s.version, s.joint_digest(), &table(values))
}

#[test]
fn native_selects_each_modality_and_requires_isolated_feedback() -> Result<(), PortfolioError> {
    for modality in [
        ModalityV1::Text,
        ModalityV1::Audio,
        ModalityV1::Image,
        ModalityV1::Video,
    ] {
        let mut owner = SessionV1::new(config(PolicyV1::Adaptive))?;
        let initial = owner.snapshot();
        let mut values = [-2.0; 5];
        values[1 + modality as usize] = -1.0;
        assert_eq!(
            choose(&mut owner, values)?.action,
            ActionV1::Refine(modality)
        );
        let pending = owner.clone();
        assert_eq!(
            choose(&mut owner, values),
            Err(PortfolioError::PendingExecution)
        );
        let mut changed = initial.latent_digests;
        changed[(modality as usize + 1) % 4] = Digest32::of_bytes(b"unselected mutation");
        assert_eq!(
            owner.confirm_refinement(/*session_id*/ 7, /*version*/ 1, modality, changed),
            Err(PortfolioError::UnrelatedLatentChanged)
        );
        assert_eq!(owner, pending);
        changed = initial.latent_digests;
        changed[modality as usize] = Digest32::of_bytes(b"actual selected update");
        owner.confirm_refinement(/*session_id*/ 7, /*version*/ 1, modality, changed)?;
        assert_eq!(
            owner.choose(
                /*session_id*/ 7,
                /*version*/ 0,
                initial.joint_digest(),
                &table(values)
            ),
            Err(PortfolioError::SnapshotMismatch)
        );
        assert_eq!(
            owner.choose(
                /*session_id*/ 7,
                /*version*/ 1,
                initial.joint_digest(),
                &table(values)
            ),
            Err(PortfolioError::SnapshotMismatch)
        );
    }
    Ok(())
}

#[test]
fn committed_plan_is_immutable_and_emission_seals() -> Result<(), PortfolioError> {
    let mut owner = SessionV1::new(config(PolicyV1::Committed(vec![ModalityV1::Audio; 2])))?;
    for version in 1..=2 {
        let before = owner.clone();
        assert_eq!(
            choose(&mut owner, [0.0, 0.0, -3.0, 4.0, 0.0]),
            Err(PortfolioError::NonZeroIneligible)
        );
        assert_eq!(owner, before);
        assert_eq!(
            choose(&mut owner, [0.0, 0.0, -3.0, 0.0, 0.0])?.action,
            ActionV1::Refine(ModalityV1::Audio)
        );
        let hashes = owner.snapshot().latent_digests;
        owner.confirm_refinement(/*session_id*/ 7, version, ModalityV1::Audio, hashes)?;
    }
    assert_eq!(
        choose(&mut owner, [-1.0, 0.0, 0.0, 0.0, 0.0])?.action,
        ActionV1::Emit
    );
    let state = owner.snapshot();
    assert_eq!(
        (state.counts, state.remaining_macs, state.version),
        ([0, 2, 0, 0], 0, 3)
    );
    let before = owner.clone();
    assert_eq!(
        owner.confirm_emission(
            /*session_id*/ 7,
            /*version*/ 3,
            state.joint_digest(),
            [Digest32::ZERO; 4]
        ),
        Err(PortfolioError::InvalidOutputs)
    );
    assert_eq!(owner, before);
    owner.confirm_emission(
        /*session_id*/ 7,
        /*version*/ 3,
        state.joint_digest(),
        state.latent_digests,
    )?;
    assert_eq!(owner.output_digests(), Some(state.latent_digests));
    assert_eq!(choose(&mut owner, [0.0; 5]), Err(PortfolioError::Sealed));
    assert_eq!(
        owner.confirm_refinement(
            /*session_id*/ 7,
            /*version*/ 3,
            ModalityV1::Audio,
            state.latent_digests
        ),
        Err(PortfolioError::Sealed)
    );
    for policy in [PolicyV1::Clean, PolicyV1::Committed(Vec::new())] {
        let mut owner = SessionV1::new(config(policy))?;
        assert_eq!(
            choose(&mut owner, [-9.0, 0.0, 0.0, 0.0, 0.0])?.action,
            ActionV1::Emit
        );
        assert_eq!(owner.snapshot().remaining_macs, 17_408);
    }
    Ok(())
}

#[test]
fn finite_complete_tables_and_order_independent_ties() -> Result<(), PortfolioError> {
    let base = SessionV1::new(config(PolicyV1::Adaptive))?;
    let s = base.snapshot();
    for value in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
        let mut owner = base.clone();
        assert_eq!(
            choose(&mut owner, [0.0, value, 0.0, 0.0, 0.0]),
            Err(PortfolioError::NonFiniteValue)
        );
        assert_eq!(owner, base);
    }
    for (values, expected) in [
        ([0.0, 1e-12, 0.5e-12, 0.0, 0.0], ActionV1::Emit),
        (
            [-1.0, 0.0, 1e-12, 0.0, 0.0],
            ActionV1::Refine(ModalityV1::Text),
        ),
    ] {
        for rotation in 0..5 {
            let mut owner = base.clone();
            let mut entries = table(values);
            entries.rotate_left(rotation);
            assert_eq!(
                owner
                    .choose(s.session_id, s.version, s.joint_digest(), &entries)?
                    .action,
                expected
            );
        }
    }
    let mut owner = base.clone();
    let mut entries = table([0.0; 5]);
    assert_eq!(
        owner.choose(s.session_id, s.version, s.joint_digest(), &entries[..4]),
        Err(PortfolioError::InvalidTable)
    );
    entries[2] = entries[1];
    assert_eq!(
        owner.choose(s.session_id, s.version, s.joint_digest(), &entries),
        Err(PortfolioError::InvalidTable)
    );
    entries = table([0.0; 5]);
    entries[3].cost_macs -= 1;
    assert_eq!(
        owner.choose(s.session_id, s.version, s.joint_digest(), &entries),
        Err(PortfolioError::CostMismatch)
    );
    assert_eq!(owner, base);
    Ok(())
}
