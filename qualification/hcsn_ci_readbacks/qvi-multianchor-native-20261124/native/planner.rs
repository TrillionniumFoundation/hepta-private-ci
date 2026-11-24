#[derive(Debug, Clone)]
pub struct Problem {
    pub matrix: Vec<Vec<f64>>,
    pub target: Vec<f64>,
    pub budget: f64,
    pub tolerance: f64,
}

#[derive(Debug)]
pub struct Plan {
    pub delta: Vec<f64>,
    pub residuals: Vec<f64>,
    pub squared_error: f64,
    pub residual_upper: f64,
    pub infeasible_lower: f64,
    pub witness: Vec<f64>,
    pub rank: usize,
    pub status: &'static str,
}

fn down(value: f64) -> f64 {
    if value == 0.0 {
        return -f64::from_bits(1);
    }
    f64::from_bits(if value > 0.0 {
        value.to_bits() - 1
    } else {
        value.to_bits() + 1
    })
}

fn up(value: f64) -> f64 {
    -down(-value)
}

#[derive(Clone, Copy)]
struct Interval(f64, f64);

impl Interval {
    fn add(self, other: Self) -> Self {
        Self(down(self.0 + other.0), up(self.1 + other.1))
    }
    fn mul(self, other: Self) -> Self {
        let values = [
            self.0 * other.0,
            self.0 * other.1,
            self.1 * other.0,
            self.1 * other.1,
        ];
        Self(
            down(values.iter().copied().fold(f64::INFINITY, f64::min)),
            up(values.iter().copied().fold(f64::NEG_INFINITY, f64::max)),
        )
    }
    fn abs_bounds(self) -> Self {
        Self(
            if self.0 <= 0.0 && self.1 >= 0.0 {
                0.0
            } else {
                self.0.abs().min(self.1.abs())
            },
            self.0.abs().max(self.1.abs()),
        )
    }
}

fn dot(a: &[f64], b: &[f64]) -> f64 {
    a.iter().zip(b).map(|(x, y)| x * y).sum()
}

fn interval_dot(a: &[f64], b: &[f64]) -> Interval {
    a.iter().zip(b).fold(Interval(0.0, 0.0), |acc, (&x, &y)| {
        acc.add(Interval(x, x).mul(Interval(y, y)))
    })
}

// One-sided Jacobi keeps tiny singular directions out of normal equations.
fn least_squares(matrix: &[Vec<f64>], target: &[f64]) -> (Vec<f64>, usize) {
    let n = matrix.len();
    let m = matrix[0].len();
    if m == 0 {
        return (vec![], 0);
    }
    let mut cols: Vec<Vec<f64>> = (0..m)
        .map(|j| matrix.iter().map(|row| row[j]).collect())
        .collect();
    let mut right = vec![vec![0.0; m]; m];
    for (i, row) in right.iter_mut().enumerate() {
        row[i] = 1.0;
    }
    for _ in 0..64 {
        let mut changed = false;
        for p in 0..m {
            for q in p + 1..m {
                let aa = dot(&cols[p], &cols[p]);
                let bb = dot(&cols[q], &cols[q]);
                let ab = dot(&cols[p], &cols[q]);
                if ab.abs() <= 4.0 * f64::EPSILON * (aa * bb).sqrt() {
                    continue;
                }
                let zeta = (bb - aa) / (2.0 * ab);
                let t = zeta.signum() / (zeta.abs() + zeta.hypot(1.0));
                let c = 1.0 / (1.0 + t * t).sqrt();
                let s = c * t;
                for i in 0..n {
                    let old = cols[p][i];
                    cols[p][i] = c * old - s * cols[q][i];
                    cols[q][i] = s * old + c * cols[q][i];
                }
                for row in &mut right {
                    let old = row[p];
                    row[p] = c * old - s * row[q];
                    row[q] = s * old + c * row[q];
                }
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    let squares: Vec<f64> = cols.iter().map(|x| dot(x, x)).collect();
    let largest = squares.iter().copied().fold(0.0, f64::max);
    let mut solution = vec![0.0; m];
    let mut rank = 0;
    for j in 0..m {
        if squares[j] <= largest * 1e-24 || squares[j] == 0.0 {
            continue;
        }
        rank += 1;
        let coefficient = dot(&cols[j], target) / squares[j];
        for i in 0..m {
            solution[i] += right[i][j] * coefficient;
        }
    }
    (solution, rank)
}

pub fn solve(problem: &Problem) -> Result<Plan, String> {
    let n = problem.matrix.len();
    let m = problem.matrix.first().map_or(0, Vec::len);
    if !(1..=64).contains(&n)
        || !(1..=3).contains(&m)
        || problem.target.len() != n
        || !problem.budget.is_finite()
        || !(0.0..=0.1).contains(&problem.budget)
        || !problem.tolerance.is_finite()
        || !(0.0..=1e-7).contains(&problem.tolerance)
        || problem.matrix.iter().any(|r| r.len() != m)
        || problem
            .matrix
            .iter()
            .flatten()
            .chain(&problem.target)
            .any(|x| !x.is_finite() || x.abs() > 1e6)
    {
        return Err("invalid finite bounded linear edit problem".into());
    }
    let mut best: Option<(f64, f64, Vec<f64>, Vec<f64>)> = None;
    for mut pattern in 0..3usize.pow(m as u32) {
        let mut candidate = vec![0.0; m];
        let mut free = Vec::new();
        for (j, value) in candidate.iter_mut().enumerate() {
            match pattern % 3 {
                0 => free.push(j),
                1 => *value = -problem.budget,
                2 => *value = problem.budget,
                _ => unreachable!(),
            }
            pattern /= 3;
        }
        let target: Vec<f64> = problem
            .matrix
            .iter()
            .zip(&problem.target)
            .map(|(row, &r)| r - dot(row, &candidate))
            .collect();
        let design: Vec<Vec<f64>> = problem
            .matrix
            .iter()
            .map(|row| free.iter().map(|&j| row[j]).collect())
            .collect();
        let (fitted, _) = least_squares(&design, &target);
        if fitted
            .iter()
            .any(|v| !v.is_finite() || v.abs() > problem.budget + 1e-12)
        {
            continue;
        }
        for (&j, &value) in free.iter().zip(&fitted) {
            candidate[j] = value.clamp(-problem.budget, problem.budget);
        }
        let errors: Vec<f64> = problem
            .matrix
            .iter()
            .zip(&problem.target)
            .map(|(row, &r)| dot(row, &candidate) - r)
            .collect();
        let score = dot(&errors, &errors);
        let norm = dot(&candidate, &candidate);
        if best
            .as_ref()
            .is_none_or(|(s, q, _, _)| score < *s || (score == *s && norm < *q))
        {
            best = Some((score, norm, candidate, errors));
        }
    }
    let Some((squared_error, _, delta, residuals)) = best else {
        return Err("no finite box candidate".into());
    };
    let residual_upper = problem
        .matrix
        .iter()
        .zip(&problem.target)
        .map(|(row, &r)| {
            interval_dot(row, &delta)
                .add(Interval(-r, -r))
                .abs_bounds()
                .1
        })
        .fold(0.0, f64::max);
    let scale: f64 = residuals.iter().map(|x| x.abs()).sum();
    let witness: Vec<f64> = residuals
        .iter()
        .map(|&r| if scale > 0.0 { r / scale } else { 0.0 })
        .collect();
    let projection = (0..m).fold(Interval(0.0, 0.0), |acc, j| {
        let column: Vec<f64> = problem.matrix.iter().map(|r| r[j]).collect();
        let abs = interval_dot(&column, &witness).abs_bounds();
        acc.add(Interval(abs.1, abs.1))
    });
    let numerator = interval_dot(&witness, &problem.target).abs_bounds();
    let penalty = projection.mul(Interval(problem.budget, problem.budget));
    // Account for the rounded witness normalization; its true L1 need not be 1.
    let ones = vec![1.0; n];
    let abs_witness: Vec<f64> = witness.iter().map(|x| x.abs()).collect();
    let witness_norm = interval_dot(&abs_witness, &ones);
    let infeasible_lower = if witness_norm.1 > 0.0 {
        down(down(numerator.0 - penalty.1) / witness_norm.1).max(0.0)
    } else {
        0.0
    };
    let status = if residual_upper <= problem.tolerance {
        "FitFeasibleNeedsFullValidation"
    } else if infeasible_lower > problem.tolerance {
        "NoEditInfeasible"
    } else {
        "NoEditNumericallyUnresolved"
    };
    let (_, rank) = least_squares(&problem.matrix, &problem.target);
    Ok(Plan {
        delta,
        residuals,
        squared_error,
        residual_upper,
        infeasible_lower,
        witness,
        rank,
        status,
    })
}

pub fn boundary_residual(theta: &[f64; 8], boundary: f64) -> f64 {
    let [mu, sigma, rho, reset, delay, gain, maintenance, cost] = *theta;
    let kappa = 2.0 * rho / (mu.hypot((2.0 * rho).sqrt() * sigma) - mu);
    let slope = gain / rho;
    let intercept = gain * mu / (rho * rho) - maintenance / rho;
    let amplitude = slope / kappa;
    slope * boundary + intercept + amplitude + cost
        - (-rho * delay).exp()
            * (slope * reset + intercept + amplitude * (-kappa * (reset - boundary)).exp())
}

pub fn cost_edit(theta: &[f64; 8], target: f64, budget: f64) -> Result<(f64, f64), String> {
    if theta.iter().any(|x| !x.is_finite())
        || !target.is_finite()
        || theta[1] <= 0.0
        || theta[2] <= 0.0
        || theta[4] <= 0.0
        || theta[4] > 2.0
        || theta[5] <= 0.0
        || theta[6] < 0.0
        || theta[7] <= 0.0
        || !(theta[3] - 8.0 < target && target < theta[3] - 1e-4)
        || !budget.is_finite()
        || !(0.0..=0.1).contains(&budget)
    {
        return Err("invalid QVI interior or edit budget".into());
    }
    let cost = theta[7] - boundary_residual(theta, target);
    if !cost.is_finite() || cost <= 0.0 || (cost - theta[7]).abs() > budget {
        return Err("target cost outside original positive bounded edit domain".into());
    }
    let mut edited = *theta;
    edited[7] = cost;
    let mut low = edited[3] - 8.0;
    let mut high = edited[3] - 1e-4;
    if !(boundary_residual(&edited, low) < 0.0 && boundary_residual(&edited, high) > 0.0) {
        return Err("target lost the interior unique root".into());
    }
    for _ in 0..64 {
        let mid = (low + high) / 2.0;
        if boundary_residual(&edited, mid) < 0.0 {
            low = mid;
        } else {
            high = mid;
        }
    }
    Ok((cost, ((low + high) / 2.0 - target).abs()))
}

#[cfg(test)]
#[path = "planner_tests.rs"]
mod tests;
