use crate::*;
use std::collections::BTreeSet;

pub struct Inputs {
    pub manifest: Value,
    pub vectors: Vec<u8>,
    pub expected: Vec<u8>,
    pub payloads: [Vec<u8>; 2],
}

pub fn hash(value: &Value) -> Result<Digest32> {
    let text = value.as_str().ok_or("digest must be text")?;
    ensure(text.len() == 64 && text.is_ascii(), "invalid digest")?;
    let mut bytes = [0; 32];
    for (index, byte) in bytes.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&text[index * 2..index * 2 + 2], 16)?;
    }
    Ok(Digest32::from_array(bytes))
}
pub fn count(value: &Value) -> Result<usize> {
    Ok(usize::try_from(
        value.as_u64().ok_or("nonnegative integer required")?,
    )?)
}
pub fn label(value: &Value) -> Result<&str> {
    value.as_str().ok_or_else(|| "text required".into())
}

impl Inputs {
    pub fn verify_family(&self, protocol_sha: &str, tasks: [&str; 2]) -> Result<()> {
        ensure(
            self.manifest["protocol_sha256"] == protocol_sha,
            "parity protocol differs",
        )?;
        let actual_tasks: BTreeSet<_> = self.manifest["tasks"]
            .as_array()
            .ok_or("tasks required")?
            .iter()
            .map(|task| label(&task["task"]))
            .collect::<Result<_>>()?;
        ensure(
            actual_tasks == BTreeSet::from(tasks),
            "parity task census differs",
        )?;
        let mut expected = BTreeMap::new();
        for task in tasks {
            for mode in ["linear", "gated"] {
                for seed in [7, 17, 29] {
                    expected.insert(format!("{task}-{mode}-seed{seed}"), (task, mode, seed));
                }
            }
        }
        for (index, version) in self.manifest["versions"]
            .as_array()
            .ok_or("versions required")?
            .iter()
            .enumerate()
        {
            let bundle = TrainedCellBundleV5::decode(
                &self.payloads[index],
                hash(&version["payload_sha256"])?,
            )?;
            let heads = version["heads"]
                .as_array()
                .ok_or("head metadata required")?;
            ensure(heads.len() == 12, "head metadata census differs")?;
            let mut seen = BTreeSet::new();
            for head in heads {
                let cell = label(&head["cell_id"])?;
                let (task, mode, seed) = expected.get(cell).ok_or("unregistered native head")?;
                let native = bundle
                    .heads()
                    .iter()
                    .find(|h| h.cell_id().as_str() == cell)
                    .ok_or("native head missing")?;
                ensure(
                    seen.insert(cell)
                        && head["task"] == *task
                        && head["head"] == *mode
                        && head["seed"] == *seed
                        && native.training_state_digest() == hash(&head["training_state_sha256"])?
                        && native.feature_identity_digest()
                            == hash(&head["feature_identity_sha256"])?,
                    "head provenance mapping differs",
                )?;
            }
            for case in version["cases"].as_array().ok_or("cases required")? {
                let (task, _, _) = expected
                    .get(label(&case["cell_id"])?)
                    .ok_or("unregistered parity head")?;
                ensure(case["task"] == *task, "parity case task mapping differs")?;
            }
        }
        Ok(())
    }

    pub fn load(root: &Path) -> Result<Self> {
        let bytes = fs::read(root.join("manifest.json"))?;
        ensure(bytes.len() <= 1_048_576, "manifest too large")?;
        let manifest: Value = serde_json::from_slice(&bytes)?;
        ensure(
            manifest["schema"] == "hepta.trained-cell-parity-input.v5"
                && manifest["authority"] == "DENY_ALL"
                && manifest["production_authority"] == false
                && manifest["scientific_acceptance"] == false
                && manifest["absolute_tolerance"].as_f64() == Some(1e-12),
            "unexpected parity policy",
        )?;
        ensure(
            hash(&manifest["compatibility_sha256"])? == trained_cell_compatibility_digest_v5(),
            "schema differs",
        )?;
        let vectors = fs::read(root.join("vectors.bin"))?;
        let expected = fs::read(root.join("expected.bin"))?;
        ensure(
            vectors.len() <= 128 * 1024 * 1024
                && expected.len() <= 128 * 1024 * 1024
                && Digest32::of_bytes(&vectors) == hash(&manifest["vectors_sha256"])?
                && Digest32::of_bytes(&expected) == hash(&manifest["expected_sha256"])?,
            "parity bytes differ",
        )?;
        let tasks = manifest["tasks"].as_array().ok_or("tasks required")?;
        ensure(tasks.len() == 2, "two tasks required")?;
        let mut offset = 0;
        for task in tasks {
            let rows = count(&task["rows"])?;
            ensure(
                rows > 0 && rows <= 16384 && count(&task["offset_bytes"])? == offset,
                "raw coverage differs",
            )?;
            offset += rows * 384 * 8;
        }
        ensure(offset == vectors.len(), "raw vector census differs")?;
        let payloads = [
            fs::read(root.join("predecessor.bin"))?,
            fs::read(root.join("candidate.bin"))?,
        ];
        let versions = manifest["versions"].as_array().ok_or("versions required")?;
        ensure(versions.len() == 2, "two versions required")?;
        offset = 0;
        for (index, version) in versions.iter().enumerate() {
            let bundle =
                TrainedCellBundleV5::decode(&payloads[index], hash(&version["payload_sha256"])?)?;
            ensure(
                bundle.encode() == payloads[index]
                    && bundle.artifact_id().as_str() == label(&version["artifact_id"])?
                    && bundle.generation().get() == (index + 1) as u64
                    && count(&version["generation"])? == index + 1
                    && bundle.heads().len() == 12,
                "typed roundtrip or identity differs",
            )?;
            let cases = version["cases"].as_array().ok_or("cases required")?;
            let native: BTreeSet<_> = bundle
                .heads()
                .iter()
                .map(|h| h.cell_id().as_str())
                .collect();
            let mut ids = BTreeSet::new();
            ensure(cases.len() == 12, "all 12 heads required")?;
            for case in cases {
                ensure(
                    ids.insert(label(&case["cell_id"])?),
                    "duplicate parity head",
                )?;
                let task = tasks
                    .iter()
                    .find(|t| t["task"] == case["task"])
                    .ok_or("unknown parity task")?;
                ensure(
                    case["rows"] == task["rows"] && count(&case["offset_bytes"])? == offset,
                    "reference coverage differs",
                )?;
                offset += count(&case["rows"])? * 8 * 8;
            }
            ensure(ids == native, "native head census differs")?;
        }
        ensure(offset == expected.len(), "reference census differs")?;
        Ok(Self {
            manifest,
            vectors,
            expected,
            payloads,
        })
    }
}

fn vector<const N: usize>(bytes: &[u8], offset: usize) -> Result<[f64; N]> {
    let selected = bytes
        .get(offset..offset + N * 8)
        .ok_or("out of bounds vector")?;
    let mut output = [0.0; N];
    for (target, encoded) in output.iter_mut().zip(selected.chunks_exact(8)) {
        *target = f64::from_be_bytes(encoded.try_into()?);
    }
    ensure(
        output.iter().all(|x| x.is_finite()),
        "nonfinite parity input",
    )?;
    Ok(output)
}

pub fn compare(
    inputs: &Inputs,
    index: usize,
    typed: &mut OwnerTypedSelectedCandidateV5<TrainedCellBundleV5>,
    owner: &LearningArtifactOwnerService,
    now: u64,
) -> Result<Value> {
    typed.with_owner(owner, now, |bundle| compare_bundle(inputs, index, bundle))?
}

pub fn compare_unpublished(inputs: &Inputs, index: usize) -> Result<Value> {
    let bundle = TrainedCellBundleV5::decode(
        &inputs.payloads[index],
        hash(&inputs.manifest["versions"][index]["payload_sha256"])?,
    )?;
    compare_bundle(inputs, index, &bundle)
}

fn compare_bundle(inputs: &Inputs, index: usize, bundle: &TrainedCellBundleV5) -> Result<Value> {
    let version = &inputs.manifest["versions"][index];
    let binding = TrainedCellInputBindingV5 {
        generation: Generation::new(count(&version["generation"])? as u64)?,
        encoder_digest: hash(&version["encoder_sha256"])?,
        projection_digest: hash(&version["projection_sha256"])?,
        normalization_digest: hash(&version["normalization_sha256"])?,
    };
    let mut maximum = [0_f64; 2];
    let mut predictions = 0usize;
    for case in version["cases"].as_array().ok_or("cases missing")? {
        let cell = id(label(&case["cell_id"])?)?;
        let task = inputs.manifest["tasks"]
            .as_array()
            .ok_or("tasks missing")?
            .iter()
            .find(|t| t["task"] == case["task"])
            .ok_or("task missing")?;
        let raw_start = count(&task["offset_bytes"])?;
        let expected_start = count(&case["offset_bytes"])?;
        let rows = count(&case["rows"])?;
        for row in 0..rows {
            let raw = vector::<384>(&inputs.vectors, raw_start + row * 384 * 8)?;
            let expected = vector::<8>(&inputs.expected, expected_start + row * 8 * 8)?;
            let output = bundle.evaluate(&binding, &cell, &raw)?;
            ensure(
                !output.authority.grants_any()
                    && output.parameter_digest == hash(&version["payload_sha256"])?,
                "output authority or parameter binding differs",
            )?;
            for column in 0..4 {
                maximum[0] = maximum[0].max((output.logits[column] - expected[column]).abs());
                maximum[1] =
                    maximum[1].max((output.probabilities[column] - expected[column + 4]).abs());
            }
            predictions += 1;
        }
    }
    ensure(
        maximum.iter().all(|error| *error <= 1e-12),
        "native parity tolerance exceeded",
    )?;
    Ok(
        json!({"version":version["name"],"all_heads":12,"predictions":predictions,
        "maximum_absolute_logit_error":maximum[0],"maximum_absolute_probability_error":maximum[1],"absolute_tolerance":1e-12,"passed":true}),
    )
}
