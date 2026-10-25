//! Bind the reviewed conversion commitment to the actual typed payload.
//! The converter checks tensors/state; the independent sealed-run audit remains
//! responsible for their ancestry and for the evaluation's statistical inputs.

use crate::Result;
use crate::ensure;
use crate::report::HEADS;
use crate::report::SEEDS;
use crate::report::TASKS;
use crate::report::array;
use crate::report::hash;
use crate::report::read;
use crate::report::string;
use codex_hepta_neuron::TrainedCellBundleV5;
use codex_hepta_neuron::TrainedCellInputBindingV5;
use codex_hepta_neuron::trained_cell_normalization_digest_v5;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use serde_json::Value;
use std::collections::BTreeSet;
use std::path::Path;

pub fn verify(gate: &Value, conversion: &Path, predecessor: &[u8], candidate: &[u8]) -> Result<()> {
    let bytes = read(conversion)?;
    let conversion: Value = serde_json::from_slice(&bytes)?;
    ensure(
        Digest32::of_bytes(&bytes) == hash(gate, "conversion_manifest_sha256")?
            && hash(&conversion, "protocol_sha256")? == hash(gate, "protocol_sha256")?
            && conversion["schema"] == "hepta.trained-cell-parity-input.v5"
            && ["fresh-v5-unreviewed", "fresh-v6-unreviewed"]
                .contains(&string(&conversion, "scope")?)
            && conversion["production_authority"] == false
            && conversion["scientific_acceptance"] == false,
        "conversion scope/binding differs",
    )?;
    let versions = array(&conversion, "versions")?;
    ensure(versions.len() == 2, "two typed versions required")?;
    let mut expected = BTreeSet::new();
    for task in TASKS {
        for head in HEADS {
            for seed in SEEDS {
                expected.insert(format!("{task}-{head}-seed{seed}"));
            }
        }
    }
    for (index, payload) in [predecessor, candidate].iter().enumerate() {
        let meta = &versions[index];
        let expected_digest = hash(meta, "payload_sha256")?;
        let bundle = TrainedCellBundleV5::decode(payload, expected_digest)?;
        let names = ["predecessor", "candidate"];
        let ids = ["all12-typed-warmup-v5", "all12-typed-candidate-v5"];
        ensure(
            bundle.artifact_id().as_str() == ids[index]
                && meta["artifact_id"] == ids[index]
                && meta["name"] == names[index]
                && bundle.generation().get() == index as u64 + 1
                && meta["generation"] == index as u64 + 1
                && hash(meta, "source_bundle_sha256")?
                    == hash(gate, &format!("source_{}_bundle_sha256", names[index]))?,
            "typed artifact provenance differs",
        )?;
        let binding = TrainedCellInputBindingV5 {
            generation: Generation::new(index as u64 + 1)?,
            encoder_digest: hash(meta, "encoder_sha256")?,
            projection_digest: hash(meta, "projection_sha256")?,
            normalization_digest: trained_cell_normalization_digest_v5(),
        };
        ensure(
            bundle.input_binding() == binding
                && hash(meta, "normalization_sha256")? == binding.normalization_digest,
            "typed input contract differs",
        )?;
        let actual: BTreeSet<_> = bundle
            .heads()
            .iter()
            .map(|h| h.cell_id().as_str().to_owned())
            .collect();
        let heads = array(meta, "heads")?;
        let mut seen = BTreeSet::new();
        ensure(
            actual == expected && heads.len() == 12 && bundle.heads().len() == 12,
            "typed all12 family differs",
        )?;
        for head in heads {
            let cell = string(head, "cell_id")?;
            let native = bundle
                .heads()
                .iter()
                .find(|h| h.cell_id().as_str() == cell)
                .ok_or("unknown typed head")?;
            let task = string(head, "task")?;
            let mode = string(head, "head")?;
            let seed = head["seed"].as_u64().ok_or("seed missing")?;
            ensure(
                seen.insert(cell)
                    && TASKS.contains(&task)
                    && HEADS.contains(&mode)
                    && SEEDS.contains(&seed)
                    && cell == format!("{task}-{mode}-seed{seed}")
                    && native.training_state_digest() == hash(head, "training_state_sha256")?
                    && native.feature_identity_digest() == hash(head, "feature_identity_sha256")?,
                "typed state/feature commitment differs",
            )?;
        }
    }
    Ok(())
}
