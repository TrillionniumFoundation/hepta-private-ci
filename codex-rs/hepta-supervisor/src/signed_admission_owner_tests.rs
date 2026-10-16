use super::*;
use crate::H7H89ProductionGrantSigner;
use crate::H7H89ProductionGrantVerifier;
use crate::H7H89ProductionTransition;
use crate::ProductionMutationStatus;
use crate::SignedIntentStatus;
use codex_hepta_memory::H7ArtifactSigner;
use codex_hepta_memory::H7QualificationRuntime;
use codex_hepta_memory::H7SignedArtifactTransition;
use codex_hepta_memory::H7TrajectoryEvent;
use pretty_assertions::assert_eq;

#[test]
fn real_signed_grant_uses_borrowed_slot_and_preserves_revocation_preflight()
-> Result<(), SupervisorError> {
    for mode in ["admit", "revoked target"] {
        let fleet = TestFleet::new()?;
        let source = admitted_release(&fleet, &fleet.first, "grant-source")?;
        let target = admitted_release(&fleet, &fleet.first, "grant-target")?;
        let control = FakeControl::default();
        let now = Instant::now();
        let (mut supervisor, _) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        supervisor.start_release(&fleet.first, source.clone(), now)?;
        control.set_healthy(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        let record = fleet.registry.load()?.agent(&fleet.first).cloned().unwrap();
        let before = supervisor.snapshot(&fleet.first).unwrap();
        let mut h7 = H7QualificationRuntime::new();
        h7.append_trajectory_event(
            H7TrajectoryEvent::new(
                "grant-trajectory",
                /*event_seq*/ 1,
                "reload",
                /*reward_bps*/ 100,
                /*safety_ok*/ true,
                /*authority_epoch*/ 1,
                /*owner_epoch*/ 1,
                /*generation*/ 1,
                Sha256Digest::for_bytes(b"fence"),
            )
            .unwrap(),
        )
        .unwrap();
        h7.evaluate_trajectory("grant-trajectory").unwrap();
        let artifact = h7
            .propose_artifact("grant-artifact", "grant-trajectory", /*generation*/ 1)
            .unwrap();
        let h7_signer =
            H7ArtifactSigner::from_seed("h7-signer", /*signer_epoch*/ 1, [7; 32]).unwrap();
        let envelope = h7_signer
            .sign(
                &artifact,
                /*ope*/ None,
                H7SignedArtifactTransition::Reload,
                /*expected_runtime_generation*/ 0,
                /*predecessor_artifact_sha256*/ None,
                /*issued_at_unix_seconds*/ 100,
                /*expires_at_unix_seconds*/ 200,
            )
            .unwrap();
        let signer =
            H7H89ProductionGrantSigner::from_seed("operator", /*signer_epoch*/ 4, [9; 32]).unwrap();
        let verifier = H7H89ProductionGrantVerifier::new_with_h7_verifier(
            "operator",
            /*signer_epoch*/ 4,
            signer.verifying_key(),
            h7_signer.verifier(),
        )
        .unwrap();
        let grant = signer
            .sign(
                &fleet.first,
                source.identity(),
                target.identity(),
                H7H89ProductionTransition::Upgrade,
                &envelope,
                before.control_revision,
                record.lifecycle.generation,
                /*authority_epoch*/ 3,
                /*issued_at_unix_seconds*/ 100,
                /*expires_at_unix_seconds*/ 200,
            )
            .unwrap();
        if mode == "revoked target" {
            fleet
                .registry
                .revoke_release(&fleet.first, target.release_id())?;
            assert!(
                supervisor
                    .apply_production_grant(
                        &fleet.first,
                        &grant,
                        &envelope,
                        &verifier,
                        /*expected_authority_epoch*/ 3,
                        /*now_unix_seconds*/ 150,
                        now
                    )
                    .is_err()
            );
            assert_eq!(supervisor.snapshot(&fleet.first), Some(before));
            assert_eq!(
                crate::signed_intent::read_intent(record.layout.run_root()).unwrap(),
                None
            );
            assert_eq!(control.counts(&fleet.first), (0, 0, 0));
            continue;
        }
        let receipt = supervisor.apply_production_grant(
            &fleet.first,
            &grant,
            &envelope,
            &verifier,
            /*expected_authority_epoch*/ 3,
            /*now_unix_seconds*/ 150,
            now,
        )?;
        assert_eq!(receipt.status, ProductionMutationStatus::Queued);
        assert_eq!(receipt.control_revision, before.control_revision + 1);
        assert_eq!(
            crate::signed_intent::read_intent(record.layout.run_root())
                .unwrap()
                .unwrap()
                .status,
            SignedIntentStatus::Queued
        );
        assert_eq!(control.counts(&fleet.first), (1, 0, 0));
        assert!(
            supervisor
                .apply_production_grant(
                    &fleet.first,
                    &grant,
                    &envelope,
                    &verifier,
                    /*expected_authority_epoch*/ 3,
                    /*now_unix_seconds*/ 150,
                    now
                )
                .is_err()
        );
        assert_eq!(control.counts(&fleet.first), (1, 0, 0));
        control.set_exit(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        control.set_healthy(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert_eq!(
            supervisor.snapshot(&fleet.first).unwrap().active_release,
            Some(target.identity().to_string())
        );
        assert_eq!(
            crate::signed_intent::read_intent(record.layout.run_root())
                .unwrap()
                .unwrap()
                .status,
            SignedIntentStatus::Committed
        );
    }
    Ok(())
}
