use codex_hepta_neuron::SparseConfig;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
#[test]
fn root_and_compiler_use_identical_original_sparse_factual_diff()
-> Result<(), Box<dyn std::error::Error>> {
    let native = SparseConfig {
        model_digest: Digest32::of_bytes(b"fixed heads"),
        normalization_digest: Digest32::of_bytes(b"normalization"),
        generation: Generation::new(2)?,
        width: 10,
        top_k: 1,
        temporal_decay_q24: 1 << 23,
        inhibition_gain_q24: 0,
        inhibition: vec![],
        activity_decay_q24: 1 << 23,
        target_activity_q24: 1 << 20,
        threshold_rate_q24: 1 << 10,
        threshold_min_q24: 0,
        threshold_max_q24: 1 << 24,
        eligibility_decay_q24: 1 << 23,
    };
    let candidate = StableId::new("actual.governed.update")?;
    let actual_native = Digest32::of_bytes(b"original released model receipt");
    let bytes =
        crate::sparse_cpu_neuron_parameter_diff_v2(&native, &candidate, actual_native, &[])?;
    assert_eq!(
        String::from_utf8(bytes)?,
        format!(
            "profile=neuron.sparse.rates.q24.v1\nbaseline={}\ncandidate={}\nmodel_advice_receipt={}\ndeltas=[]\n",
            native.digest()?,
            candidate,
            actual_native
        )
    );
    Ok(())
}
