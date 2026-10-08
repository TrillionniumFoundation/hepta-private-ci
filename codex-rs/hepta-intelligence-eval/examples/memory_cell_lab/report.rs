//! Source-clustered measurement. These unsigned lab reports cannot grant acceptance.
use super::controls::{Arm, predict};
use super::data::{CLASSES, Episode, Split};
use super::model::argmax;
use std::collections::BTreeMap;
use std::fmt::Write;
use std::time::Instant;

#[derive(Clone, Debug, PartialEq)]
pub struct Score {
    pub root: String,
    pub semantic: bool,
    pub procedure: bool,
    pub confidence: f64,
    pub nll: f64,
    pub brier: f64,
    pub latency_ns: u128,
    pub read_ops: u64,
    pub evidence_count: usize,
    pub scanned: usize,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Summary {
    pub rows: usize,
    pub roots: usize,
    pub accuracy: f64,
    pub lower: f64,
    pub upper: f64,
    pub semantic_accuracy: f64,
    pub procedure_accuracy: f64,
    pub nll: f64,
    pub brier: f64,
    pub ece: f64,
    pub latency_ns: [u128; 3],
    pub read_ops: u64,
    pub evidence_count: usize,
    pub scanned: usize,
}

pub fn summarize(scores: &[Score]) -> Result<Summary, String> {
    if scores.is_empty() {
        return Err("empty evaluation window".into());
    }
    let mut clusters: BTreeMap<&str, (usize, usize)> = BTreeMap::new();
    let mut bins = [(0usize, 0.0, 0usize); 10];
    for s in scores {
        if !s.confidence.is_finite()
            || !(0.0..=1.0).contains(&s.confidence)
            || !s.nll.is_finite()
            || !s.brier.is_finite()
        {
            return Err("invalid observation".into());
        }
        let group = clusters.entry(&s.root).or_default();
        group.0 += usize::from(s.semantic && s.procedure);
        group.1 += 1;
        let bin = &mut bins[((s.confidence * 10.0) as usize).min(9)];
        bin.0 += 1;
        bin.1 += s.confidence;
        bin.2 += usize::from(s.semantic && s.procedure);
    }
    let roots = clusters.len();
    let accuracy = clusters
        .values()
        .map(|(n, total)| *n as f64 / *total as f64)
        .sum::<f64>()
        / roots as f64;
    // Equal weight per supplied independent source root; repeated episodes cannot
    // inflate n. Hoeffding + Bonferroni for the 7 arms x 3 preregistered windows.
    // Independence of externally supplied roots is an ASSUMPTION, not authenticated.
    let radius = ((2.0_f64 * 21.0 / 0.05).ln() / (2.0 * roots as f64)).sqrt();
    let rows = scores.len();
    let mut latency: Vec<_> = scores.iter().map(|s| s.latency_ns).collect();
    latency.sort_unstable();
    let percentile = |p: usize| latency[((rows * p).div_ceil(100)).saturating_sub(1).min(rows - 1)];
    Ok(Summary {
        rows,
        roots,
        accuracy,
        lower: (accuracy - radius).max(0.0),
        upper: (accuracy + radius).min(1.0),
        semantic_accuracy: scores.iter().filter(|s| s.semantic).count() as f64 / rows as f64,
        procedure_accuracy: scores.iter().filter(|s| s.procedure).count() as f64 / rows as f64,
        nll: scores.iter().map(|s| s.nll).sum::<f64>() / rows as f64,
        brier: scores.iter().map(|s| s.brier).sum::<f64>() / rows as f64,
        ece: bins
            .iter()
            .filter(|b| b.0 > 0)
            .map(|b| (b.1 - b.2 as f64).abs())
            .sum::<f64>()
            / rows as f64,
        latency_ns: [percentile(50), percentile(95), percentile(99)],
        read_ops: scores.iter().map(|s| s.read_ops).sum(),
        evidence_count: scores.iter().map(|s| s.evidence_count).sum(),
        scanned: scores.iter().map(|s| s.scanned).sum(),
    })
}

pub fn evaluate(arm: &Arm, rows: &[Episode], split: Split) -> Result<Summary, String> {
    if !matches!(split, Split::FutureA | Split::FutureB | Split::Retention) {
        return Err("evaluation requires an untouched report window".into());
    }
    let mut scores = Vec::new();
    for row in rows.iter().filter(|r| r.split == split) {
        let start = Instant::now();
        let recall = predict(arm, rows, &row.query)?;
        let elapsed = start.elapsed().as_nanos();
        let p = recall.probabilities;
        let predicted = [argmax(&p[0]), argmax(&p[1])];
        let mut brier = 0.0;
        for head in 0..2 {
            for class in 0..CLASSES {
                brier += (p[head][class] - f64::from(class == row.targets[head])).powi(2) / 2.0;
            }
        }
        scores.push(Score {
            root: row.root.clone(),
            semantic: predicted[0] == row.targets[0],
            procedure: predicted[1] == row.targets[1],
            confidence: p[0][predicted[0]] * p[1][predicted[1]],
            nll: -p[0][row.targets[0]].max(1e-12).ln() - p[1][row.targets[1]].max(1e-12).ln(),
            brier,
            latency_ns: elapsed,
            read_ops: recall.ops_estimate,
            evidence_count: recall.evidence.len(),
            scanned: recall.scanned,
        });
    }
    summarize(&scores)
}

pub fn json_string(s: &str) -> String {
    let mut out = String::from("\"");
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c.is_control() => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

impl Summary {
    pub fn json(&self) -> String {
        format!(
            concat!(
                "{{\"rows\":{},\"source_roots\":{},\"root_mean_joint_accuracy\":{},",
                "\"simultaneous_95_interval\":[{},{}],\"row_semantic_accuracy\":{},\"row_procedure_accuracy\":{},",
                "\"nll\":{},\"brier\":{},\"ece10\":{},\"query_latency_ns_p50_p95_p99\":[{},{},{}],",
                "\"read_ops_estimate\":{},\"evidence_refs\":{},\"documents_scanned\":{},\"citation_entailment_precision\":null}}"
            ),
            self.rows,
            self.roots,
            self.accuracy,
            self.lower,
            self.upper,
            self.semantic_accuracy,
            self.procedure_accuracy,
            self.nll,
            self.brier,
            self.ece,
            self.latency_ns[0],
            self.latency_ns[1],
            self.latency_ns[2],
            self.read_ops,
            self.evidence_count,
            self.scanned
        )
    }
}

pub fn experiment_report(
    arms: &[Arm],
    rows: &[Episode],
    corpus_bytes: usize,
    smoke: bool,
) -> Result<String, String> {
    let mut records = Vec::new();
    let mut metrics = BTreeMap::new();
    for arm in arms {
        let mut windows = Vec::new();
        for split in [Split::FutureA, Split::FutureB, Split::Retention] {
            let result = evaluate(arm, rows, split)?;
            println!(
                "{} {split:?}: {:.4} roots={} CI=[{:.4},{:.4}]",
                arm.name, result.accuracy, result.roots, result.lower, result.upper
            );
            windows.push(format!(
                "{}:{}",
                json_string(&format!("{split:?}")),
                result.json()
            ));
            metrics.insert((arm.name, split), result);
        }
        let decisions = arm
            .decisions
            .iter()
            .map(|s| json_string(s))
            .collect::<Vec<_>>()
            .join(",");
        let artifact_bytes = arm.bundle.as_ref().map_or(0, |b| b.encode().len());
        let parameter_bytes = arm.bundle.as_ref().map_or(0, |b| b.parameters() * 8);
        records.push(format!(concat!("{{\"arm\":{},\"parameter_bytes\":{},\"artifact_bytes\":{},",
            "\"train_ops_estimate\":{},\"train_updates\":{},\"train_micros\":{},",
            "\"amortized_train_ops_per_report_query\":{},\"topology_decisions\":[{}],\"windows\":{{{}}}}}"),
            json_string(arm.name), parameter_bytes, artifact_bytes, arm.meter.train_ops, arm.meter.updates,
            arm.training_micros, arm.meter.train_ops as f64 / rows.iter().filter(|r| matches!(r.split, Split::FutureA | Split::FutureB | Split::Retention)).count() as f64,
            decisions, windows.join(",")));
    }
    let candidate = "dynamic_equal_capacity";
    let baseline = "static_2x4";
    let mut screen = true;
    for split in [Split::FutureA, Split::FutureB] {
        let a = metrics
            .get(&(candidate, split))
            .ok_or("missing candidate")?;
        let b = metrics.get(&(baseline, split)).ok_or("missing baseline")?;
        screen &= a.roots >= 200 && b.roots >= 200 && a.lower > b.upper;
    }
    let old_a = &metrics[&(candidate, Split::Retention)];
    let old_b = &metrics[&(baseline, Split::Retention)];
    let regression = if old_b.accuracy > 0.0 {
        ((old_b.accuracy - old_a.accuracy) / old_b.accuracy).max(0.0)
    } else {
        0.0
    };
    screen &= old_b.accuracy > 0.0 && regression <= 0.02;
    Ok(format!(
        concat!(
            "{{\"schema\":\"hepta.memory-cell-lab.report.v1\",\"synthetic_smoke\":{},",
            "\"shared_retained_corpus_bytes_counted_once\":{},\"encoder\":{},\"arms\":[{}],",
            "\"dynamic_vs_static_numeric_screen\":{},\"relative_old_task_regression\":{},",
            "\"production_qualified\":false,\"superiority_claim\":false,",
            "\"missing_evidence\":[\"three independently admitted snapshots\",\"two real future calendar windows\",",
            "\"authenticated source-root independence\",\"citation entailment precision >= 0.99\",",
            "\"production owner integration and distributed deployment\",\"independent signed qualification\"],",
            "\"metric_notes\":[\"op counters are declared estimates, not FLOPs or measured GPU time\",",
            "\"corpus storage is retained, not erased by parametric compression\",",
            "\"confidence product is evaluated for calibration, not assumed calibrated\",",
            "\"a source reference is not proof of proposition entailment\"]}}\n"
        ),
        smoke,
        corpus_bytes,
        json_string(super::data::ENCODER),
        records.join(","),
        screen,
        regression
    ))
}
