//! Finite CTMC row-vector propagation; no approximation to a continuum is claimed.

pub const MAX_DIMENSION: usize = 4096;
pub const MAX_SEGMENTS: usize = 16384;
pub const POISSON_MEAN_LIMIT: f64 = 16.0;
pub const TOTAL_TAIL_BUDGET: f64 = 1e-13;
pub const MASS_TOLERANCE: f64 = 5e-10;

#[derive(Debug, Clone, Copy)]
#[repr(i32)]
pub enum Failure {
    Dimension = 1,
    Domain = 2,
    Generator = 3,
    Normalization = 4,
    WorkLimit = 5,
    Numerical = 6,
    NullPointer = 7,
    Panic = 8,
    Handle = 9,
    Version = 10,
    CacheLimit = 11,
}

pub fn compensated_sum(values: impl Iterator<Item = f64>) -> f64 {
    let (mut total, mut correction) = (0.0, 0.0);
    for value in values {
        let adjusted = value - correction;
        let next = total + adjusted;
        correction = (next - total) - adjusted;
        total = next;
    }
    total
}

pub fn probability_mass(p: &[f64]) -> Result<f64, Failure> {
    if p.is_empty() || p.iter().any(|x| !x.is_finite() || *x < 0.0) {
        return Err(Failure::Domain);
    }
    let mass = compensated_sum(p.iter().copied());
    if (mass - 1.0).abs() > MASS_TOLERANCE {
        return Err(Failure::Normalization);
    }
    Ok(mass)
}

pub struct Uniformized {
    pub rate: f64,
    pub rows: Vec<Vec<(usize, f64)>>,
}

pub fn prepare(n: usize, q: &[f64]) -> Result<Uniformized, Failure> {
    if n == 0 || n > MAX_DIMENSION || q.len() != n * n {
        return Err(Failure::Dimension);
    }
    let mut rate: f64 = 0.0;
    for (i, row) in q.chunks_exact(n).enumerate() {
        if row
            .iter()
            .enumerate()
            .any(|(j, x)| !x.is_finite() || (i == j && *x > 0.0) || (i != j && *x < 0.0))
        {
            return Err(Failure::Generator);
        }
        let outgoing = compensated_sum(row.iter().enumerate().filter_map(|(j, x)| {
            if i == j {
                None
            } else {
                Some(*x)
            }
        }));
        let scale = outgoing.max(-row[i]).max(f64::MIN_POSITIVE);
        if !outgoing.is_finite() || (outgoing + row[i]).abs() > 64.0 * f64::EPSILON * scale {
            return Err(Failure::Generator);
        }
        rate = rate.max(-row[i]);
    }
    let mut rows = Vec::with_capacity(n);
    if rate > 0.0 {
        for (i, row) in q.chunks_exact(n).enumerate() {
            let mut entries = Vec::new();
            for (j, value) in row.iter().enumerate() {
                let entry = if i == j {
                    1.0 + value / rate
                } else {
                    value / rate
                };
                if !entry.is_finite() || entry < 0.0 {
                    return Err(Failure::Numerical);
                }
                if entry != 0.0 {
                    entries.push((j, entry));
                }
            }
            rows.push(entries);
        }
    }
    Ok(Uniformized { rate, rows })
}

fn segment(
    p: &[f64],
    rows: &[Vec<(usize, f64)>],
    mean: f64,
    tolerance: f64,
) -> Result<Vec<f64>, Failure> {
    let mut weight = (-mean).exp();
    let mut term = p.to_vec();
    let mut result: Vec<f64> = p.iter().map(|x| x * weight).collect();
    let mut correction = vec![0.0; p.len()];
    let mut next = vec![0.0; p.len()];
    for k in 0..512 {
        // After k terms, ratios in the omitted Poisson tail decrease. Once
        // mean/(k+2)<1, a geometric series is a conservative exact-real bound.
        let next_weight = weight * mean / (k + 1) as f64;
        let ratio_bound = mean / (k + 2) as f64;
        if ratio_bound < 1.0 && next_weight / (1.0 - ratio_bound) <= tolerance {
            return Ok(result);
        }
        next.fill(0.0);
        for (i, row) in rows.iter().enumerate() {
            for &(j, value) in row {
                next[j] += term[i] * value;
            }
        }
        std::mem::swap(&mut term, &mut next);
        weight = next_weight;
        for j in 0..result.len() {
            let adjusted = weight * term[j] - correction[j];
            let sum = result[j] + adjusted;
            correction[j] = (sum - result[j]) - adjusted;
            result[j] = sum;
        }
    }
    Err(Failure::WorkLimit)
}

pub fn propagate_row(n: usize, q: &[f64], dt: f64, p: &[f64]) -> Result<Vec<f64>, Failure> {
    if p.len() != n || !dt.is_finite() || dt < 0.0 {
        return Err(Failure::Domain);
    }
    let transition = prepare(n, q)?;
    let mass = probability_mass(p)?;
    let total_mean = transition.rate * dt;
    if !total_mean.is_finite() || total_mean > POISSON_MEAN_LIMIT * MAX_SEGMENTS as f64 {
        return Err(Failure::WorkLimit);
    }
    if total_mean == 0.0 {
        return Ok(p.to_vec());
    }
    let segments = (total_mean / POISSON_MEAN_LIMIT).ceil() as usize;
    let mean = total_mean / segments as f64;
    let mut result = p.to_vec();
    for _ in 0..segments {
        result = segment(
            &result,
            &transition.rows,
            mean,
            TOTAL_TAIL_BUDGET / segments as f64,
        )?;
    }
    let final_mass = probability_mass(&result)?;
    if (final_mass - mass).abs() > MASS_TOLERANCE {
        return Err(Failure::Numerical);
    }
    // Do not conceal truncation or roundoff by renormalizing propagation.
    Ok(result)
}

pub fn observe_row(prior: &[f64], likelihood: &[f64]) -> Result<Vec<f64>, Failure> {
    if prior.len() != likelihood.len() || prior.len() > MAX_DIMENSION {
        return Err(Failure::Dimension);
    }
    probability_mass(prior)?;
    if likelihood.iter().any(|x| !x.is_finite() || *x < 0.0) {
        return Err(Failure::Domain);
    }
    let scale = likelihood.iter().copied().fold(0.0, f64::max);
    if scale == 0.0 {
        return Err(Failure::Normalization);
    }
    let mut posterior: Vec<f64> = prior
        .iter()
        .zip(likelihood)
        .map(|(p, l)| p * (l / scale))
        .collect();
    let normalizer = compensated_sum(posterior.iter().copied());
    if !normalizer.is_finite() || normalizer <= 0.0 {
        return Err(Failure::Normalization);
    }
    posterior.iter_mut().for_each(|x| *x /= normalizer);
    probability_mass(&posterior)?;
    Ok(posterior)
}
