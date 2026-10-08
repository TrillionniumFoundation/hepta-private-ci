//! Bounded BM25 + frozen-feature cosine reciprocal-rank-fusion control.
//! This is a transparent small-corpus control, not a claim to be the best RAG system.
use super::data::{CLASSES, Episode, Query, Split, features, words};
use std::collections::{BTreeMap, BTreeSet};

pub struct Recall {
    pub probabilities: [[f64; CLASSES]; 2],
    pub evidence: Vec<String>,
    pub scanned: usize,
    pub ops_estimate: u64,
}

pub fn recall(rows: &[Episode], q: &Query, scan_limit: usize) -> Result<Recall, String> {
    if scan_limit == 0 || scan_limit > 20_000 { return Err("invalid scan budget".into()); }
    let mut docs: Vec<_> = rows.iter().filter(|e| e.split == Split::Train && e.query.scope == q.scope).collect();
    docs.sort_by(|a, b| a.id.cmp(&b.id));
    docs.truncate(scan_limit);
    if docs.is_empty() { return Err("no eligible evidence".into()); }
    let tokens: Vec<_> = docs.iter().map(|d| words(&d.query.text)).collect();
    let terms: BTreeSet<_> = words(&q.text).into_iter().collect();
    let mut frequency = BTreeMap::new();
    for term in &terms {
        frequency.insert(term, tokens.iter().filter(|d| d.contains(term)).count());
    }
    let average = tokens.iter().map(Vec::len).sum::<usize>() as f64 / docs.len() as f64;
    let x = features(q);
    let mut bm25 = Vec::new();
    let mut cosine = Vec::new();
    for (i, doc) in docs.iter().enumerate() {
        let score: f64 = terms.iter().map(|term| {
            let tf = tokens[i].iter().filter(|w| *w == term).count() as f64;
            let df = frequency[term] as f64;
            let idf = (1.0 + (docs.len() as f64 - df + 0.5) / (df + 0.5)).ln();
            idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * tokens[i].len() as f64 / average.max(1.0)))
        }).sum();
        let y = features(&doc.query);
        let dot: f64 = x.iter().zip(y).map(|(a, b)| a * b).sum();
        let norm = (x.iter().map(|v| v * v).sum::<f64>() * y.iter().map(|v| v * v).sum::<f64>()).sqrt();
        bm25.push((i, score));
        cosine.push((i, dot / norm.max(f64::MIN_POSITIVE)));
    }
    for channel in [&mut bm25, &mut cosine] {
        channel.sort_by(|a, b| b.1.total_cmp(&a.1).then_with(|| docs[a.0].id.cmp(&docs[b.0].id)));
    }
    let mut fused = vec![0.0; docs.len()];
    for channel in [&bm25, &cosine] {
        for (rank, (i, _)) in channel.iter().enumerate() { fused[*i] += 1.0 / (60 + rank) as f64; }
    }
    let mut ranked: Vec<_> = fused.into_iter().enumerate().collect();
    ranked.sort_by(|a, b| b.1.total_cmp(&a.1).then_with(|| docs[a.0].id.cmp(&docs[b.0].id)));
    let mut probabilities = [[0.001; CLASSES]; 2];
    let mut evidence = Vec::new();
    for (i, score) in ranked.into_iter().take(4) {
        for (head, p) in probabilities.iter_mut().enumerate() { p[docs[i].targets[head]] += score; }
        evidence.push(docs[i].evidence.clone());
    }
    for p in &mut probabilities {
        let total: f64 = p.iter().sum();
        for v in p { *v /= total; }
    }
    let token_work: usize = tokens.iter().map(Vec::len).sum();
    Ok(Recall { probabilities, evidence, scanned: docs.len(),
        ops_estimate: (token_work * (terms.len() + 2) + docs.len() * 128) as u64 })
}
