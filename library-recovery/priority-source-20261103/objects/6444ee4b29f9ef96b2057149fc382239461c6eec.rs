//! An optional std-only Rust CPU research reference for one toy vector update.
//!
//! NOT the full He-Xiong financial kernel, not production HCSN, not a GPU
//! implementation, not an authenticated checkpoint/recovery runtime.
//! The authoring sandbox has no rustc/cargo; this source is UNCOMPILED here.

#[derive(Clone, Debug)]
pub struct ToyCells {
    values: Vec<f64>,
    completed_steps: u64,
}

impl ToyCells {
    pub fn new(n: usize) -> Result<Self, &'static str> {
        match n {
            64 | 256 | 1024 | 4096 => Ok(Self {
                values: vec![0.0; n],
                completed_steps: 0,
            }),
            _ => Err("Unregistered Cell scale"),
        }
    }

    pub fn values(&self) -> &[f64] {
        &self.values
    }

    pub fn completed_steps(&self) -> u64 {
        self.completed_steps
    }

    pub fn step(&mut self) -> Result<(), &'static str> {
        if self.completed_steps == u64::MAX {
            return Err("Sequence counter would overflow");
        }
        let tick = self.completed_steps;
        let dt = 0.035 + (tick % 17) as f64 * 0.0004;
        let keep = (-dt).exp();
        for (i, h) in self.values.iter_mut().enumerate() {
            let logz = h.abs().ln_1p();
            let gamma = 0.65_f64;
            let continuation = logz.exp_m1() + (-gamma * logz).exp_m1() / gamma;
            let risk = (-gamma * logz).exp();
            let x = 3.0 * (*h - 0.1);
            let softplus = if x > 20.0 { x + (-x).exp().ln_1p() }
                           else { x.exp().ln_1p() };
            let margin = softplus / 3.0;
            let signal = (tick as f64 * 0.07 + i as f64 * 0.003).sin();
            let next = keep * *h
                + (1.0 - keep) * (signal + 0.4 * continuation
                                    - 0.2 * risk + 0.3 * margin).tanh();
            if !next.is_finite() {
                return Err("Nonfinite Cell state");
            }
            *h = next;
        }
        self.completed_steps += 1;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reject_unregistered_scale() {
        assert!(ToyCells::new(0).is_err());
        assert!(ToyCells::new(1023).is_err());
        assert!(ToyCells::new(4097).is_err());
    }

    #[test]
    fn deterministic_replay_at_each_scale() {
        for n in [64, 256, 1024, 4096] {
            let mut a = ToyCells::new(n).unwrap();
            let mut b = ToyCells::new(n).unwrap();
            for _ in 0..64 {
                a.step().unwrap();
                b.step().unwrap();
            }
            assert_eq!(a.completed_steps(), 64);
            assert_eq!(a.values(), b.values());
            assert!(a.values().iter().all(|v| v.is_finite()));
        }
    }

    #[test]
    fn Python_scalar_golden_first_step() {
        let mut a = ToyCells::new(64).unwrap();
        a.step().unwrap();
        // First output references generated independently by NumPy below;
        // tolerance allows platform libm differences.
        assert!((a.values()[0] - (-0.004937884030690982)).abs() < 2e-8);
    }
}
