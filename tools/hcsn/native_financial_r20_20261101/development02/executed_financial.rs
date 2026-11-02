//! Native construction of the declared R12/R15 finite financial-parameter law.
//! This is a static H-X boundary parameterization, not a continuum neural QVI.
use std::error::Error;

pub type Result<T> = std::result::Result<T, Box<dyn Error>>;

pub struct Model {
    pub q: [[f64; 40]; 40],
    pub read: [[f64; 5]; 40],
    pub refresh: [[f64; 4]; 40],
    pub prior: [f64; 40],
    pub boundary: f64,
}

const X: [f64; 8] = [
    0.0950125098376374405,
    0.281603550779258915,
    0.458016777657227370,
    0.617876244402643771,
    0.755404408355002999,
    0.865631202387831755,
    0.944575023073232600,
    0.989400934991649939,
];
const W: [f64; 8] = [
    0.189450610455068641,
    0.182603415044923639,
    0.169156519395002647,
    0.149595988816576708,
    0.124628971255534071,
    0.0951585116824926053,
    0.0622535239386474565,
    0.0271524594117541762,
];

fn ensure(condition: bool, message: &str) -> Result<()> {
    if condition {
        Ok(())
    } else {
        Err(message.into())
    }
}

fn integrate(a: f64, b: f64, f: impl Fn(f64) -> f64) -> f64 {
    let (middle, half) = ((a + b) / 2.0, (b - a) / 2.0);
    let mut total = 0.0;
    for (x, w) in X.iter().zip(W) {
        total += w * (f(middle - half * x) + f(middle + half * x));
    }
    half * total
}

/// Positive normal-tail integral on twelve unit intervals; no tail subtraction.
pub fn normal_cdf(x: f64) -> Result<f64> {
    ensure(
        x.is_finite() && x.abs() <= 12.0,
        "CDF argument outside profile",
    )?;
    if x == 0.0 {
        return Ok(0.5);
    }
    if x > 0.0 {
        return Ok(1.0 - normal_cdf(-x)?);
    }
    let u = -x;
    let mut integral = 0.0;
    for k in 0..12 {
        integral += integrate(k as f64, (k + 1) as f64, |t| (-u * t - t * t / 2.0).exp());
    }
    Ok((-u * u / 2.0).exp() * integral / (2.0 * std::f64::consts::PI).sqrt())
}

/// Divided difference B(y), evaluated by its smooth derivative integral.
fn b_function(z: f64, s: f64, y: f64, tail: f64) -> f64 {
    integrate(0.0, 1.0, |t| {
        let at = -z + t * (z + y);
        s * (-0.5 * at * at * s * s).exp() / (2.0 * std::f64::consts::PI).sqrt()
            + at * s * s * (0.5 * (z - at) * (z + at) * s * s).exp() * tail
    })
}

pub fn boundary(sigma: f64, liquidity: f64, maturity: f64) -> Result<f64> {
    ensure(
        sigma.is_finite() && (0.15..=0.4).contains(&sigma),
        "sigma outside R12 box",
    )?;
    ensure(
        liquidity.is_finite() && (0.002..=0.04).contains(&liquidity),
        "liquidity outside R12 box",
    )?;
    ensure(
        maturity.is_finite() && (0.5..=2.0).contains(&maturity),
        "maturity outside R12 box",
    )?;
    let (r, delta, alpha, tax, coupon, principal) = (0.08, 0.02, 0.60, 0.27, 6.39, 61.68);
    let s2 = sigma * sigma;
    let rate = r + liquidity;
    let a = (r - delta - s2 / 2.0) / s2;
    let z = (a * a + 2.0 * r / s2).sqrt();
    let zt = (a * a + 2.0 * rate / s2).sqrt();
    let eta = if a >= 0.0 {
        2.0 * r / (s2 * (z + a))
    } else {
        z - a
    };
    let gamma = 2.0 * r / (s2 * eta);
    let s = sigma * maturity.sqrt();
    let c = coupon / maturity;
    let q = principal / maturity - c / rate;
    let discount = (-rate * maturity).exp();
    let cost = (1.0 - tax) * coupon - (-rate * maturity).exp_m1() * q;
    let tail = normal_cdf(-z * s)?;
    let bs = b_function(z, s, -zt, tail) + b_function(z, s, zt, tail);
    let ba = b_function(z, s, -a, tail) + b_function(z, s, a, tail);
    let value = (cost / eta + q * discount * ba + c / rate * bs)
        / (0.5 * s2 * (gamma + 1.0) + alpha / maturity * bs);
    let flow = delta * value - (1.0 - tax) * coupon + (alpha * value - principal) / maturity;
    let scale = (delta * value).abs()
        + ((1.0 - tax) * coupon).abs()
        + ((alpha * value).abs() + principal.abs()) / maturity;
    ensure(
        value.is_finite() && value > 0.0 && flow < -64.0 * f64::EPSILON * scale.max(1.0),
        "inadmissible static boundary",
    )?;
    Ok(value)
}

fn edge(q: &mut [[f64; 40]; 40], source: usize, destination: usize, rate: f64) {
    q[source][destination] += rate;
    q[source][source] -= rate;
}

pub fn construct(sigma: f64, liquidity: f64, maturity: f64) -> Result<Model> {
    let boundary = boundary(sigma, liquidity, maturity)?;
    let reset = (90.0 / boundary).ln();
    let centers: [f64; 8] = std::array::from_fn(|i| (i as f64 + 0.5) * 0.1);
    ensure(
        reset > centers[0] && reset < centers[7],
        "reset outside center interval",
    )?;
    ensure(
        centers
            .iter()
            .all(|x| (reset - x).abs() > 32.0 * f64::EPSILON),
        "reset interpolation knot",
    )?;
    let lower = centers.iter().take_while(|x| **x < reset).count() - 1;
    let fraction = (reset - centers[lower]) / 0.1;
    let mut weights = [0.0; 8];
    weights[lower] = 1.0 - fraction;
    weights[lower + 1] = fraction;
    let diffusion = sigma * sigma / 2.0;
    let drift = 0.08 - 0.02 - diffusion;
    let rates = [
        diffusion / 0.01 + drift / 0.2,
        diffusion / 0.01 - drift / 0.2,
        2.0 * diffusion / 0.01,
    ];
    ensure(
        rates.iter().all(|r| r.is_finite() && *r > 0.0),
        "invalid centered rate",
    )?;
    let mut model = Model {
        q: [[0.0; 40]; 40],
        read: [[0.0; 5]; 40],
        refresh: [[0.01; 4]; 40],
        prior: [0.0; 40],
        boundary,
    };
    for phase in 0..8 {
        for content in 0..4 {
            let source = 4 * phase + content;
            if phase < 7 {
                edge(&mut model.q, source, source + 4, rates[0]);
            }
            if phase > 0 {
                edge(&mut model.q, source, source - 4, rates[1]);
            } else {
                edge(&mut model.q, source, 32 + content, rates[2]);
            }
            model.prior[source] = weights[phase] / 4.0;
        }
    }
    let recovery = 2.0 / 0.35;
    for content in 0..4 {
        edge(&mut model.q, 32 + content, 36 + content, recovery);
        for (phase, weight) in weights.iter().enumerate() {
            for destination in 0..4 {
                let retention = if content == destination {
                    0.875
                } else {
                    0.125 / 3.0
                };
                edge(
                    &mut model.q,
                    36 + content,
                    4 * phase + destination,
                    recovery * weight * retention,
                );
            }
        }
    }
    for state in 0..40 {
        if state < 32 {
            model.read[state] = [0.1, 0.1, 0.1, 0.1, 0.0];
            model.read[state][state % 4] = 0.7;
        } else {
            model.read[state][4] = 1.0;
        }
        model.refresh[state][state % 4] = 0.97;
    }
    Ok(model)
}
