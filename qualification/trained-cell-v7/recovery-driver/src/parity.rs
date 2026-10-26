include!("../../../trained-cell-v5/driver/src/parity.rs");

pub fn compare_handoff(
    inputs: &Inputs,
    index: usize,
    typed: &mut OwnerTypedSelectedCandidateV5<crate::handoff_version::Handoff>,
    owner: &LearningArtifactOwnerService,
    now: u64,
) -> Result<Value> {
    typed.with_owner(owner, now, |bundle| {
        compare_bundle(inputs, index, bundle.serving())
    })?
}
