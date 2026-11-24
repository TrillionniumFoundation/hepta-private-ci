mod compiler;
mod planner;
use std::io::Read;

fn run() -> Result<(), String> {
    let mut text = String::new();
    std::io::stdin()
        .take(65537)
        .read_to_string(&mut text)
        .map_err(|e| e.to_string())?;
    if text.len() > 65536 {
        return Err("input exceeds 65536-byte cap".into());
    }
    let mut tokens = text.split_whitespace();
    let schema = tokens.next();
    if schema == Some("HEPTA_QVI_COMPILE_V1") {
        let n = tokens
            .next()
            .ok_or("missing dimensions")?
            .parse::<usize>()
            .map_err(|e| e.to_string())?;
        let values: Result<Vec<f64>, String> = tokens
            .map(|s| s.parse::<f64>().map_err(|e| e.to_string()))
            .collect();
        let values = values?;
        if n == 0 || n > 16 || values.len() != 1 + 2 * n {
            return Err("bad compiler payload".into());
        }
        let (parameters, upper) =
            compiler::compile(&values[1..1 + n], &values[1 + n..], values[0])?;
        println!(
            "{{\"schema\":\"hepta-qvi-compiled-parameters-v1\",\"parameters\":{parameters:?},\"exact_delta_outward_upper\":{upper:?}}}"
        );
        return Ok(());
    }
    if schema != Some("HEPTA_QVI_EDIT_V1") {
        return Err("bad schema".into());
    }
    let n = tokens
        .next()
        .ok_or("missing rows")?
        .parse::<usize>()
        .map_err(|e| e.to_string())?;
    let m = tokens
        .next()
        .ok_or("missing columns")?
        .parse::<usize>()
        .map_err(|e| e.to_string())?;
    if !(1..=64).contains(&n) || !(1..=3).contains(&m) {
        return Err("bad dimensions".into());
    }
    let values: Result<Vec<f64>, String> = tokens
        .map(|s| s.parse::<f64>().map_err(|e| e.to_string()))
        .collect();
    let values = values?;
    if values.len() != 11 + n * (m + 1) || values.iter().any(|v| !v.is_finite()) {
        return Err("bad finite payload length or value".into());
    }
    let budget = values[0];
    let tolerance = values[1];
    let theta: [f64; 8] = values[2..10].try_into().map_err(|_| "bad theta")?;
    let target_boundary = values[10];
    let (cost, boundary_error) = planner::cost_edit(&theta, target_boundary, budget)?;
    let mut matrix = Vec::new();
    let mut target = Vec::new();
    for row in values[11..].chunks_exact(m + 1) {
        matrix.push(row[..m].to_vec());
        target.push(row[m]);
    }
    let result = planner::solve(&planner::Problem {
        matrix,
        target,
        budget,
        tolerance,
    })?;
    println!(
        "{{\"schema\":\"hepta-qvi-native-plan-v1\",\"status\":\"{}\",\"rows\":{n},\"columns\":{m},\"cost\":{cost:.17e},\"cost_delta\":{:.17e},\"boundary_error\":{boundary_error:.17e},\"delta\":{:?},\"residuals\":{:?},\"squared_error\":{:.17e},\"fit_residual_certified_upper\":{:.17e},\"dual_infeasibility_certified_lower\":{:.17e},\"dual_witness\":{:?},\"rank\":{},\"requires_full_forward_validation\":true,\"certificate_scope\":\"RECORDED_FP64_LINEAR_SYSTEM\"}}",
        result.status,
        cost - theta[7],
        result.delta,
        result.residuals,
        result.squared_error,
        result.residual_upper,
        result.infeasible_lower,
        result.witness,
        result.rank
    );
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("No edit: {error}");
        std::process::exit(2);
    }
}
