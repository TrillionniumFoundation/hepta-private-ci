//! Research-only numerical parity for four standardized linear continuation heads.
//! No encoder, decoder, model authorization, production owner, or learned STOP.
use std::io::{self, Read};

const SCHEMA: &str = "hepta.ndu-v6.continuation-linear.v1";
const OUTPUT: &str = "hepta.ndu-v6.continuation-linear-output.v1";
const ACTIONS: &str = "refine_semantic\trefine_image\trefine_text\tcouple";
const MAX_BYTES: u64 = 16 * 1024 * 1024;

fn values(line: Option<&str>, label: &str, n: usize) -> Result<Vec<f64>, String> {
    let mut fields = line.ok_or("missing row")?.split('\t');
    if fields.next() != Some(label) {
        return Err("unexpected row label".into());
    }
    let row: Result<Vec<_>, _> = fields.map(str::parse::<f64>).collect();
    let row = row.map_err(|_| "invalid number")?;
    if row.len() != n || row.iter().any(|v| !v.is_finite()) {
        return Err("invalid row dimension or nonfinite number".into());
    }
    Ok(row)
}

fn run() -> Result<String, String> {
    let mut input = String::new();
    io::stdin()
        .lock()
        .take(MAX_BYTES + 1)
        .read_to_string(&mut input)
        .map_err(|_| "invalid UTF-8 input")?;
    if input.len() as u64 > MAX_BYTES {
        return Err("input exceeds byte limit".into());
    }
    let mut lines = input.lines();
    let header: Vec<_> = lines.next().ok_or("missing header")?.split('\t').collect();
    if header.len() != 3 || header[0] != SCHEMA {
        return Err("unsupported schema or header".into());
    }
    let f = header[1]
        .parse::<usize>()
        .map_err(|_| "invalid feature count")?;
    let b = header[2]
        .parse::<usize>()
        .map_err(|_| "invalid batch count")?;
    if !(1..=8192).contains(&f) || !(1..=4096).contains(&b) {
        return Err("dimension outside bounds".into());
    }
    if lines.next() != Some(format!("actions\t{ACTIONS}").as_str()) {
        return Err("unknown action order".into());
    }
    let mean = values(lines.next(), "mean", f)?;
    let scale = values(lines.next(), "scale", f)?;
    if scale.iter().any(|s| *s <= 0.0) {
        return Err("scale must be positive".into());
    }
    let mut weight = Vec::with_capacity(f + 1);
    for _ in 0..=f {
        weight.push(values(lines.next(), "weight", 4)?);
    }
    let mut output = format!("{OUTPUT}\t{b}\nSTOP\t{ACTIONS}\n");
    for _ in 0..b {
        let x = values(lines.next(), "features", f)?;
        let mut result = [0.0; 4];
        for i in 0..f {
            let z = (x[i] - mean[i]) / scale[i];
            if !z.is_finite() {
                return Err("standardization overflow".into());
            }
            for j in 0..4 {
                result[j] += z * weight[i][j];
            }
        }
        for j in 0..4 {
            result[j] += weight[f][j];
        }
        if result.iter().any(|v| !v.is_finite()) {
            return Err("output overflow".into());
        }
        output.push_str("0.00000000000000000e0");
        for v in result {
            output.push_str(&format!("\t{v:.17e}"));
        }
        output.push('\n');
    }
    if lines.next().is_some() {
        return Err("trailing rows".into());
    }
    Ok(output)
}

fn main() {
    match run() {
        Ok(output) => print!("{output}"),
        Err(error) => {
            eprintln!("continuation-head rejected: {error}");
            std::process::exit(2);
        }
    }
}
