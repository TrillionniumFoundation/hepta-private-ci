//! Ordinary belief-grid Bellman backups over a public two-job schedule.
use crate::task::Public;

#[derive(Clone, Debug)]
pub struct Grid {
    public: Public,
    confusion: [[f64; 2]; 2],
    nodes: usize,
    values: Vec<f64>,
}

impl Grid {
    pub fn new(public: &Public, confusion: [[f64; 2]; 2], nodes: usize) -> Result<Self, String> {
        if !(3..=1025).contains(&nodes) || nodes % 2 != 1 {
            return Err("odd belief grid envelope 3..1025".into());
        }
        let size = 3 * (public.deadline + 2) * (public.budget + 1) * nodes;
        let mut grid = Self {
            public: public.clone(),
            confusion,
            nodes,
            values: vec![0.; size],
        };
        for job in (0..2).rev() {
            for tick in (0..public.deadline).rev() {
                for budget in 0..=public.budget {
                    for point in 0..nodes {
                        let p = point as f64 / (nodes - 1) as f64;
                        let value = grid.q(job, tick, budget, p).into_iter().fold(0., f64::max);
                        let index = grid.index(job, tick, budget, point);
                        grid.values[index] = value;
                    }
                }
            }
        }
        Ok(grid)
    }

    fn index(&self, job: usize, tick: usize, budget: usize, point: usize) -> usize {
        ((job * (self.public.deadline + 2) + tick) * (self.public.budget + 1) + budget) * self.nodes
            + point
    }

    fn value(&self, job: usize, tick: usize, budget: usize, posterior: f64) -> f64 {
        if job >= 2 || tick >= self.public.deadline {
            return 0.;
        }
        let coordinate = posterior.clamp(0., 1.) * (self.nodes - 1) as f64;
        let left = (coordinate.floor() as usize).min(self.nodes - 2);
        let fraction = coordinate - left as f64;
        self.values[self.index(job, tick, budget, left)] * (1. - fraction)
            + self.values[self.index(job, tick, budget, left + 1)] * fraction
    }

    pub fn q(&self, job: usize, tick: usize, budget: usize, posterior: f64) -> [f64; 4] {
        let mut q = [0., f64::NEG_INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY];
        let m = &self.public;
        if job >= 2 || tick >= m.deadline {
            return q;
        }
        let cost = m.latency_price * m.elapsed(tick, 1);
        if tick + 1 < m.deadline {
            q[1] = self.value(job, tick + 1, budget, posterior) - cost;
            if budget > 0 {
                let reliability = m.reliability[job][tick];
                q[2] = -m.multiplier * m.price[job][tick] - cost;
                for observation in 0..2 {
                    let law0 = reliability * self.confusion[0][observation]
                        + (1. - reliability) * self.confusion[1][observation];
                    let law1 = reliability * self.confusion[1][observation]
                        + (1. - reliability) * self.confusion[0][observation];
                    let probability = (1. - posterior) * law0 + posterior * law1;
                    let belief = posterior * law1 / probability;
                    q[2] += probability * self.value(job, tick + 1, budget - 1, belief);
                }
            }
        }
        q[3] = (2. * posterior - 1.).abs() + self.value(job + 1, tick + 2, budget, 0.5)
            - m.latency_price * m.elapsed(tick, 2);
        q
    }

    pub fn resident_bytes(&self) -> usize {
        self.values.len() * 8
    }
}
