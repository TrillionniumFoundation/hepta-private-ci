//! Predeclared controls and capacity-matched, next-generation topology candidates.
use super::data::{Episode, Query, Split};
use super::model::{Bundle, Meter, argmax};

pub const TRAIN_CEILING: u64 = 8_000_000;

#[derive(Clone, Debug)]
pub struct Arm {
    pub name: &'static str,
    pub bundle: Option<Bundle>,
    pub scan_limit: usize,
    pub meter: Meter,
    pub decisions: Vec<String>,
    pub training_micros: u128,
}

pub fn selection_loss(bundle: &Bundle, rows: &[Episode]) -> Result<f64, String> {
    let select: Vec<_> = rows.iter().filter(|r| r.split == Split::Select).collect();
    if select.is_empty() { return Err("missing selection view".into()); }
    let mut loss = 0.0;
    for row in &select {
        let p = bundle.infer(&row.query)?;
        loss -= p[0][row.targets[0]].max(1e-12).ln() + p[1][row.targets[1]].max(1e-12).ln();
    }
    Ok(loss / select.len() as f64)
}

pub fn admit_topology(parent: &Bundle, candidate: &Bundle, rows: &[Episode]) -> Result<bool, String> {
    if parent.scope != candidate.scope || candidate.generation != parent.generation + 1
        || candidate.parameters() != parent.parameters() || candidate.roots != parent.roots {
        return Err("incompatible or unmatched topology candidate".into());
    }
    // Avoid sacrificing either observed domain on the selection set. Final future
    // and retention labels are intentionally excluded from adoption decisions.
    for domain in 0..2 {
        let selected: Vec<_> = rows.iter().filter(|r| r.split == Split::Select && r.query.domain == domain).collect();
        if selected.len() < 8 { return Ok(false); }
        let correct = |bundle: &Bundle| -> Result<usize, String> {
            let mut n = 0;
            for row in &selected {
                let p = bundle.infer(&row.query)?;
                n += usize::from([argmax(&p[0]), argmax(&p[1])] == row.targets);
            }
            Ok(n)
        };
        if (correct(candidate)? as f64) < 0.98 * correct(parent)? as f64 { return Ok(false); }
    }
    // Serialized manifest and routing overhead are not silently free. This tiny
    // fixed selection penalty is predeclared, not tuned on either future window.
    let cost = |b: &Bundle| b.encode().len() as f64 * 1e-7 + b.cells.len() as f64 * 1e-3;
    Ok(selection_loss(candidate, rows)? + cost(candidate) + 1e-3
        < selection_loss(parent, rows)? + cost(parent))
}

pub fn split(parent: &Bundle) -> Result<Bundle, String> {
    if parent.cells.len() != 1 || parent.cells[0].rank % 2 != 0 {
        return Err("split requires one even-rank parent".into());
    }
    let half = parent.cells[0].rank / 2;
    let mut child = Bundle::new(parent.scope.clone(), &[half, half])?;
    child.generation = parent.generation + 1;
    child.roots = parent.roots.clone();
    // Copy compatible slices, never duplicate the parent's parameter capacity.
    // This is a lossy candidate initializer; equivalence is NOT asserted.
    for (part, c) in child.cells.iter_mut().enumerate() {
        for j in 0..half {
            let old = part * half + j;
            for k in 0..super::data::WIDTH {
                c.weights[j * super::data::WIDTH + k] = parent.cells[0].weights[old * super::data::WIDTH + k];
            }
            for out in 0..2 * super::data::CLASSES {
                c.weights[half * (super::data::WIDTH + out) + j] =
                    parent.cells[0].weights[parent.cells[0].rank * (super::data::WIDTH + out) + old];
            }
        }
    }
    Ok(child)
}

pub fn merge(parent: &Bundle) -> Result<Bundle, String> {
    if parent.cells.len() != 2 { return Err("merge requires two cells".into()); }
    let rank = parent.cells.iter().map(|c| c.rank).sum();
    let mut merged = Bundle::new(parent.scope.clone(), &[rank])?;
    merged.generation = parent.generation + 1;
    merged.roots = parent.roots.clone();
    // Consolidation by bounded retraining from the permitted original examples.
    // No arbitrary adapter averaging and no independent evidence fabrication.
    Ok(merged)
}

pub fn train_arms(rows: &[Episode]) -> Result<Vec<Arm>, String> {
    let scope = rows.first().ok_or("empty corpus")?.query.scope.clone();
    let mut arms = Vec::new();
    for (name, ranks) in [
        ("shared_rank8", vec![8]), ("static_2x4", vec![4, 4]),
        ("shared_rank16", vec![16]), ("static_2x8", vec![8, 8]),
    ] {
        let start = std::time::Instant::now();
        let mut bundle = Bundle::new(scope.clone(), &ranks)?;
        let mut meter = Meter::default();
        bundle.train(rows, &mut meter, TRAIN_CEILING)?;
        arms.push(Arm { name, bundle: Some(bundle), scan_limit: 0, meter,
            decisions: vec!["fixed_before_training".into()], training_micros: start.elapsed().as_micros() });
    }
    let start = std::time::Instant::now();
    let mut parent = Bundle::new(scope, &[8])?;
    let mut meter = Meter::default();
    parent.train(rows, &mut meter, TRAIN_CEILING / 4)?;
    let mut candidate = split(&parent)?;
    candidate.train(rows, &mut meter, TRAIN_CEILING * 5 / 8)?;
    let accepted = admit_topology(&parent, &candidate, rows)?;
    let mut decisions = vec![format!("split:{}", if accepted { "adopt_next_generation" } else { "retain_parent" })];
    if accepted {
        parent = candidate;
        let mut merged = merge(&parent)?;
        merged.train(rows, &mut meter, TRAIN_CEILING)?;
        let accepted = admit_topology(&parent, &merged, rows)?;
        decisions.push(format!("merge:{}", if accepted { "adopt_next_generation" } else { "retain_children" }));
        if accepted { parent = merged; }
    } else {
        // Rejected-candidate compute remains charged; remaining budget may improve
        // the unmodified topology, but never using held-out future labels.
        parent.train(rows, &mut meter, TRAIN_CEILING)?;
        decisions.push("merge:not_applicable_without_adopted_split".into());
    }
    arms.push(Arm { name: "dynamic_equal_capacity", bundle: Some(parent), scan_limit: 0,
        meter, decisions, training_micros: start.elapsed().as_micros() });
    for (name, scan_limit) in [("hybrid_retrieval_64", 64), ("hybrid_retrieval_256", 256)] {
        arms.push(Arm { name, bundle: None, scan_limit, meter: Meter::default(),
            decisions: vec!["nonparametric_control".into()], training_micros: 0 });
    }
    Ok(arms)
}

pub fn predict(arm: &Arm, rows: &[Episode], query: &Query) -> Result<super::retrieval::Recall, String> {
    match &arm.bundle {
        Some(bundle) => {
            let slot = if bundle.cells.len() == 1 { 0 } else { query.domain };
            Ok(super::retrieval::Recall { probabilities: bundle.infer(query)?, evidence: Vec::new(), scanned: 0,
                ops_estimate: (bundle.cells[slot].weights.len() * 2 + query.text.len()) as u64 })
        }
        None => super::retrieval::recall(rows, query, arm.scan_limit),
    }
}
