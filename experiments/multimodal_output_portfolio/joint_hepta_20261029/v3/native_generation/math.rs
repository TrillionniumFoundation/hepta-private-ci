//! FP64 scalar operators for the declared frozen-interval Hepta profile.
//! erfc is supplied by the Linux system math library, not Python/Torch.
use crate::codec::{Packet, Result};
#[link(name = "m")]
unsafe extern "C" {
    fn erfc(x: f64) -> f64;
}
pub fn sigmoid(x: f64) -> f64 {
    if x >= 0.0 {
        1.0 / (1.0 + (-x).exp())
    } else {
        let e = x.exp();
        e / (1.0 + e)
    }
}
pub fn softplus(x: f64) -> f64 {
    if x > 20.0 { x } else { x.exp().ln_1p() }
}
pub fn logcdf(x: f64) -> f64 {
    if x > -37.0 {
        return (0.5 * unsafe { erfc(-x / std::f64::consts::SQRT_2) }).ln();
    }
    let z = -x;
    let mut term = 1.0;
    let mut sum = 1.0;
    for i in 1..20 {
        term *= -(2 * i - 1) as f64 / (z * z);
        sum += term;
        if term.abs() < 1e-17 {
            break;
        }
    }
    -0.5 * z * z - z.ln() - 0.5 * (2.0 * std::f64::consts::PI).ln() + sum.ln()
}
fn log_erfcx(x: f64) -> f64 {
    if x < 26.0 {
        return x * x + unsafe { erfc(x) }.ln();
    }
    let mut term = 1.0;
    let mut sum = 1.0;
    for i in 1..20 {
        term *= -(2 * i - 1) as f64 / (2.0 * x * x);
        sum += term;
        if term.abs() < 1e-17 {
            break;
        }
    }
    sum.ln() - x.ln() - 0.5 * std::f64::consts::PI.ln()
}
pub fn passage(voltage: f64, boundary: f64, drift: f64, diffusion: f64, dt: f64) -> (f64, f64) {
    let distance = boundary - voltage;
    if distance <= 0.0 {
        return (0.0, 1.0);
    }
    if dt == 0.0 {
        return (voltage, 0.0);
    }
    let scale = diffusion * dt.sqrt();
    let z = (drift * dt - distance) / scale;
    let rz = (-drift * dt - distance) / scale;
    let image = if rz <= 0.0 {
        -std::f64::consts::LN_2 - 0.5 * z * z + log_erfcx(-rz / std::f64::consts::SQRT_2)
    } else {
        2.0 * drift * distance / (diffusion * diffusion) + logcdf(rz)
    };
    let base = logcdf(z);
    let largest = base.max(image);
    let logf = (largest + ((base - largest).exp() + (image - largest).exp()).ln()).min(0.0);
    let event = logf.exp();
    let survival = -logf.exp_m1();
    (
        (voltage + drift * dt) * survival - 2.0 * distance * image.exp(),
        event,
    )
}
pub fn linear(p: &Packet, name: &str, input: &[f64]) -> Result<Vec<f64>> {
    let w = p
        .tensors
        .get(&format!("{name}.weight"))
        .ok_or_else(|| format!("missing {name}.weight"))?;
    if w.shape.len() != 2 || w.shape[1] != input.len() {
        return Err(format!("linear shape {name}"));
    }
    let bias = p.tensors.get(&format!("{name}.bias"));
    let mut out = vec![0.0; w.shape[0]];
    for (i, row) in w.data.chunks_exact(input.len()).enumerate() {
        let dot: f64 = row.iter().zip(input).map(|(a, b)| a * b).sum();
        out[i] = dot + bias.map_or(0.0, |t| t.data[i]);
    }
    if out.iter().any(|v| !v.is_finite()) {
        return Err(format!("nonfinite linear {name}"));
    }
    Ok(out)
}
pub fn tanh(mut x: Vec<f64>) -> Vec<f64> {
    for v in &mut x {
        *v = v.tanh();
    }
    x
}
pub fn cat(parts: &[&[f64]]) -> Vec<f64> {
    parts.iter().flat_map(|v| v.iter().copied()).collect()
}
pub fn norm(p: &Packet, name: &str, x: &[f64]) -> Result<Vec<f64>> {
    let w = p.get(&format!("{name}.weight"))?;
    let b = p.get(&format!("{name}.bias"))?;
    let mean = x.iter().sum::<f64>() / x.len() as f64;
    let var = x.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / x.len() as f64;
    Ok(x.iter()
        .enumerate()
        .map(|(i, v)| (v - mean) / (var + 1e-5).sqrt() * w[i] + b[i])
        .collect())
}
/// SplitMix64 counter law is separately versioned; it is not Torch's RNG.
pub fn uniform(seed: u64, index: u64) -> f64 {
    let mut x = seed.wrapping_add(index.wrapping_add(1).wrapping_mul(0x9e3779b97f4a7c15));
    x = (x ^ (x >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    x = (x ^ (x >> 27)).wrapping_mul(0x94d049bb133111eb);
    x ^= x >> 31;
    ((x >> 11) as f64 + 0.5) / 9007199254740992.0
}
pub fn normal(seed: u64, index: u64) -> f64 {
    (-2.0 * uniform(seed, index * 2).ln()).sqrt()
        * (2.0 * std::f64::consts::PI * uniform(seed, index * 2 + 1)).cos()
}
