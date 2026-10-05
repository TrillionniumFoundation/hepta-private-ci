//! Historical verification and current commitment are deliberately different.
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::RuntimeTopologyCandidateV1;
use codex_hepta_types::RuntimeTopologyCandidateV2;
use codex_hepta_types::RuntimeTopologyContractErrorV1;
use codex_hepta_types::RuntimeTopologyContractErrorV2;
use codex_hepta_types::RuntimeTopologyDeltaV1;
use codex_hepta_types::RuntimeTopologyDeltaV2;
use codex_hepta_types::RuntimeTopologyOperationV1;
use codex_hepta_types::RuntimeTopologyOperationV2;
use codex_hepta_types::StableId;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;

fn digest(value: &str) -> TestResult<Digest32> {
    Ok(value.parse()?)
}

fn historical() -> TestResult<RuntimeTopologyCandidateV1> {
    Ok(RuntimeTopologyCandidateV1 {
        proposal_digest: digest(
            "ecd1378bc9dc130008f00d58db5d26f60db55934a49b949af7e6f6a8da2a2beb",
        )?,
        candidate_id: StableId::new("candidate-8")?,
        candidate_digest: digest(
            "f7a3653e4cbcf55dd5afea1672b08f0707bfbd31197a26e5b450b30f14b786f6",
        )?,
        baseline_generation: Generation::new(7)?,
        candidate_generation: Generation::new(8)?,
        selected_topology_digest: digest(
            "fa232b9dc6dac7e96f45b416ccb6a69c9943b1834979ebf3bdd6fadc2dac649f",
        )?,
        evaluation_digest: digest(
            "efe77b201dc216c0edf435a227df2b2898d3f6ea1ff16e5d4d0d4ec0cf593271",
        )?,
        rollback_predecessor_digest: digest(
            "fa232b9dc6dac7e96f45b416ccb6a69c9943b1834979ebf3bdd6fadc2dac649f",
        )?,
        changed: true,
        deltas: vec![RuntimeTopologyDeltaV1 {
            module_id: StableId::new("module.alpha")?,
            operation: RuntimeTopologyOperationV1::Add,
            related_module_ids: Vec::new(),
            predecessor_digest: Digest32::ZERO,
            candidate_digest: digest(
                "27e3ad1bd5794e7c5639704ab86fe63a6f01387f14c3380b6a009dd6b5616d5a",
            )?,
            evidence_digest: digest(
                "ff2f2ce7f9577786db39d3dcb0e2b93bf0f583bb0daffbe04fa65b97c4e1b6d7",
            )?,
        }],
    })
}

// A test fixture, not a product migration or a transfer of selection authority.
fn current() -> TestResult<RuntimeTopologyCandidateV2> {
    let old = historical()?;
    Ok(RuntimeTopologyCandidateV2 {
        proposal_digest: old.proposal_digest,
        candidate_id: old.candidate_id,
        candidate_digest: digest(
            "971cb9b9f6f58fa53a3841a5b9ae711899257e38487ea3d15972958da9f66e9e",
        )?,
        baseline_generation: old.baseline_generation,
        candidate_generation: old.candidate_generation,
        selected_topology_digest: old.selected_topology_digest,
        evaluation_digest: old.evaluation_digest,
        rollback_predecessor_digest: old.rollback_predecessor_digest,
        changed: old.changed,
        deltas: old
            .deltas
            .into_iter()
            .map(|delta| RuntimeTopologyDeltaV2 {
                module_id: delta.module_id,
                operation: RuntimeTopologyOperationV2::Add,
                related_module_ids: delta.related_module_ids,
                predecessor_digest: delta.predecessor_digest,
                candidate_digest: delta.candidate_digest,
                evidence_digest: delta.evidence_digest,
            })
            .collect(),
    })
}

#[test]
fn historical_and_current_goldens_validate_only_their_own_commitments() -> TestResult {
    let old = historical()?;
    let new = current()?;
    assert_eq!(old.content_digest(), Ok(old.candidate_digest));
    assert_eq!(new.content_digest(), Ok(new.candidate_digest));
    assert_eq!(old.validate(), Ok(()));
    assert_eq!(new.validate(), Ok(()));
    assert_ne!(old.candidate_digest, new.candidate_digest);
    let crossed_old = RuntimeTopologyCandidateV1 {
        candidate_digest: new.candidate_digest,
        ..old
    };
    let crossed_new = RuntimeTopologyCandidateV2 {
        candidate_digest: crossed_old.content_digest()?,
        ..new
    };
    assert_eq!(
        crossed_old.validate(),
        Err(RuntimeTopologyContractErrorV1::CandidateDigestMismatch)
    );
    assert_eq!(
        crossed_new.validate(),
        Err(RuntimeTopologyContractErrorV2::CandidateDigestMismatch)
    );
    Ok(())
}

#[test]
fn historical_unbound_fields_stay_historical_and_v2_binds_them() -> TestResult {
    let mut old = historical()?;
    let mut new = current()?;
    old.evaluation_digest = Digest32::of_bytes(b"changed evaluation");
    new.evaluation_digest = old.evaluation_digest;
    assert_eq!(old.validate(), Ok(()));
    assert_eq!(
        new.validate(),
        Err(RuntimeTopologyContractErrorV2::CandidateDigestMismatch)
    );
    // Reissuing a V2 commitment produces different evidence; no selection token
    // or authority is returned by the type's public validation/digest API.
    let old_v2_digest = new.candidate_digest;
    new.candidate_digest = new.content_digest()?;
    assert_ne!(new.candidate_digest, old_v2_digest);
    assert_eq!(new.validate(), Ok(()));
    Ok(())
}

#[test]
fn superseded_unversioned_hptc_digest_is_not_a_compatibility_fallback() -> TestResult {
    let intermediate = digest("8a2396058d95d3c0efde025d3e34ec1524d0ffa3a10f2fb8f6457cdb35a195d8")?;
    let old = RuntimeTopologyCandidateV1 {
        candidate_digest: intermediate,
        ..historical()?
    };
    let new = RuntimeTopologyCandidateV2 {
        candidate_digest: intermediate,
        ..current()?
    };
    assert_eq!(
        old.validate(),
        Err(RuntimeTopologyContractErrorV1::CandidateDigestMismatch)
    );
    assert_eq!(
        new.validate(),
        Err(RuntimeTopologyContractErrorV2::CandidateDigestMismatch)
    );
    Ok(())
}
