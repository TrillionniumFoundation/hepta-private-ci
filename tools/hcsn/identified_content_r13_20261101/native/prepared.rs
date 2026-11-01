//! Immutable validated Q and exact-bit time caches. All preparation is observable.
use crate::core::Failure;
use crate::core::Uniformized;
use crate::core::{self};
use crate::sha256;
use std::collections::HashMap;
use std::sync::Arc;
use std::sync::Mutex;

pub const MAX_PREPARED_DIMENSION: usize = 1024;
const MAX_CACHE_ENTRIES: usize = 32;
const MAX_CACHE_BYTES: usize = 64 * 1024 * 1024;

pub enum Transition {
    Sparse { segments: usize, weights: Vec<f64> },
    Dense(Vec<f64>),
}

#[derive(Default)]
struct Cache {
    entries: HashMap<(u64, u32), Arc<Transition>>,
    bytes: usize,
    hits: u64,
    preparations: u64,
}

pub struct Model {
    pub n: usize,
    pub version: u64,
    pub q: Vec<f64>,
    pub identity: String,
    embedded: Uniformized,
    cache: Mutex<Cache>,
}

#[derive(Default)]
pub struct Workspace {
    state: Vec<f64>,
    term: Vec<f64>,
    next: Vec<f64>,
    sum: Vec<f64>,
    correction: Vec<f64>,
    pub output: Vec<f64>,
}

impl Workspace {
    fn resize(&mut self, n: usize) {
        self.state.resize(n, 0.0);
        self.term.resize(n, 0.0);
        self.next.resize(n, 0.0);
        self.sum.resize(n, 0.0);
        self.correction.resize(n, 0.0);
    }

    fn segment(&mut self, rows: &[Vec<(usize, f64)>], weights: &[f64]) {
        self.term.copy_from_slice(&self.state);
        self.correction.fill(0.0);
        for (sum, x) in self.sum.iter_mut().zip(&self.term) {
            *sum = weights[0] * x;
        }
        for weight in &weights[1..] {
            self.next.fill(0.0);
            for (i, row) in rows.iter().enumerate() {
                for &(j, coefficient) in row {
                    self.next[j] += self.term[i] * coefficient;
                }
            }
            std::mem::swap(&mut self.term, &mut self.next);
            for j in 0..self.sum.len() {
                let adjusted = weight * self.term[j] - self.correction[j];
                let next = self.sum[j] + adjusted;
                self.correction[j] = (next - self.sum[j]) - adjusted;
                self.sum[j] = next;
            }
        }
        self.state.copy_from_slice(&self.sum);
    }
}

fn weights(total_mean: f64) -> Result<(usize, Vec<f64>), Failure> {
    if !total_mean.is_finite() || total_mean > core::POISSON_MEAN_LIMIT * core::MAX_SEGMENTS as f64
    {
        return Err(Failure::WorkLimit);
    }
    let segments = ((total_mean / core::POISSON_MEAN_LIMIT).ceil() as usize)
        .max(1)
        .next_power_of_two();
    let mean = total_mean / segments as f64;
    let tolerance = core::TOTAL_TAIL_BUDGET / segments as f64;
    let mut terms = vec![(-mean).exp()];
    for k in 0..512 {
        let next = terms[k] * mean / (k + 1) as f64;
        let ratio = mean / (k + 2) as f64;
        if ratio < 1.0 && next / (1.0 - ratio) <= tolerance {
            return Ok((segments, terms));
        }
        terms.push(next);
    }
    Err(Failure::WorkLimit)
}

fn multiply(a: &[f64], b: &[f64], n: usize, output: &mut [f64]) {
    output.fill(0.0);
    for i in 0..n {
        let row = &mut output[i * n..(i + 1) * n];
        for k in 0..n {
            let scale = a[i * n + k];
            if scale != 0.0 {
                for (target, value) in row.iter_mut().zip(&b[k * n..(k + 1) * n]) {
                    *target += scale * value;
                }
            }
        }
    }
}

impl Model {
    pub fn new(n: usize, q: &[f64], version: u64) -> Result<Self, Failure> {
        if n == 0 || n > MAX_PREPARED_DIMENSION {
            return Err(Failure::Dimension);
        }
        let embedded = core::prepare(n, q)?;
        let mut bytes = b"HCSN_R13_Q_VERSION_V1".to_vec();
        bytes.extend_from_slice(&(n as u64).to_be_bytes());
        bytes.extend_from_slice(&version.to_be_bytes());
        for value in q {
            bytes.extend_from_slice(&value.to_bits().to_be_bytes());
        }
        Ok(Self {
            n,
            version,
            q: q.to_vec(),
            identity: sha256::hex(&bytes),
            embedded,
            cache: Mutex::new(Cache::default()),
        })
    }

    pub fn prepare(&self, dt: f64, mode: u32) -> Result<Arc<Transition>, Failure> {
        if !dt.is_finite() || dt < 0.0 || mode > 1 {
            return Err(Failure::Domain);
        }
        let key = (dt.to_bits(), mode);
        let mut cache = self.cache.lock().map_err(|_| Failure::Panic)?;
        if let Some(plan) = cache.entries.get(&key).cloned() {
            cache.hits += 1;
            return Ok(plan);
        }
        let (segments, terms) = weights(self.embedded.rate * dt)?;
        let bytes = if mode == 0 {
            terms.len() * 8
        } else {
            self.n * self.n * 8
        };
        if cache.entries.len() >= MAX_CACHE_ENTRIES || cache.bytes + bytes > MAX_CACHE_BYTES {
            return Err(Failure::CacheLimit);
        }
        let plan = if mode == 0 {
            Transition::Sparse {
                segments,
                weights: terms,
            }
        } else {
            let mut kernel = vec![0.0; self.n * self.n];
            let mut scratch = Workspace::default();
            scratch.resize(self.n);
            for i in 0..self.n {
                scratch.state.fill(0.0);
                scratch.state[i] = 1.0;
                scratch.segment(&self.embedded.rows, &terms);
                kernel[i * self.n..(i + 1) * self.n].copy_from_slice(&scratch.state);
            }
            let mut temporary = vec![0.0; kernel.len()];
            for _ in 0..segments.trailing_zeros() {
                multiply(&kernel, &kernel, self.n, &mut temporary);
                std::mem::swap(&mut kernel, &mut temporary);
            }
            for row in kernel.chunks_exact(self.n) {
                core::probability_mass(row)?;
            }
            Transition::Dense(kernel)
        };
        let plan = Arc::new(plan);
        cache.bytes += bytes;
        cache.preparations += 1;
        cache.entries.insert(key, plan.clone());
        Ok(plan)
    }

    pub fn statistics(&self) -> Result<[u64; 4], Failure> {
        let cache = self.cache.lock().map_err(|_| Failure::Panic)?;
        Ok([1, cache.preparations, cache.hits, cache.bytes as u64])
    }

    pub fn clear_cache(&self) -> Result<(), Failure> {
        let mut cache = self.cache.lock().map_err(|_| Failure::Panic)?;
        cache.entries.clear();
        cache.bytes = 0;
        Ok(())
    }

    pub fn apply(
        &self,
        plan: &Transition,
        input: &[f64],
        work: &mut Workspace,
    ) -> Result<(), Failure> {
        for row in input.chunks_exact(self.n) {
            core::probability_mass(row)?;
        }
        work.output.resize(input.len(), 0.0);
        match plan {
            Transition::Sparse { segments, weights } => {
                work.resize(self.n);
                for (index, row) in input.chunks_exact(self.n).enumerate() {
                    work.state.copy_from_slice(row);
                    for _ in 0..*segments {
                        work.segment(&self.embedded.rows, weights);
                    }
                    work.output[index * self.n..(index + 1) * self.n].copy_from_slice(&work.state);
                }
            }
            Transition::Dense(kernel) => {
                work.output.fill(0.0);
                for (row, out) in input
                    .chunks_exact(self.n)
                    .zip(work.output.chunks_exact_mut(self.n))
                {
                    for (i, scale) in row.iter().enumerate() {
                        if *scale != 0.0 {
                            for (target, value) in
                                out.iter_mut().zip(&kernel[i * self.n..(i + 1) * self.n])
                            {
                                *target += scale * value;
                            }
                        }
                    }
                }
            }
        }
        for (before, after) in input
            .chunks_exact(self.n)
            .zip(work.output.chunks_exact(self.n))
        {
            let old = core::probability_mass(before)?;
            let new = core::probability_mass(after)?;
            if (old - new).abs() > core::MASS_TOLERANCE {
                return Err(Failure::Numerical);
            }
        }
        Ok(())
    }
}
