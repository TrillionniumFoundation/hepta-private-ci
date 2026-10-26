//! Full-row, bounded-buffer parity of the actual native classifier. No labels
//! are consumed; all four possible class NLLs and the first-tie argmax are checked.
use crate::ensure;
use crate::report;
use crate::Result;
use codex_hepta_neuron::TrainedCellBundleV5;
use codex_hepta_neuron::TrainedCellInputBindingV5;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde_json::json;
use serde_json::Value;
use sha2::Digest;
use sha2::Sha256;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
#[path = "streaming_header_v8.rs"]
mod header;
pub use header::Inputs;
pub use header::CHUNK_ROWS;

fn vector<const N: usize>(bytes: &[u8]) -> Result<[f64; N]> {
    ensure(bytes.len() == N * 8, "complete floating row required")?;
    let mut result = [0.0; N];
    for (value, encoded) in result.iter_mut().zip(bytes.chunks_exact(8)) {
        *value = f64::from_be_bytes(encoded.try_into()?);
    }
    ensure(result.iter().all(|v| v.is_finite()), "nonfinite stream row")?;
    Ok(result)
}
fn argmax(values: &[f64]) -> usize {
    values.iter().enumerate().skip(1).fold(
        0,
        |best, (index, value)| if *value > values[best] { index } else { best },
    )
}

impl Inputs {
    pub fn verify_family(&self, protocol: &str) -> Result<()> {
        ensure(
            self.header["protocol_sha256"] == protocol
                && self.manifest["protocol_sha256"] == protocol,
            "stream protocol differs",
        )
    }
    pub fn compare_unpublished(&self, index: usize) -> Result<Value> {
        let version = &self.header["versions"][index];
        let bundle = TrainedCellBundleV5::decode(
            &self.payloads[index],
            report::hash(version, "payload_sha256")?,
        )?;
        self.compare_bundle(index, &bundle)
    }
    pub fn compare_bundle(&self, index: usize, bundle: &TrainedCellBundleV5) -> Result<Value> {
        let version = &self.header["versions"][index];
        ensure(
            bundle.content_digest() == report::hash(version, "payload_sha256")?,
            "stream used another serving artifact",
        )?;
        let binding = TrainedCellInputBindingV5 {
            generation: Generation::new(header::count(version, "generation")?)?,
            encoder_digest: report::hash(version, "encoder_sha256")?,
            projection_digest: report::hash(version, "projection_sha256")?,
            normalization_digest: report::hash(version, "normalization_sha256")?,
        };
        let mut vectors = header::open(
            &self.root.join("vectors.bin"),
            header::count(&self.header, "vectors_bytes")?,
        )?;
        let mut expected = header::open(
            &self.root.join("expected.bin"),
            header::count(&self.header, "expected_bytes")?,
        )?;
        let mut maximum = [0_f64; 3];
        let mut predictions = 0_u64;
        let mut cases = Vec::new();
        let mut raw_buffer = vec![0_u8; CHUNK_ROWS * 384 * 8];
        let mut reference_buffer = vec![0_u8; CHUNK_ROWS * 8 * 8];
        for case in report::array(version, "cases")? {
            let cell = StableId::new(report::string(case, "cell_id")?)?;
            let task = report::array(&self.header, "tasks")?
                .iter()
                .find(|t| t["task"] == case["task"])
                .ok_or("task absent")?;
            vectors.seek(SeekFrom::Start(header::count(task, "offset_bytes")?))?;
            expected.seek(SeekFrom::Start(header::count(case, "offset_bytes")?))?;
            let rows = header::count(case, "rows")?;
            let mut completed = 0;
            let mut blocks = 0;
            let mut raw_hash = Sha256::new();
            let mut reference_hash = Sha256::new();
            while completed < rows {
                let n = (rows - completed).min(CHUNK_ROWS as u64) as usize;
                let raw = &mut raw_buffer[..n * 384 * 8];
                let reference = &mut reference_buffer[..n * 8 * 8];
                vectors.read_exact(raw)?;
                expected.read_exact(reference)?;
                raw_hash.update(&*raw);
                reference_hash.update(&*reference);
                for (raw, reference) in raw.chunks_exact(384 * 8).zip(reference.chunks_exact(8 * 8))
                {
                    let x = vector::<384>(raw)?;
                    let y = vector::<8>(reference)?;
                    let output = bundle.evaluate(&binding, &cell, &x)?;
                    ensure(
                        !output.authority.grants_any()
                            && output.parameter_digest == bundle.content_digest(),
                        "stream output authority or parameter identity differs",
                    )?;
                    for class in 0..4 {
                        ensure(
                            (0.0..=1.0).contains(&y[4 + class]),
                            "invalid reference probability",
                        )?;
                        maximum[0] = maximum[0].max((output.logits[class] - y[class]).abs());
                        maximum[1] =
                            maximum[1].max((output.probabilities[class] - y[4 + class]).abs());
                        let actual = -output.probabilities[class].max(f64::MIN_POSITIVE).ln();
                        let wanted = -y[4 + class].max(f64::MIN_POSITIVE).ln();
                        maximum[2] = maximum[2].max((actual - wanted).abs());
                    }
                    ensure(
                        argmax(&output.probabilities) == argmax(&y[4..]),
                        "stream class prediction differs",
                    )?;
                    predictions += 1;
                }
                completed += n as u64;
                blocks += 1;
            }
            let raw_hash = Digest32::from_array(raw_hash.finalize().into());
            let reference_hash = Digest32::from_array(reference_hash.finalize().into());
            ensure(
                raw_hash == report::hash(task, "sha256")?
                    && reference_hash == report::hash(case, "sha256")?,
                "stream changed between validation and actual full-row inference",
            )?;
            cases.push(json!({"cell_id":cell.as_str(),"rows_inferred":completed,"blocks":blocks,
                "task_stream_sha256":raw_hash.to_string(),"reference_case_sha256":reference_hash.to_string()}));
        }
        ensure(
            maximum.iter().all(|v| v.is_finite() && *v <= 1e-12),
            "full-row native parity exceeds fixed tolerance",
        )?;
        Ok(
            json!({"schema":"hepta.native-stream-parity-result.v8","version":version["name"],
            "header_sha256":self.header_digest.to_string(),"all_heads":12,"prediction_rows":predictions,
            "logits_checked":4*predictions,"probabilities_checked":4*predictions,"class_nlls_checked":4*predictions,
            "argmax_predictions_checked":predictions,"maximum_absolute_logit_error":maximum[0],
            "maximum_absolute_probability_error":maximum[1],"maximum_all_class_nll_error":maximum[2],
            "chunk_rows":CHUNK_ROWS,"raw_buffer_bytes":CHUNK_ROWS*384*8,"reference_buffer_bytes":CHUNK_ROWS*8*8,
            "cases":cases,"labels_read":false,"row_subsampling":false,"production_authority":false}),
        )
    }
}
