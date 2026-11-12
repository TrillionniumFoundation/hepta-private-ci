#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Features {
    schema: String,
    rows: Vec<Vec<f64>>,
    candidate_ids: Vec<String>,
    source_manifest_sha256: String,
    head_sha256: String,
    projection_sha256: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Normalization {
    mean: Vec<f64>,
    scale: Vec<f64>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Parameters {
    w1: Vec<Vec<f64>>,
    b1: Vec<f64>,
    w2: Vec<f64>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Trace {
    step: usize,
    batch_sha256: String,
    loss: f64,
    parameters_sha256: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Training {
    steps: usize,
    rows: usize,
    initial_sha256: String,
    final_sha256: String,
    trace: Vec<Trace>,
    elapsed_ns: u64,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Head {
    schema: String,
    scientific_qualified: bool,
    seed: u64,
    normalization: Normalization,
    parameters: Parameters,
    training: Training,
    arm: String,
    training_features_sha256: String,
    training_targets_sha256: String,
    projection_sha256: String,
    code_sha256: String,
}
fn hash(value: &str) -> Result<Digest32> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|v| v.is_ascii_digit() || (b'a'..=b'f').contains(&v))
    {
        return Err("invalid SHA256 binding".into());
    }
    let mut bytes = [0; 32];
    for (i, item) in bytes.iter_mut().enumerate() {
        *item = u8::from_str_radix(&value[i * 2..i * 2 + 2], 16)?;
    }
    Ok(Digest32::from_array(bytes))
}
impl Head {
    fn validate(&self, features: &Features) -> Result<()> {
        let n = self.normalization.mean.len();
        let h = self.parameters.b1.len();
        let t = &self.training;
        let finite = |v: f64| v.is_finite() && v.abs() <= 1e9;
        if self.schema != "perc1.semantic-ranking-head.v1"
            || self.scientific_qualified
            || !matches!(self.arm.as_str(), "global" | "dense")
            || n != 59
            || !(1..=64).contains(&h)
            || self.normalization.scale.len() != n
            || self.parameters.w1.len() != n
            || self.parameters.w1.iter().any(|r| r.len() != h)
            || self.parameters.w2.len() != h
            || features.rows.iter().any(|r| r.len() != n)
            || !self
                .normalization
                .mean
                .iter()
                .chain(&self.normalization.scale)
                .chain(self.parameters.w1.iter().flatten())
                .chain(&self.parameters.b1)
                .chain(&self.parameters.w2)
                .all(|v| finite(*v))
            || self.normalization.scale.iter().any(|v| *v < 1e-5)
            || !(1..=2000).contains(&t.steps)
            || !(1..=10000).contains(&t.rows)
            || t.trace.len() != t.steps
            || t.initial_sha256 == t.final_sha256
            || t.trace.last().map(|v| v.parameters_sha256.as_str()) != Some(t.final_sha256.as_str())
        {
            return Err("invalid semantic head".into());
        }
        for (index, row) in t.trace.iter().enumerate() {
            if row.step != index + 1 || !row.loss.is_finite() || row.loss < 0.0 {
                return Err("invalid semantic training trace".into());
            }
            hash(&row.batch_sha256)?;
            hash(&row.parameters_sha256)?;
        }
        for v in [
            &t.initial_sha256,
            &t.final_sha256,
            &self.training_features_sha256,
            &self.training_targets_sha256,
            &self.projection_sha256,
        ] {
            hash(v)?;
        }
        hash(&self.code_sha256)?;
        if self.projection_sha256 != features.projection_sha256 {
            return Err("projection binding mismatch".into());
        }
        let _ = (self.seed, t.elapsed_ns);
        Ok(())
    }
    fn scores(&self, rows: &[Vec<f64>]) -> Result<Vec<f64>> {
        let mut out = Vec::with_capacity(4);
        for row in rows {
            let mut score = 0.0;
            for j in 0..self.parameters.b1.len() {
                let mut a = self.parameters.b1[j];
                for (i, x) in row.iter().enumerate() {
                    a += ((x - self.normalization.mean[i]) / self.normalization.scale[i])
                        * self.parameters.w1[i][j];
                }
                score += a.tanh() * self.parameters.w2[j];
            }
            if !score.is_finite() {
                return Err("nonfinite semantic score".into());
            }
            out.push(score);
        }
        Ok(out)
    }
}
impl Features {
    fn validate(&self, head_bytes: &[u8]) -> Result<()> {
        if self.schema != "perc1.semantic-native-features.v1"
            || self.rows.len() != 4
            || self
                .rows
                .iter()
                .flatten()
                .any(|v| !v.is_finite() || v.abs() > 1e6)
        {
            return Err("invalid semantic features".into());
        }
        if self.candidate_ids.len() != 4
            || self.candidate_ids.iter().any(|value| value == ABSTAIN_ID)
            || self
                .candidate_ids
                .iter()
                .collect::<std::collections::BTreeSet<_>>()
                .len()
                != 4
            || self.candidate_ids.iter().any(|s| StableId::new(s).is_err())
        {
            return Err("invalid candidate catalog".into());
        }
        if hash(&self.head_sha256)? != Digest32::of_bytes(head_bytes) {
            return Err("head byte binding mismatch".into());
        }
        hash(&self.source_manifest_sha256)?;
        hash(&self.projection_sha256)?;
        Ok(())
    }
    fn transport(&self) -> (Vec<i64>, f64, f64) {
        let scale = self
            .rows
            .iter()
            .flatten()
            .map(|v| v.abs())
            .fold(1.0_f64, f64::max);
        let values: Vec<i64> = self
            .rows
            .iter()
            .flatten()
            .map(|v| (v / scale * Q as f64).round() as i64)
            .collect();
        let error = values
            .iter()
            .zip(self.rows.iter().flatten())
            .map(|(v, x)| (x - *v as f64 / Q as f64 * scale).abs())
            .fold(0.0_f64, f64::max);
        (values, scale, error)
    }
}
