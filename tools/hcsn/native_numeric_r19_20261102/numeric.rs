//! Forty-state public-generator propagation; no hidden owner paths or targets.
//!
//! Tail bounds use nonnegative powers and explicit row-norm growth. The FP64
//! roundoff allowance is conditional on ordinary IEEE arithmetic without harmful
//! underflow and a small libm exp error. It is an engineering error contract,
//! not a machine-checked interval certificate or a guarantee for arbitrary laws.
use crate::common::{Result, checksum, ensure, read};
use std::collections::BTreeMap;
use std::path::Path;
pub const N: usize = 40;
pub type Vector = [f64; N];
pub type Matrix = [[f64; N]; N];
pub fn identity() -> Matrix {
    let mut a = [[0.; N]; N];
    for (i, r) in a.iter_mut().enumerate() {
        r[i] = 1.;
    }
    a
}
pub fn mul(a: &Matrix, b: &Matrix) -> Matrix {
    let mut c = [[0.; N]; N];
    for i in 0..N {
        for k in 0..N {
            let x = a[i][k];
            if x != 0. {
                for j in 0..N {
                    c[i][j] += x * b[k][j];
                }
            }
        }
    }
    c
}
pub fn row(p: &Vector, a: &Matrix) -> Vector {
    let mut y = [0.; N];
    for i in 0..N {
        for j in 0..N {
            y[j] += p[i] * a[i][j];
        }
    }
    y
}
fn column(a: &Matrix, p: &Vector) -> Vector {
    let mut y = [0.; N];
    for i in 0..N {
        for j in 0..N {
            y[i] += a[i][j] * p[j];
        }
    }
    y
}
#[derive(Clone)]
pub struct Flow {
    pub p: Matrix,
    pub g: Vector,
    pub tail: f64,
    pub reward_tail: f64,
    pub roundoff: f64,
    pub reward_roundoff: f64,
    pub norm_bound: f64,
    pub reward_bound: f64,
    pub order: usize,
}
fn compose(a: &Flow, b: &Flow) -> Flow {
    let mut g = a.g;
    let h = column(&a.p, &b.g);
    for i in 0..N {
        g[i] += h[i];
    }
    let roundoff = a.roundoff * b.norm_bound
        + a.norm_bound * b.roundoff
        + a.roundoff * b.roundoff
        + 2e-14 * (a.norm_bound + a.roundoff) * (b.norm_bound + b.roundoff);
    let reward_roundoff = a.reward_roundoff
        + a.roundoff * b.reward_bound
        + a.norm_bound * b.reward_roundoff
        + a.roundoff * b.reward_roundoff
        + 2e-14
            * (1.
                + a.reward_bound
                + (a.norm_bound + a.roundoff) * (b.reward_bound + b.reward_roundoff));
    Flow {
        p: mul(&a.p, &b.p),
        g,
        tail: a.tail * b.norm_bound + a.norm_bound * b.tail,
        reward_tail: a.reward_tail + a.tail * b.reward_bound + a.norm_bound * b.reward_tail,
        roundoff,
        reward_roundoff,
        norm_bound: a.norm_bound * b.norm_bound,
        reward_bound: a.reward_bound + a.norm_bound * b.reward_bound,
        order: a.order.max(b.order),
    }
}
pub fn propagate(q: &Matrix, t: f64, event: &Vector) -> Result<Flow> {
    ensure(
        t.is_finite() && t >= 0. && t <= 32.,
        "duration outside qualified [0,32] profile",
    )?;
    if t == 0. {
        return Ok(Flow {
            p: identity(),
            g: [0.; N],
            tail: 0.,
            reward_tail: 0.,
            roundoff: 0.,
            reward_roundoff: 0.,
            norm_bound: 1.,
            reward_bound: 0.,
            order: 0,
        });
    }
    let lambda = (0..N).map(|i| -q[i][i]).fold(0., f64::max);
    ensure(
        lambda > 0. && lambda.is_finite(),
        "invalid uniformization rate",
    )?;
    let segments = ((lambda * t / 8.).ceil() as usize).max(1);
    ensure(segments <= 64, "uniformization segment capacity")?;
    let mu = lambda * t / segments as f64;
    let mut m = identity();
    let mut reach = [[false; N]; N];
    for i in 0..N {
        for j in 0..N {
            m[i][j] += q[i][j] / lambda;
            ensure(
                m[i][j] >= 0. && m[i][j].is_finite(),
                "nonpositive uniformization matrix",
            )?;
            reach[i][j] = m[i][j] > 0. || i == j;
        }
        ensure(
            m[i].iter().sum::<f64>() <= 1. + 2e-12,
            "not a substochastic profile",
        )?;
    }
    for k in 0..N {
        for i in 0..N {
            for j in 0..N {
                reach[i][j] |= reach[i][k] && reach[k][j];
            }
        }
    }
    let norm_m = m.iter().map(|r| r.iter().sum::<f64>()).fold(1., f64::max);
    let mut power = identity();
    let mut weight = (-mu).exp();
    let mut p = [[0.; N]; N];
    for i in 0..N {
        p[i][i] = weight;
    }
    let mut g = [0.; N];
    let mut count = [0.; N];
    let rate = event.map(|v| v / lambda);
    let rmax = rate.iter().copied().fold(0., f64::max);
    let mut order = 0;
    let mut tail = 1.;
    let mut reward_tail = 0.;
    for k in 1..=256 {
        let reward = column(&power, &rate);
        for i in 0..N {
            count[i] += reward[i];
        }
        power = mul(&power, &m);
        weight *= mu / k as f64;
        for i in 0..N {
            g[i] += weight * count[i];
            for j in 0..N {
                p[i][j] += weight * power[i][j];
            }
        }
        if k < N - 1 || k as f64 <= mu {
            continue;
        }
        let ratio = mu * norm_m / (k + 2) as f64;
        tail = weight * norm_m.powi(k as i32) * mu * norm_m / (k + 1) as f64 / (1. - ratio);
        let mut minimum = f64::INFINITY;
        for i in 0..N {
            for j in 0..N {
                if reach[i][j] {
                    minimum = minimum.min(p[i][j]);
                }
            }
        }
        ensure(
            minimum >= 1e-250,
            "unrepresentable/unsupported positive transition support",
        )?;
        let count_tail = rmax * mu * (weight * norm_m.powi(k as i32) + tail);
        reward_tail = count_tail;
        let gmin = g
            .iter()
            .copied()
            .filter(|v| *v > 0.)
            .fold(f64::INFINITY, f64::min);
        if tail <= 1e-15 / segments as f64
            && tail <= 1e-12 * minimum / segments as f64
            && count_tail <= 1e-13 / segments as f64
            && count_tail <= 1e-11 * gmin / segments as f64
        {
            order = k;
            break;
        }
    }
    ensure(order > 0, "uniformization truncation capacity")?;
    // Nonnegative matrix products: each length-40 dot has gamma_40 rounding;
    // summation/power accumulation is bounded conservatively by 2*k*gamma_41.
    // Segment composition adds the same multiplication bound per product.
    let gamma = 41. * f64::EPSILON / (1. - 41. * f64::EPSILON);
    let norm_bound = (mu * (norm_m - 1.)).exp();
    let reward_bound = t / segments as f64 * lambda * rmax * norm_bound;
    let small = Flow {
        p,
        g,
        tail,
        reward_tail,
        roundoff: 4. * order as f64 * gamma * norm_bound,
        reward_roundoff: 4. * order as f64 * gamma * reward_bound,
        norm_bound,
        reward_bound,
        order,
    };
    let mut result = Flow {
        p: identity(),
        g: [0.; N],
        tail: 0.,
        reward_tail: 0.,
        roundoff: 0.,
        reward_roundoff: 0.,
        norm_bound: 1.,
        reward_bound: 0.,
        order,
    };
    let mut base = small;
    let mut n = segments;
    while n > 0 {
        if n % 2 == 1 {
            result = compose(&result, &base);
        }
        n /= 2;
        if n > 0 {
            base = compose(&base, &base);
        }
    }
    ensure(result.roundoff <= 1.3e-9, "roundoff budget exceeded")?;
    Ok(result)
}

pub struct Model {
    pub id: String,
    pub q: Matrix,
    pub prior: Vector,
    pub read: [[f64; 5]; N],
    pub refresh: [[f64; 4]; N],
    pub cache: BTreeMap<u64, Matrix>,
    pub max_tail: f64,
    pub max_roundoff: f64,
}
impl Model {
    pub fn open(path: &Path) -> Result<Self> {
        let text = read(path)?;
        let mut lines = text.lines();
        let h: Vec<_> = lines.next().ok_or("model header")?.split('\t').collect();
        ensure(h.len() == 2 && h[0] == "MODEL", "model header")?;
        let mut data = BTreeMap::new();
        for line in lines {
            let mut fields = line.split_whitespace();
            let key = fields.next().ok_or("model field")?;
            let values: std::result::Result<Vec<f64>, _> = fields.map(str::parse).collect();
            ensure(data.insert(key, values?).is_none(), "duplicate model field")?;
        }
        let qv = data.get("Q").ok_or("Q")?;
        let pv = data.get("PRIOR").ok_or("PRIOR")?;
        let er = data.get("READ").ok_or("READ")?;
        let ef = data.get("REFRESH").ok_or("REFRESH")?;
        ensure(
            qv.len() == 1600 && pv.len() == 40 && er.len() == 200 && ef.len() == 160,
            "model shape",
        )?;
        let mut q = [[0.; N]; N];
        let mut prior = [0.; N];
        let mut read = [[0.; 5]; N];
        let mut refresh = [[0.; 4]; N];
        for i in 0..N {
            prior[i] = pv[i];
            for j in 0..N {
                q[i][j] = qv[i * N + j];
                ensure(
                    q[i][j].is_finite() && (i == j || q[i][j] >= 0.),
                    "generator entry",
                )?;
            }
            ensure(q[i][i] <= 0., "positive generator diagonal")?;
            ensure(q[i].iter().sum::<f64>().abs() < 5e-12, "generator mass")?;
            for j in 0..5 {
                read[i][j] = er[i * 5 + j];
            }
            for j in 0..4 {
                refresh[i][j] = ef[i * 4 + j];
            }
            ensure(
                read[i]
                    .iter()
                    .chain(refresh[i].iter())
                    .all(|v| v.is_finite() && *v >= 0.)
                    && (read[i].iter().sum::<f64>() - 1.).abs() < 1e-13
                    && (refresh[i].iter().sum::<f64>() - 1.).abs() < 1e-13,
                "emission profile",
            )?;
        }
        ensure(
            prior.iter().all(|v| v.is_finite() && *v >= 0.)
                && (prior.iter().sum::<f64>() - 1.).abs() < 1e-12,
            "prior",
        )?;
        Ok(Self {
            // Header identity is metadata. Owned-state binding also covers the
            // actual serialized model bytes in this trusted-host profile.
            id: format!("{}:bytes-{:016x}", h[1], checksum(text.as_bytes())),
            q,
            prior,
            read,
            refresh,
            cache: BTreeMap::new(),
            max_tail: 0.,
            max_roundoff: 0.,
        })
    }
    pub fn transition(&mut self, t: f64) -> Result<Matrix> {
        let key = t.to_bits();
        if let Some(p) = self.cache.get(&key) {
            return Ok(*p);
        }
        let flow = propagate(&self.q, t, &[0.; N])?;
        self.max_tail = self.max_tail.max(flow.tail);
        self.max_roundoff = self.max_roundoff.max(flow.roundoff);
        self.cache.insert(key, flow.p);
        Ok(flow.p)
    }
    pub fn observe(&self, p: &Vector, token: usize, quality: usize) -> Result<Vector> {
        ensure(token < if quality == 2 { 5 } else { 4 }, "token")?;
        let mut out = *p;
        for i in 0..N {
            out[i] *= if quality == 2 {
                self.read[i][token]
            } else {
                self.refresh[i][token]
            };
        }
        let mass = out.iter().sum::<f64>();
        ensure(
            mass > 1e-250 && mass.is_finite(),
            "impossible/unqualified observation likelihood",
        )?;
        for x in &mut out {
            *x /= mass;
        }
        Ok(out)
    }
}
pub fn project(p: &Vector) -> Vector {
    let mut groups = [0.; 8];
    for i in 0..N {
        groups[if i < 32 { i % 4 } else { 4 + i % 4 }] += p[i];
    }
    let mut out = [0.; N];
    for i in 0..N {
        let group = if i < 32 { i % 4 } else { 4 + i % 4 };
        out[i] = groups[group] / if i < 32 { 8. } else { 2. };
    }
    out
}
pub fn answer(p: &Vector, transition: &Matrix) -> (usize, f64) {
    let future = row(p, transition);
    let mut reward = [0.; 4];
    for i in 0..N {
        reward[i % 4] += future[i];
    }
    let mut best = 0;
    for j in 1..4 {
        if reward[j] > reward[best] {
            best = j;
        }
    }
    let second = reward
        .iter()
        .enumerate()
        .filter(|(i, _)| *i != best)
        .map(|(_, v)| *v)
        .fold(f64::NEG_INFINITY, f64::max);
    (best, reward[best] - second)
}
pub fn values(
    model: &Model,
    p: &Vector,
    remaining: usize,
    dt: f64,
    read_cost: f64,
    refresh_cost: f64,
    anchored: bool,
    ps: &[Matrix; 4],
) -> [f64; 4] {
    let future = row(p, &ps[remaining]);
    let mut rewards = [0.; 4];
    for i in 0..N {
        rewards[i % 4] += future[i];
    }
    let mut out = [f64::NEG_INFINITY; 4];
    out[0] = rewards.iter().copied().fold(0., f64::max);
    if remaining == 0 {
        return out;
    }
    let advanced = row(p, &ps[1]);
    out[1] = values(
        model,
        &advanced,
        remaining - 1,
        dt,
        read_cost,
        refresh_cost,
        anchored,
        ps,
    )
    .iter()
    .copied()
    .fold(f64::NEG_INFINITY, f64::max)
        - 0.003 * dt;
    for action in 2..4 {
        let slots = if action == 3 { 2 } else { 1 };
        if slots > remaining {
            continue;
        }
        let before = row(p, &ps[slots]);
        let tokens = if action == 2 { 5 } else { 4 };
        let mut gain = 0.;
        for token in 0..tokens {
            let mut post = before;
            for i in 0..N {
                post[i] *= if action == 2 {
                    model.read[i][token]
                } else {
                    model.refresh[i][token]
                };
            }
            let mass = post.iter().sum::<f64>();
            if mass > 0. {
                for x in &mut post {
                    *x /= mass;
                }
            } else {
                post = model.prior;
            }
            if anchored {
                post = project(&post);
            }
            let next = values(
                model,
                &post,
                remaining - slots,
                dt,
                read_cost,
                refresh_cost,
                anchored,
                ps,
            );
            gain += mass * next.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        }
        out[action] =
            gain - if action == 2 { read_cost } else { refresh_cost } - 0.003 * slots as f64 * dt;
    }
    out
}
