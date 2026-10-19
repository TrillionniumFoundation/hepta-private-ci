//! Tiny trainable two-head backend for controlled experiments, not installed inference.
use super::data::CLASSES;
use super::data::ENCODER;
use super::data::Episode;
use super::data::Query;
use super::data::Split;
use super::data::WIDTH;
use super::data::features;
use std::collections::BTreeSet;

#[derive(Clone, Debug, PartialEq)]
pub struct Cell {
    pub rank: usize,
    pub weights: Vec<f64>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Bundle {
    pub scope: String,
    pub generation: u64,
    pub roots: BTreeSet<String>,
    pub cells: Vec<Cell>,
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Meter {
    pub train_ops: u64,
    pub updates: u64,
}

pub fn argmax(p: &[f64]) -> usize {
    p.iter()
        .enumerate()
        .max_by(|a, b| a.1.total_cmp(b.1).then_with(|| b.0.cmp(&a.0)))
        .map_or(0, |(i, _)| i)
}

impl Cell {
    pub fn new(rank: usize) -> Result<Self, String> {
        if !(1..=32).contains(&rank) {
            return Err("invalid rank".into());
        }
        let n = rank * (WIDTH + 2 * CLASSES);
        let weights = (0..n)
            .map(|i| (((i * 97 + 13) % 101) as f64 - 50.0) / 250.0)
            .collect();
        Ok(Self { rank, weights })
    }

    pub fn infer(&self, q: &Query) -> [[f64; CLASSES]; 2] {
        let x = features(q);
        let h: Vec<_> = self.weights[..self.rank * WIDTH]
            .chunks(WIDTH)
            .map(|w| w.iter().zip(x).map(|(a, b)| a * b).sum::<f64>().tanh())
            .collect();
        let mut result = [[0.0; CLASSES]; 2];
        for (head, out) in result.iter_mut().enumerate() {
            for (class, p) in out.iter_mut().enumerate() {
                let offset = self.rank * (WIDTH + head * CLASSES + class);
                *p = self.weights[offset..offset + self.rank]
                    .iter()
                    .zip(&h)
                    .map(|(a, b)| a * b)
                    .sum();
            }
            let max = out.iter().copied().fold(f64::NEG_INFINITY, f64::max);
            for p in out.iter_mut() {
                *p = (*p - max).exp();
            }
            let z: f64 = out.iter().sum();
            for p in out {
                *p /= z;
            }
        }
        result
    }

    pub fn step(&mut self, row: &Episode, meter: &mut Meter, ceiling: u64) -> Result<bool, String> {
        if row.split != Split::Train {
            return Err("training requires train split".into());
        }
        let ops = (self.weights.len() * 8 + self.rank * 8) as u64;
        if meter.train_ops.checked_add(ops).ok_or("counter overflow")? > ceiling {
            return Ok(false);
        }
        let x = features(&row.query);
        let hidden: Vec<_> = self.weights[..self.rank * WIDTH]
            .chunks(WIDTH)
            .map(|w| w.iter().zip(x).map(|(a, b)| a * b).sum::<f64>().tanh())
            .collect();
        let p = self.infer(&row.query);
        let mut dh = vec![0.0; self.rank];
        for (head, head_probabilities) in p.iter().enumerate() {
            for (class, probability) in head_probabilities.iter().enumerate() {
                let error = *probability - f64::from(class == row.targets[head]);
                let offset = self.rank * (WIDTH + head * CLASSES + class);
                for j in 0..self.rank {
                    dh[j] += error * self.weights[offset + j];
                    self.weights[offset + j] -= 0.08 * error * hidden[j];
                }
            }
        }
        for j in 0..self.rank {
            let grad = dh[j] * (1.0 - hidden[j] * hidden[j]);
            for (k, v) in x.iter().enumerate() {
                self.weights[j * WIDTH + k] -= 0.08 * grad * v;
            }
        }
        if self
            .weights
            .iter()
            .any(|w| !w.is_finite() || w.abs() > 100.0)
        {
            return Err("nonfinite or unbounded candidate weights".into());
        }
        meter.train_ops += ops;
        meter.updates += 1;
        Ok(true)
    }
}

impl Bundle {
    pub fn new(scope: String, ranks: &[usize]) -> Result<Self, String> {
        if ranks.is_empty() || ranks.len() > 2 {
            return Err("invalid cell count".into());
        }
        Ok(Self {
            scope,
            generation: 1,
            roots: BTreeSet::new(),
            cells: ranks
                .iter()
                .map(|r| Cell::new(*r))
                .collect::<Result<_, _>>()?,
        })
    }

    pub fn train(
        &mut self,
        rows: &[Episode],
        meter: &mut Meter,
        ceiling: u64,
    ) -> Result<(), String> {
        let train: Vec<_> = rows.iter().filter(|r| r.split == Split::Train).collect();
        if train.is_empty() || train.iter().any(|r| r.query.scope != self.scope) {
            return Err("empty or cross-scope training view".into());
        }
        for round in 0..256 {
            for offset in 0..train.len() {
                let row = train[(offset + round) % train.len()];
                let slot = if self.cells.len() == 1 {
                    0
                } else {
                    row.query.domain
                };
                if !self.cells[slot].step(row, meter, ceiling)? {
                    return Ok(());
                }
                self.roots.insert(row.root.clone());
            }
        }
        Ok(())
    }

    pub fn infer(&self, query: &Query) -> Result<[[f64; CLASSES]; 2], String> {
        if query.scope != self.scope || query.domain > 1 {
            return Err("scope/domain mismatch".into());
        }
        let slot = if self.cells.len() == 1 {
            0
        } else {
            query.domain
        };
        Ok(self.cells[slot].infer(query))
    }

    pub fn parameters(&self) -> usize {
        self.cells.iter().map(|c| c.weights.len()).sum()
    }

    pub fn encode(&self) -> String {
        let mut s = format!(
            "MCELL-LAB-1\n{ENCODER}\n{}\n{}\n{}\n",
            self.scope,
            self.generation,
            self.roots.len()
        );
        for root in &self.roots {
            s.push_str(&format!("{root}\n"));
        }
        s.push_str(&format!("{}\n", self.cells.len()));
        for cell in &self.cells {
            s.push_str(&format!("{}\n", cell.rank));
            for w in &cell.weights {
                s.push_str(&format!("{:016x}\n", w.to_bits()));
            }
        }
        s
    }

    pub fn decode(s: &str) -> Result<Self, String> {
        if s.len() > 4 * 1024 * 1024 {
            return Err("bundle too large".into());
        }
        let mut lines = s.lines();
        if lines.next() != Some("MCELL-LAB-1") || lines.next() != Some(ENCODER) {
            return Err("incompatible bundle/encoder".into());
        }
        let scope = lines.next().ok_or("missing scope")?.to_owned();
        if scope.is_empty() || scope.len() > 8192 {
            return Err("invalid scope".into());
        }
        let generation = lines
            .next()
            .ok_or("missing generation")?
            .parse()
            .map_err(|_| "invalid generation")?;
        let roots_len: usize = lines
            .next()
            .ok_or("missing roots")?
            .parse()
            .map_err(|_| "invalid roots")?;
        if roots_len > 20_000 || generation == 0 {
            return Err("bundle bounds".into());
        }
        let mut roots = BTreeSet::new();
        for _ in 0..roots_len {
            let root = lines.next().ok_or("missing root")?;
            if root.is_empty() || root.len() > 8192 || !roots.insert(root.to_owned()) {
                return Err("invalid root".into());
            }
        }
        let count: usize = lines
            .next()
            .ok_or("missing cells")?
            .parse()
            .map_err(|_| "invalid cells")?;
        if !(1..=2).contains(&count) {
            return Err("invalid cell count".into());
        }
        let mut cells = Vec::new();
        for _ in 0..count {
            let rank = lines
                .next()
                .ok_or("missing rank")?
                .parse()
                .map_err(|_| "invalid rank")?;
            let mut cell = Cell::new(rank)?;
            for w in &mut cell.weights {
                *w = f64::from_bits(
                    u64::from_str_radix(lines.next().ok_or("missing tensor")?, 16)
                        .map_err(|_| "invalid tensor")?,
                );
                if !w.is_finite() || w.abs() > 100.0 {
                    return Err("invalid weight".into());
                }
            }
            cells.push(cell);
        }
        if lines.next().is_some() {
            return Err("trailing bundle bytes".into());
        }
        Ok(Self {
            scope,
            generation,
            roots,
            cells,
        })
    }
}
