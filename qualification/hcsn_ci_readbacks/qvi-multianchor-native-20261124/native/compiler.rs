fn next_toward(value: f64, target: f64) -> f64 {
    if value == target {
        return target;
    }
    if value == 0.0 {
        return f64::from_bits(1).copysign(target);
    }
    f64::from_bits(if (value > 0.0) == (target > value) {
        value.to_bits() + 1
    } else {
        value.to_bits() - 1
    })
}

/// Compose floating parameters inside the original box, with outward bounds.
pub fn compile(base: &[f64], delta: &[f64], budget: f64) -> Result<(Vec<f64>, Vec<f64>), String> {
    if base.is_empty()
        || base.len() > 16
        || base.len() != delta.len()
        || !budget.is_finite()
        || !(0.0..=0.1).contains(&budget)
        || base.iter().any(|x| !x.is_finite() || x.abs() > 1e6)
        || delta.iter().any(|x| !x.is_finite() || x.abs() > budget)
    {
        return Err("invalid bounded checkpoint composition".into());
    }
    let mut parameters = Vec::new();
    let mut bounds = Vec::new();
    for (&original, &change) in base.iter().zip(delta) {
        if change == 0.0 {
            parameters.push(original);
            bounds.push(0.0);
            continue;
        }
        let mut value = original + change;
        let mut upper = 0.0;
        for _ in 0..8 {
            if value == original {
                upper = 0.0;
                break;
            }
            let difference = (value - original).abs();
            // One upward ULP encloses the exact difference of the FP64 inputs.
            upper = f64::from_bits(difference.to_bits() + 1);
            if upper <= budget {
                break;
            }
            value = next_toward(value, original);
        }
        if upper > budget {
            return Err("unable to compile inside unchanged parameter box".into());
        }
        parameters.push(value);
        bounds.push(upper);
    }
    Ok((parameters, bounds))
}

#[cfg(test)]
#[path = "compiler_tests.rs"]
mod tests;
