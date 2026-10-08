//! Read-only experiment inputs, not a cognitive.store writer or wire protocol.
use std::collections::BTreeMap;
use std::collections::BTreeSet;

pub const WIDTH: usize = 32;
pub const CLASSES: usize = 4;
pub const ENCODER: &str = "memory-cell-lab:hashed-words-32:v1";
pub const HEADER: &str = "episode\troot\tsplit\ttime\tscope\tcommit\tenvironment\tevidence\tdomain\tsemantic\tprocedure\ttext";

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum Split {
    Train,
    Select,
    FutureA,
    FutureB,
    Retention,
}

impl Split {
    pub fn parse(s: &str) -> Result<Self, String> {
        match s {
            "train" => Ok(Self::Train),
            "select" => Ok(Self::Select),
            "future-a" => Ok(Self::FutureA),
            "future-b" => Ok(Self::FutureB),
            "retention" => Ok(Self::Retention),
            _ => Err(format!("unknown split: {s}")),
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct Query {
    pub scope: String,
    pub domain: usize,
    pub text: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Episode {
    pub id: String,
    pub root: String,
    pub split: Split,
    pub time: u64,
    pub commit: String,
    pub environment: String,
    pub evidence: String,
    pub query: Query,
    pub targets: [usize; 2],
}

pub fn parse(input: &str) -> Result<Vec<Episode>, String> {
    if input.len() > 16 * 1024 * 1024 {
        return Err("corpus exceeds 16 MiB".into());
    }
    let mut lines = input.lines();
    if lines.next() != Some(HEADER) {
        return Err("unknown corpus header/version".into());
    }
    let mut rows = Vec::new();
    for (line, text) in lines.enumerate() {
        let f: Vec<_> = text.split('\t').collect();
        if f.len() != 12 || f.iter().any(|s| s.is_empty() || s.len() > 8192) {
            return Err(format!("invalid corpus row {}", line + 2));
        }
        if f[..11].iter().any(|s| s.chars().any(char::is_control)) {
            return Err("control character in metadata".into());
        }
        let number = |i: usize| {
            f[i].parse::<usize>()
                .map_err(|_| "invalid number".to_owned())
        };
        let domain = number(8)?;
        let targets = [number(9)?, number(10)?];
        if domain > 1 || targets.iter().any(|v| *v >= CLASSES) {
            return Err("domain/target out of range".into());
        }
        if f[5].len() != 40 || !f[5].bytes().all(|b| b.is_ascii_hexdigit()) {
            return Err("commit must be an exact 40-character hex reference".into());
        }
        rows.push(Episode {
            id: f[0].into(),
            root: f[1].into(),
            split: Split::parse(f[2])?,
            time: f[3].parse().map_err(|_| "invalid timestamp")?,
            commit: f[5].into(),
            environment: f[6].into(),
            evidence: f[7].into(),
            query: Query {
                scope: f[4].into(),
                domain,
                text: f[11].into(),
            },
            targets,
        });
        if rows.len() > 20_000 {
            return Err("corpus exceeds 20000 episodes".into());
        }
    }
    validate(&rows)?;
    Ok(rows)
}

pub fn validate(rows: &[Episode]) -> Result<(), String> {
    let scope = rows.first().ok_or("empty corpus")?.query.scope.as_str();
    let mut ids = BTreeSet::new();
    let mut roots = BTreeMap::new();
    let mut inputs = BTreeMap::new();
    let mut ranges: BTreeMap<Split, (u64, u64)> = BTreeMap::new();
    for e in rows {
        if e.query.scope != scope || !ids.insert(&e.id) {
            return Err("scope mixing or duplicate episode".into());
        }
        let key = (&e.query.scope, e.query.domain, &e.query.text);
        if let Some(prior) = inputs.insert(key, e.split)
            && prior != e.split
        {
            return Err("duplicate query across splits".into());
        }
        if let Some(prior) = roots.insert(&e.root, e.split)
            && prior != e.split
        {
            return Err(format!("root crosses data splits: {}", e.root));
        }
        ranges
            .entry(e.split)
            .and_modify(|r| {
                r.0 = r.0.min(e.time);
                r.1 = r.1.max(e.time);
            })
            .or_insert((e.time, e.time));
    }
    for split in [
        Split::Train,
        Split::Select,
        Split::FutureA,
        Split::FutureB,
        Split::Retention,
    ] {
        if !ranges.contains_key(&split) {
            return Err(format!("missing split {split:?}"));
        }
    }
    for pair in [
        (Split::Train, Split::Select),
        (Split::Select, Split::FutureA),
        (Split::FutureA, Split::FutureB),
    ] {
        if ranges[&pair.0].1 >= ranges[&pair.1].0 {
            return Err("non-disjoint chronological windows".into());
        }
    }
    Ok(())
}

pub fn words(text: &str) -> Vec<String> {
    text.split(|c: char| !c.is_alphanumeric())
        .filter(|w| !w.is_empty())
        .take(512)
        .map(str::to_lowercase)
        .collect()
}

pub fn features(q: &Query) -> [f64; WIDTH] {
    let mut x = [0.0; WIDTH];
    x[0] = 1.0;
    x[1] = q.domain as f64;
    for w in words(&q.text) {
        // Non-cryptographic feature hashing ONLY; never an integrity/authority digest.
        let h = w.bytes().fold(2166136261u32, |a, b| {
            (a ^ u32::from(b)).wrapping_mul(16777619)
        });
        x[2 + h as usize % (WIDTH - 2)] += 1.0;
    }
    let norm = x[2..].iter().map(|v| v * v).sum::<f64>().sqrt().max(1.0);
    for v in &mut x[2..] {
        *v /= norm;
    }
    x
}

pub fn smoke_corpus() -> String {
    let mut s = format!("{HEADER}\n");
    let symptoms = [
        "ownership moved value",
        "borrow mutable reference",
        "unresolved module import",
        "mismatched return type",
    ];
    for (window, name) in ["train", "select", "future-a", "future-b", "retention"]
        .iter()
        .enumerate()
    {
        for i in 0..64 {
            let class = i % CLASSES;
            let domain = (i / CLASSES) % 2;
            let procedure = (class + domain) % CLASSES;
            let time = 1000 + window * 100 + i;
            s.push_str(&format!(
                "e{window}-{i}\tr{window}-{i}\t{name}\t{time}\tlab-public\t0000000000000000000000000000000000000000\tsynthetic-not-a-build\tfixture:{window}:{i}\t{domain}\t{class}\t{procedure}\t{} workspace variant {window}-{i}\n", symptoms[class]));
        }
    }
    s
}
