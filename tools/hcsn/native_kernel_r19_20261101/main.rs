//! Finite 40-state numeric prototype; input matrices are frozen model data.
use std::error::Error;
use std::io::{self, Read};

const N: usize = 40;
const CAPACITY: u64 = 2_000_000;
type Result<T> = std::result::Result<T, Box<dyn Error>>;
type State = [f64; N];
type Matrix = [[f64; N]; N];

fn ensure(condition: bool, message: &str) -> Result<()> {
    if condition { Ok(()) } else { Err(message.into()) }
}

fn number(tokens: &mut std::str::SplitWhitespace<'_>) -> Result<f64> {
    let value: f64 = tokens.next().ok_or("missing number")?.parse()?;
    ensure(value.is_finite(), "nonfinite number")?;
    Ok(value)
}

fn belief(p: &State) -> Result<()> {
    ensure(p.iter().all(|x| x.is_finite() && *x >= 0.0), "invalid belief support")?;
    ensure((p.iter().sum::<f64>() - 1.0).abs() <= 2e-11, "invalid belief mass")
}

fn validate(q: &Matrix, emission: &[Vec<f64>]) -> Result<()> {
    for (i, row) in q.iter().enumerate() {
        ensure(row[i] <= 0.0 && -row[i] <= 100.0, "exit rate outside profile")?;
        ensure(row.iter().enumerate().all(|(j, x)| j == i || *x >= 0.0), "negative edge")?;
        let outgoing: f64 = row.iter().enumerate().filter(|(j, _)| *j != i).map(|(_, x)| x).sum();
        ensure((outgoing + row[i]).abs() <= 64.0 * f64::EPSILON * outgoing.max(-row[i]), "nonconservative generator")?;
    }
    for row in emission {
        ensure(row.iter().all(|x| *x >= 0.0), "negative emission")?;
        ensure((row.iter().sum::<f64>() - 1.0).abs() <= 1e-13, "invalid emission mass")?;
    }
    Ok(())
}

/// Positive uniformization, retaining a flux accumulator through all segments.
/// The fixed 160 terms at mu <= 8 bound omitted Poisson mass far below FP64 eps.
fn evolve(q: &Matrix, p: &State, dt: f64, rate: &State) -> Result<(State, f64)> {
    ensure(dt.is_finite() && (0.0..=20.0).contains(&dt), "duration outside profile")?;
    let lambda = q.iter().enumerate().map(|(i, row)| -row[i]).fold(0.0_f64, f64::max);
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
            cumulative += term.iter().zip(rate).map(|(x, r)| x * (r / lambda)).sum::<f64>();
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
    ensure(result.iter().all(|x| x.is_finite() && *x >= 0.0) && total.is_finite(), "numeric overflow")?;
    Ok((result, total))
}

fn array(p: &State) -> String {
    format!("[{}]", p.iter().map(|x| format!("{x:.17e}")).collect::<Vec<_>>().join(","))
}

fn run() -> Result<()> {
    let mut text = String::new();
    io::stdin().take(CAPACITY + 1).read_to_string(&mut text)?;
    ensure(text.len() as u64 <= CAPACITY, "input capacity")?;
    let mut tokens = text.split_whitespace();
    ensure(tokens.next() == Some("HCSN_FINITE_40_V1"), "unknown schema")?;
    let mut q = [[0.0; N]; N];
    for row in &mut q { for entry in row { *entry = number(&mut tokens)?; } }
    let mut emissions = Vec::new();
    for columns in [5, 4] {
        for _ in 0..N {
            let mut row = Vec::new();
            for _ in 0..columns { row.push(number(&mut tokens)?); }
            emissions.push(row);
        }
    }
    validate(&q, &emissions)?;
    let mut p = [0.0; N];
    for entry in &mut p { *entry = number(&mut tokens)?; }
    belief(&p)?;
    let mut killed = q;
    let mut rate = [0.0; N];
    for content in 0..4 {
        rate[content] = q[content][32 + content];
        killed[content][32 + content] = 0.0;
    }
    let mut count = 0;
    while let Some(operation) = tokens.next() {
        count += 1;
        ensure(count <= 512, "operation capacity")?;
        match operation {
            "PROP" => {
                let dt = number(&mut tokens)?;
                p = evolve(&q, &p, dt, &rate)?.0;
            }
            "READ" | "REFRESH" => {
                let token: usize = tokens.next().ok_or("missing token")?.parse()?;
                let (offset, columns) = if operation == "READ" { (0, 5) } else { (N, 4) };
                ensure(token < columns, "invalid token")?;
                let mut evidence = 0.0;
                for (i, value) in p.iter_mut().enumerate() {
                    *value *= emissions[offset + i][token];
                    evidence += *value;
                }
                ensure(evidence > 0.0 && evidence.is_finite(), "zero or underflowed observation evidence")?;
                for value in &mut p { *value /= evidence; }
            }
            "RESET" => {
                let mut successor = [0.0; N];
                for (i, value) in p.iter().enumerate() { successor[32 + i % 4] += value; }
                p = successor;
            }
            "MISSING" => {}
            "DIAG" => {
                let dt = number(&mut tokens)?;
                let (future, events) = evolve(&q, &p, dt, &rate)?;
                let (survivor, first) = evolve(&killed, &p, dt, &rate)?;
                println!("{{\"op\":\"DIAG\",\"state\":{},\"future\":{},\"survivor\":{},\"first\":{first:.17e},\"events\":{events:.17e}}}", array(&p), array(&future), array(&survivor));
                continue;
            }
            _ => return Err("unknown operation".into()),
        }
        belief(&p)?;
        println!("{{\"op\":\"{operation}\",\"state\":{}}}", array(&p));
    }
    ensure(count > 0, "empty operation stream")
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
