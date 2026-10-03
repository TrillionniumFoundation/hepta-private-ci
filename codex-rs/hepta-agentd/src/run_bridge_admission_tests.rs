use super::*;
#[path = "run_bridge_admission_fixture.rs"]
mod fixture;
use super::super::DurableAgentRunCoordinator;
use codex_hepta_infer_core::control_contracts::TrustRole;
use fixture::*;

type TestResult = Result<(), Box<dyn std::error::Error>>;

#[test]
fn retained_owner_is_unchanged_and_reopen_requires_fresh_validation() -> TestResult {
    let mut f = fixture()?;
    let path = f.dir.path().join("runs.json");
    let bytes = std::fs::read(&path)?;
    {
        let mut admitted = f
            .host
            .validate(&mut f.owner, &f.signed, &f.proof, &f.binding)?;
        admitted.revalidate()?;
    }
    assert_eq!(std::fs::read(&path)?, bytes);
    let composition = f.owner.composition().clone();
    drop(f.owner);
    let mut reopened =
        DurableAgentRunCoordinator::open(composition, path).map_err(|e| format!("{e:?}"))?;
    f.host
        .validate(&mut reopened, &f.signed, &f.proof, &f.binding)?
        .revalidate()?;
    Ok(())
}

#[test]
fn signature_role_and_revocation_are_independently_checked() -> TestResult {
    for case in 0..3 {
        let mut f = fixture()?;
        match case {
            0 => f.signed.signatures[0].signature[0] ^= 1,
            1 => {
                f.current.0.lock().map_err(|_| "host lock")?.keys[0].role = TrustRole::DataAuthority
            }
            2 => {
                f.current.0.lock().map_err(|_| "host lock")?.keys[0].revoked_at_authority_epoch =
                    Some(3)
            }
            _ => unreachable!(),
        }
        assert!(matches!(
            f.host
                .validate(&mut f.owner, &f.signed, &f.proof, &f.binding),
            Err(RunBridgeAdmissionError::InvalidAuthority)
        ));
    }
    Ok(())
}

#[test]
fn run_context_plan_revision_and_generation_relabeling_are_rejected() -> TestResult {
    for case in 0..8 {
        let mut f = fixture()?;
        match case {
            0 => f.binding.identity.run_id = "another-run".into(),
            1 => f.binding.identity.request_id = "another-request".into(),
            2 => f.binding.identity.owner_dispatch_revision += 1,
            3 => f.binding.identity.context_sha256 = Sha256Digest::for_bytes(b"different context"),
            4 => {
                f.binding.identity.envelope_sha256 = Sha256Digest::for_bytes(b"different envelope")
            }
            5 => {
                f.binding.identity.execution_binding_sha256 =
                    Sha256Digest::for_bytes(b"different plan")
            }
            6 => f.binding.identity.owner_generation += 1,
            7 => f.binding.identity.fence_sha256 = Sha256Digest::for_bytes(b"different fence"),
            _ => unreachable!(),
        }
        assert!(
            f.host
                .validate(&mut f.owner, &f.signed, &f.proof, &f.binding)
                .is_err()
        );
    }
    Ok(())
}

#[test]
fn stale_currentness_and_movement_during_validation_fail_closed() -> TestResult {
    for case in 0..9 {
        let mut f = fixture()?;
        {
            let mut state = f.current.0.lock().map_err(|_| "host lock")?;
            match case {
                0 => state.generation += 1,
                1 => state.epoch += 1,
                2 => state.now = 60_000,
                3 => state.move_during_check = true,
                4 => state.rollback_during_check = true,
                5 => state.available = false,
                6 => state.revision = 0,
                7 => state.configuration = Sha256Digest::for_bytes(b"another configuration"),
                8 => state.ports = Sha256Digest::for_bytes(b"another ports root"),
                _ => unreachable!(),
            }
        }
        assert!(
            f.host
                .validate(&mut f.owner, &f.signed, &f.proof, &f.binding)
                .is_err()
        );
    }
    Ok(())
}

#[test]
fn failed_revalidation_cannot_be_revived_by_restoring_host_values() -> TestResult {
    for case in 0..4 {
        let mut f = fixture()?;
        let mut admitted = f
            .host
            .validate(&mut f.owner, &f.signed, &f.proof, &f.binding)?;
        {
            let mut state = f.current.0.lock().map_err(|_| "host lock")?;
            match case {
                0 => state.generation += 1,
                1 => state.revision += 1,
                2 => state.now = 60_000,
                3 => state.now = 99,
                _ => unreachable!(),
            }
        }
        assert!(admitted.revalidate().is_err());
        {
            let mut state = f.current.0.lock().map_err(|_| "host lock")?;
            state.generation = 8;
            state.revision = 1;
            state.now = 100;
        }
        assert_eq!(
            admitted.revalidate(),
            Err(RunBridgeAdmissionError::CurrentnessChanged)
        );
    }
    Ok(())
}

#[test]
fn retained_integrity_failure_fences_the_scoped_result() -> TestResult {
    let mut f = fixture()?;
    let path = f.dir.path().join("runs.json");
    let bytes = std::fs::read(&path)?;
    let mut admitted = f
        .host
        .validate(&mut f.owner, &f.signed, &f.proof, &f.binding)?;
    std::fs::write(&path, b"{}").map_err(|e| format!("{e}"))?;
    assert!(admitted.revalidate().is_err());
    std::fs::write(&path, bytes)?;
    assert!(admitted.revalidate().is_err());
    Ok(())
}

#[test]
fn dispatched_reopened_and_retired_destination_runs_never_reacquire_admission() -> TestResult {
    for retired in [false, true] {
        let mut f = fixture()?;
        f.owner
            .mark_dispatched(100, "bridge-run", 2)
            .map_err(|e| format!("{e:?}"))?;
        if retired {
            f.owner
                .observe_terminal("bridge-run", 3, RunPhase::Succeeded, true)
                .map_err(|e| format!("{e:?}"))?;
            f.owner
                .remove_closed_run("bridge-run", 4)
                .map_err(|e| format!("{e:?}"))?;
        }
        let composition = f.owner.composition().clone();
        drop(f.owner);
        let mut reopened =
            DurableAgentRunCoordinator::open(composition, f.dir.path().join("runs.json"))
                .map_err(|e| format!("{e:?}"))?;
        assert!(
            f.host
                .validate(&mut reopened, &f.signed, &f.proof, &f.binding)
                .is_err()
        );
    }
    Ok(())
}

#[test]
fn host_must_advance_revision_for_every_trust_snapshot_change() -> TestResult {
    let mut f = fixture()?;
    let mut admitted = f
        .host
        .validate(&mut f.owner, &f.signed, &f.proof, &f.binding)?;
    {
        let mut state = f.current.0.lock().map_err(|_| "host lock")?;
        let mut extra = state.keys[0].clone();
        extra.key_id = "new-unrelated-key".into();
        extra.signer_id = "reconciliation-authority".into();
        extra.role = TrustRole::ReconciliationIssuer;
        extra.verifying_key = ed25519_dalek::SigningKey::from_bytes(&[8; 32])
            .verifying_key()
            .to_bytes();
        state.keys.push(extra);
    }
    // An unrelated key does not affect the four signatures. This documents the
    // host contract: the adapter does not independently fingerprint trust bytes.
    admitted.revalidate()?;
    f.current.0.lock().map_err(|_| "host lock")?.revision += 1;
    assert_eq!(
        admitted.revalidate(),
        Err(RunBridgeAdmissionError::CurrentnessChanged)
    );
    Ok(())
}

#[test]
fn closed_retained_admissions_cannot_be_overridden_by_a_ready_host() -> TestResult {
    let mut f = fixture()?;
    f.owner.close_admissions().map_err(|e| format!("{e:?}"))?;
    assert!(matches!(
        f.host
            .validate(&mut f.owner, &f.signed, &f.proof, &f.binding),
        Err(RunBridgeAdmissionError::Owner(
            AgentRunError::AdmissionClosed
        ))
    ));
    Ok(())
}
