//! Finite 40-state numeric prototype; input matrices are frozen model data.
use std::error::Error;

pub const N: usize = 40;
type Result<T> = std::result::Result<T, Box<dyn Error>>;
pub type State = [f64; N];
pub type Matrix = [[f64; N]; N];

fn ensure(condition: bool, message: &str) -> Result<()> {
    if condition {
        Ok(())
    } else {
        Err(message.into())
    }
}

pub fn belief(p: &State) -> Result<()> {
    ensure(
        p.iter().all(|x| x.is_finite() && *x >= 0.0),
        "invalid belief support",
    )?;
    ensure(
        (p.iter().sum::<f64>() - 1.0).abs() <= 2e-11,
        "invalid belief mass",
    )
}

pub fn validate(q: &Matrix, emission: &[Vec<f64>]) -> Result<()> {
    for (i, row) in q.iter().enumerate() {
        ensure(
            row[i] <= 0.0 && -row[i] <= 100.0,
            "exit rate outside profile",
        )?;
        ensure(
            row.iter().enumerate().all(|(j, x)| j == i || *x >= 0.0),
            "negative edge",
        )?;
        let outgoing: f64 = row
            .iter()
            .enumerate()
            .filter(|(j, _)| *j != i)
            .map(|(_, x)| x)
            .sum();
        ensure(
            (outgoing + row[i]).abs() <= 64.0 * f64::EPSILON * outgoing.max(-row[i]),
            "nonconservative generator",
        )?;
    }
    for row in emission {
        ensure(row.iter().all(|x| *x >= 0.0), "negative emission")?;
        ensure(
            (row.iter().sum::<f64>() - 1.0).abs() <= 1e-13,
            "invalid emission mass",
        )?;
    }
    Ok(())
}

/// Positive uniformization, retaining a flux accumulator through all segments.
/// The fixed 160 terms at mu <= 8 bound omitted Poisson mass far below FP64 eps.
pub fn evolve(q: &Matrix, p: &State, dt: f64, rate: &State) -> Result<(State, f64)> {
    ensure(
        dt.is_finite() && (0.0..=20.0).contains(&dt),
        "duration outside profile",
    )?;
    let lambda = q
        .iter()
        .enumerate()
        .map(|(i, row)| -row[i])
        .fold(0.0_f64, f64::max);
    if lambda == 0.0 || dt == 0.0 {
        return Ok((*p, 0.0));
    }
    ensure(lambda * dt > 0.0, "underflowed propagation clock")?;
    let segments = (lambda * dt / 8.0).ceil().max(1.0) as usize;
    let mu = lambda * dt / segments as f64;
    let mut transition = [[0.0; N]; N];
    for (i, row) in q.iter().enumerate() {
        for (j, entry) in row.iter().enumerate() {
            transition[i][j] = entry / lambda + f64::from(i == j);
            ensure(transition[i][j] >= 0.0, "uniformization negative entry")?;
        }
    }
    let mut result = *p;
    let mut total = 0.0;
    for _ in 0..segments {
        let mut term = result;
        let mut weight = (-mu).exp();
        let mut output = term.map(|x| weight * x);
        let mut reward = 0.0;
        let mut cumulative = 0.0;
        for k in 1..160 {
            cumulative += term
                .iter()
                .zip(rate)
                .map(|(x, r)| x * (r / lambda))
                .sum::<f64>();
            let mut successor = [0.0; N];
            for (i, value) in term.iter().enumerate() {
                for (j, entry) in transition[i].iter().enumerate() {
                    successor[j] += value * entry;
                }
            }
            term = successor;
            weight *= mu / k as f64;
            for (entry, value) in output.iter_mut().zip(term) {
                *entry += weight * value;
            }
            reward += weight * cumulative;
        }
        result = output;
        total += reward;
    }
    ensure(
        result.iter().all(|x| x.is_finite() && *x >= 0.0) && total.is_finite(),
        "numeric overflow",
    )?;
    Ok((result, total))
}
