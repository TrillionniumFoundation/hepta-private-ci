//! R7 finite-state laws. The upwind CTMC is not continuous OU first passage.
use std::f64::consts::SQRT_2;

#[link(name = "m")]
unsafe extern "C" {
    fn erfc(x: f64) -> f64;
}

pub fn cdf(z: f64) -> f64 {
    // libm preserves the small lower tail; 1 + erf would cancel it.
    0.5 * unsafe { erfc(-z / SQRT_2) }
}

fn interval(a: f64, b: f64) -> f64 {
    if a > 0.0 {
        cdf(-a) - cdf(-b)
    } else {
        cdf(b) - cdf(a)
    }
}

pub fn sigmoid(x: f64) -> f64 {
    if x >= 0.0 {
        1.0 / (1.0 + (-x).exp())
    } else {
        x.exp() / (1.0 + x.exp())
    }
}

#[derive(Clone)]
pub struct Kernel {
    pub n: usize,
    pub mode: String,
    pub grid: Vec<f64>,
    pub edges: Vec<f64>,
    pub leak: f64,
    pub diffusion: f64,
    pub boundary: f64,
    pub recovery: f64,
    pub resets: [Vec<f64>; 2],
    pub basis: Vec<[f64; 4]>,
}

impl Kernel {
    pub fn new(n: usize, mode: &str, raw: [f64; 6]) -> Result<Self, String> {
        if n < 5 || n > 63 || n % 2 != 1 || raw.iter().any(|x| !x.is_finite() || x.abs() > 100.0) {
            return Err("kernel parameter envelope".into());
        }
        if !["direct", "continuous", "clocked", "first_passage"].contains(&mode) {
            return Err("unsupported finite-law kernel version/mode".into());
        }
        let boundary = 0.35 + 1.65 * sigmoid(raw[2]);
        let normal: Vec<_> = (1..=n).map(|i| -1.0 + 2.0 * i as f64 / (n + 1) as f64).collect();
        let mut edges = vec![-1.0];
        edges.extend(normal.windows(2).map(|w| (w[0] + w[1]) / 2.0));
        edges.push(1.0);
        let resets = [raw[3], raw[4]].map(|r| {
            let center = 0.75 * r.tanh();
            (0..n)
                .map(|i| {
                    let a = (edges[i] - center) / 0.08;
                    let b = (edges[i + 1] - center) / 0.08;
                    if i == 0 {
                        cdf(b)
                    } else if i == n - 1 {
                        cdf(-a)
                    } else {
                        interval(a, b)
                    }
                })
                .collect::<Vec<_>>()
        });
        let grid: Vec<_> = normal.iter().map(|x| boundary * x).collect();
        let mut basis: Vec<_> = grid.iter().map(|x| [*x, x * x, 0.0, 0.0]).collect();
        for (i, reset) in resets.iter().enumerate() {
            let first: f64 = reset.iter().zip(&grid).map(|(p, x)| p * x).sum();
            let second: f64 = reset.iter().zip(&grid).map(|(p, x)| p * x * x).sum();
            basis.push([
                first,
                second,
                if i == 0 { 1.0 } else { 0.0 },
                if i == 1 { 1.0 } else { 0.0 },
            ]);
        }
        Ok(Self {
            n,
            mode: mode.into(),
            grid,
            edges: edges.iter().map(|x| boundary * x).collect(),
            leak: 2.0 * sigmoid(raw[0]),
            diffusion: 0.05 + 0.75 * sigmoid(raw[1]),
            boundary,
            recovery: 0.05 + 0.9 * sigmoid(raw[5]),
            resets,
            basis,
        })
    }

    pub fn transition(&self, drive: f64, dt: f64) -> Result<Vec<Vec<f64>>, String> {
        if !drive.is_finite() || drive.abs() > 1.5 + 1e-12 || !dt.is_finite() || dt <= 0.0 || dt > 128.0 {
            return Err("drive/duration envelope".into());
        }
        let n = self.n;
        let s = n + 2;
        let mut matrix = vec![vec![0.0; s]; s];
        if self.mode == "direct" {
            for (i, row) in matrix.iter_mut().enumerate() {
                row[i] = 1.0;
            }
            return Ok(matrix);
        }
        if self.mode == "first_passage" {
            matrix = self.first_passage(drive, dt)?;
        } else {
            let decay = (-self.leak * dt).exp();
            let integral = -(-self.leak * dt).exp_m1() / self.leak;
            let sd = (self.diffusion.powi(2) * -(-2.0 * self.leak * dt).exp_m1() / (2.0 * self.leak)).sqrt();
            for (i, row) in matrix.iter_mut().take(n).enumerate() {
                let mean = decay * self.grid[i] + integral * drive;
                let z: Vec<_> = self.edges.iter().map(|x| (x - mean) / sd).collect();
                for j in 0..n {
                    row[j] = if self.mode == "continuous" && j == 0 {
                        cdf(z[1])
                    } else if self.mode == "continuous" && j == n - 1 {
                        cdf(-z[n - 1])
                    } else {
                        interval(z[j], z[j + 1])
                    };
                }
                if self.mode == "clocked" {
                    row[n] = cdf(-z[n]);
                    row[n + 1] = cdf(z[0]);
                }
            }
        }
        // Refractory cohorts at tick start release only at the tick endpoint.
        for d in 0..2 {
            matrix[n + d].fill(0.0);
            if self.mode == "continuous" {
                matrix[n + d][n + d] = 1.0;
            } else {
                for j in 0..n {
                    matrix[n + d][j] = self.recovery * self.resets[d][j];
                }
                matrix[n + d][n + d] = 1.0 - self.recovery;
            }
        }
        for row in &matrix {
            simplex(row, /*tolerance*/ 2e-10)?;
        }
        Ok(matrix)
    }

    fn first_passage(&self, drive: f64, dt: f64) -> Result<Vec<Vec<f64>>, String> {
        let n = self.n;
        let s = n + 2;
        let spacing = 2.0 * self.boundary / (n + 1) as f64;
        let diffusion = 0.5 * self.diffusion.powi(2) / spacing.powi(2);
        let rates: Vec<_> = self
            .grid
            .iter()
            .map(|x| {
                let drift = drive - self.leak * x;
                (
                    diffusion + drift.max(0.0) / spacing,
                    diffusion + (-drift).max(0.0) / spacing,
                )
            })
            .collect();
        let rate = rates.iter().map(|(a, b)| a + b).fold(0.0, f64::max);
        let squares = ((rate * dt / 16.0).log2().ceil().max(0.0)) as u32;
        if squares > 20 {
            return Err("uniformization work envelope".into());
        }
        let lambda = rate * dt / 2.0_f64.powi(squares as i32);
        let mut power = vec![vec![0.0; s]; s];
        for (i, row) in power.iter_mut().enumerate() {
            row[i] = 1.0;
        }
        let mut weight = (-lambda).exp();
        let mut sum: Vec<Vec<_>> = power
            .iter()
            .map(|r| r.iter().map(|v| weight * v).collect())
            .collect();
        for k in 1..=160 {
            let mut next = vec![vec![0.0; s]; s];
            for i in 0..s {
                for j in 0..n {
                    let (up, down) = rates[j];
                    next[i][j] += power[i][j] * (1.0 - (up + down) / rate);
                    next[i][if j + 1 < n { j + 1 } else { n }] += power[i][j] * up / rate;
                    next[i][if j > 0 { j - 1 } else { n + 1 }] += power[i][j] * down / rate;
                }
                next[i][n] += power[i][n];
                next[i][n + 1] += power[i][n + 1];
            }
            power = next;
            weight *= lambda / k as f64;
            for i in 0..s {
                for j in 0..s {
                    sum[i][j] += weight * power[i][j];
                }
            }
            if k > lambda as usize && weight < 1e-18 {
                break;
            }
            if k == 160 {
                return Err("uniformization did not converge".into());
            }
        }
        for _ in 0..squares {
            let mut squared = vec![vec![0.0; s]; s];
            for i in 0..s {
                for k in 0..s {
                    for j in 0..s {
                        squared[i][j] += sum[i][k] * sum[k][j];
                    }
                }
            }
            sum = squared;
        }
        Ok(sum)
    }
}

pub fn simplex(p: &[f64], tolerance: f64) -> Result<(), String> {
    if p.is_empty()
        || p.iter().any(|x| !x.is_finite() || *x < 0.0)
        || (p.iter().sum::<f64>() - 1.0).abs() > tolerance
    {
        Err("finite nonnegative probability simplex required".into())
    } else {
        Ok(())
    }
}
