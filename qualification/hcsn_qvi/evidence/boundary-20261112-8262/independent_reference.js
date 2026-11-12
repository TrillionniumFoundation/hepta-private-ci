/* Independent FP64 sanity reference for the fixed bounded-diffusion fixture.
 *
 * Executed in functions.exec V8, separately from the candidate Python code.
 * This does not execute PyTorch, Python tests, CI, or high-precision arithmetic.
 * Both the continuum model and the finite Markov approximation are bounded
 * reflecting models with g(x)=x and a zero-reward deterministic reset delay.
 * Neither is the HCSN half-line neural process or a certified interval result.
 *
 * Reproduction in a CommonJS-capable Node runtime:
 *   node independent_reference.js
 * Node execution itself was not performed in the retained V8 run.
 */

function independentReference() {
  const p = {mu: -0.2, sigma: 0.35, discount: 0.15, upper: 2.0,
             reset: 1.37, delay: 0.2, cost: 0.6, initial: 0.8};
  const eta = Math.exp(-p.discount * p.delay);
  const discriminant = Math.sqrt(p.mu * p.mu + 2 * p.discount * p.sigma * p.sigma);
  const rp = (-p.mu + discriminant) / (p.sigma * p.sigma);
  const rm = (-p.mu - discriminant) / (p.sigma * p.sigma);

  function candidate(boundary) {
    const eb = Math.exp(rp * (boundary - p.upper));
    const hl = Math.exp(rm * (p.upper - boundary));
    const determinant = rp * rm - rm * hl * rp * eb;
    const a = (-rm / p.discount + rm * hl / p.discount) / determinant;
    const c = (-rp / p.discount + rp * eb / p.discount) / determinant;
    const continuation = x => x / p.discount + p.mu / p.discount ** 2
      + a * Math.exp(rp * (x - p.upper))
      + c * Math.exp(rm * (x - boundary));
    const slope = x => 1 / p.discount + a * rp * Math.exp(rp * (x - p.upper))
      + c * rm * Math.exp(rm * (x - boundary));
    const curvature = x => a * rp * rp * Math.exp(rp * (x - p.upper))
      + c * rm * rm * Math.exp(rm * (x - boundary));
    return {
      residual: continuation(boundary) + p.cost - eta * continuation(p.reset),
      value: x => continuation(Math.max(x, boundary)),
      continuation, slope, curvature,
    };
  }

  const endpointResiduals = [candidate(0).residual, candidate(p.reset).residual];
  if (!(endpointResiduals[0] < 0 && endpointResiduals[1] > 0)) {
    throw new Error("This reference only handles the declared bracketed fixture");
  }
  let lower = 0, upper = p.reset;
  for (let i = 0; i < 90; i++) {
    const middle = (lower + upper) / 2;
    if (candidate(middle).residual < 0) lower = middle;
    else upper = middle;
  }
  const boundary = (lower + upper) / 2;
  const continuous = candidate(boundary);
  let odeResidual = 0;
  for (let i = 0; i <= 256; i++) {
    const x = boundary + (p.upper - boundary) * i / 256;
    odeResidual = Math.max(odeResidual, Math.abs(
      0.5 * p.sigma ** 2 * continuous.curvature(x)
      + p.mu * continuous.slope(x) - p.discount * continuous.continuation(x) + x));
  }

  function linearSolve(original, rhs) {
    const n = rhs.length, a = original.map(row => row.slice()), r = rhs.slice();
    for (let k = 0; k < n; k++) {
      let pivot = k;
      for (let i = k + 1; i < n; i++) {
        if (Math.abs(a[i][k]) > Math.abs(a[pivot][k])) pivot = i;
      }
      [a[k], a[pivot]] = [a[pivot], a[k]];
      [r[k], r[pivot]] = [r[pivot], r[k]];
      if (!Number.isFinite(a[k][k]) || a[k][k] === 0) {
        throw new Error("Unresolved finite-model linear system");
      }
      for (let i = k + 1; i < n; i++) {
        const factor = a[i][k] / a[k][k];
        for (let j = k + 1; j < n; j++) a[i][j] -= factor * a[k][j];
        r[i] -= factor * r[k];
        a[i][k] = 0;
      }
    }
    const x = Array(n).fill(0);
    for (let i = n - 1; i >= 0; i--) {
      let total = r[i];
      for (let j = i + 1; j < n; j++) total -= a[i][j] * x[j];
      x[i] = total / a[i][i];
    }
    if (!x.every(Number.isFinite)) throw new Error("Nonfinite policy value");
    return x;
  }

  function pointWeights(point, spacing, n) {
    const weights = Array(n).fill(0);
    const left = Math.min(Math.floor(point / spacing), n - 2);
    const fraction = point / spacing - left;
    weights[left] = 1 - fraction;
    weights[left + 1] = fraction;
    return weights;
  }

  const dot = (a, b) => a.reduce((sum, value, i) => sum + value * b[i], 0);
  const finite = [];
  for (const n of [21, 41, 81, 121]) {
    const spacing = p.upper / (n - 1);
    const upward = p.sigma ** 2 / (2 * spacing * spacing)
      + Math.max(p.mu, 0) / spacing;
    const downward = p.sigma ** 2 / (2 * spacing * spacing)
      + Math.max(-p.mu, 0) / spacing;
    const rate = upward + downward;
    const wait = Array.from({length: n}, () => Array(n).fill(0));
    const reward = Array(n).fill(0);
    const resetWeights = pointWeights(p.reset, spacing, n);
    for (let i = 0; i < n; i++) {
      if (i < n - 1) wait[i][i + 1] = upward / (p.discount + rate);
      if (i > 0) wait[i][i - 1] = downward / (p.discount + rate);
      wait[i][i] = (rate - (i < n - 1 ? upward : 0) - (i > 0 ? downward : 0))
        / (p.discount + rate);
      reward[i] = i * spacing / (p.discount + rate);
    }
    let policy = Array(n).fill(false), value = null, iterations = 0;
    let target = null, waitValues = null, converged = false;
    for (let iteration = 0; iteration < 256; iteration++) {
      const system = wait.map((row, i) => row.map((entry, j) =>
        (i === j ? 1 : 0) - (policy[i] ? eta * resetWeights[j] : entry)));
      value = linearSolve(system, reward.map((entry, i) => policy[i] ? -p.cost : entry));
      target = -p.cost + eta * dot(resetWeights, value);
      waitValues = wait.map((row, i) => reward[i] + dot(row, value));
      const next = waitValues.map(entry => target > entry + 1e-13);
      iterations = iteration + 1;
      if (next.every((entry, i) => entry === policy[i])) {
        converged = true;
        break;
      }
      policy = next;
    }
    if (!converged) throw new Error("Finite policy iteration exceeded its fixed budget");
    const initial = dot(pointWeights(p.initial, spacing, n), value);
    const last = policy.lastIndexOf(true);
    finite.push({
      nodes: n, spacing, policy_evaluations: iterations,
      initial_value: initial,
      initial_value_absolute_error: Math.abs(initial - continuous.value(p.initial)),
      maximum_grid_value_error: Math.max(...value.map((entry, i) =>
        Math.abs(entry - continuous.value(i * spacing)))),
      bellman_residual: Math.max(...value.map((entry, i) =>
        Math.abs(Math.max(waitValues[i], target) - entry))),
      discrete_policy_boundary_bracket: last >= 0 && last < n - 1
        ? [last * spacing, (last + 1) * spacing] : null,
    });
  }
  return {
    schema: "hcsn-independent-js-boundary-reference-v1",
    problem: p,
    arithmetic: "JavaScript Number binary64; no arbitrary precision",
    continuum: {
      boundary, initial_value: continuous.value(p.initial),
      characteristic_roots: [rp, rm],
      endpoint_matching_residuals: endpointResiduals,
      value_matching_residual: continuous.residual,
      smooth_pasting_residual: continuous.slope(boundary),
      upper_reflection_residual: continuous.slope(p.upper),
      maximum_sampled_continuation_ode_residual: odeResidual,
      maximum_intervention_generator_residual:
        boundary - p.discount * continuous.value(boundary),
    },
    finite_policy_iteration: finite,
    interpretation: {
      finite_bellman_residual_is_not_continuum_error: true,
      discrete_policy_brackets_are_not_continuum_certificates: true,
      refinement_is_empirical_for_this_single_fixture: true,
      tested_candidate_python: false, tested_ci: false,
      trained_models: 0, independent_value_iteration_performed: false,
      high_precision_performed: false, gradient_validation_performed: false,
      general_continuum_certificate: false, hcsn_half_line_qualification: false,
      neural_task_benefit_established: false,
    },
  };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {independentReference};
  if (typeof require !== "undefined" && require.main === module) {
    process.stdout.write(JSON.stringify(independentReference(), null, 2) + "\n");
  }
}
