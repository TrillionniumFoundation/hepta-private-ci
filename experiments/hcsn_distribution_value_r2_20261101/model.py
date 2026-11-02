"""Shared empirical identification, two full-law kernels and explicit projections."""
import numpy as np
from scipy.linalg import expm
from scipy.optimize import minimize


def fit(arrays):
    features = np.column_stack((np.ones(len(arrays['contexts'])), arrays['contexts']))
    coefficients, records = [], []
    for channel in range(4):
        count, exposure = arrays['counts'][:, channel], arrays['exposure'][:, channel]
        def objective(beta):
            linear = features @ beta
            expected = exposure * np.exp(linear)
            return float((expected - count * linear).sum() + 1e-6 * (beta * beta).sum()), features.T @ (expected - count) + 2e-6 * beta
        result = minimize(objective, [np.log(count.sum() / exposure.sum()), 0., 0.], jac=True, method='L-BFGS-B', bounds=[(-4., 2.), (-2., 2.), (-2., 2.)], options=dict(ftol=1e-13, gtol=1e-8, maxiter=1000))
        if not result.success or not np.isfinite(result.x).all():
            raise ArithmeticError(str(result.message))
        coefficients.append(result.x.tolist())
        records.append(dict(success=bool(result.success), objective=float(result.fun), gradient_norm=float(np.linalg.norm(result.jac))))
    joint = np.zeros((8, 8))
    np.add.at(joint, tuple(arrays['prior_samples'].T), 1)
    joint /= joint.sum(1, keepdims=True)
    factorized = np.asarray([(row.reshape(4, 2).sum(1)[:, None] * row.reshape(4, 2).sum(0)).ravel() for row in joint])
    read = np.asarray([np.mean(arrays['read_target'][arrays['read_state'] == state] == arrays['read_observed'][arrays['read_state'] == state]) for state in range(4)])
    return dict(coefficients=coefficients, full_priors=joint.tolist(), factorized_priors=factorized.tolist(), read_accuracy=read.tolist(), identification=records,
                supervision='Identical fully observed physical trajectory counts/exposures, balanced cue-state-bit samples, and state-labelled noisy READ calibration for every main arm')


def generator(candidate, context):
    physical_rates = np.exp(np.asarray(candidate['coefficients']) @ np.r_[1., context])
    if not np.isfinite(physical_rates).all() or (physical_rates > 6).any():
        raise ArithmeticError('Fitted heldout rate outside prospectively bounded profile')
    up, down, outage, recover = physical_rates
    q = np.zeros((4, 4))
    q[0, 1] = q[1, 2] = up
    q[1, 0] = q[2, 1] = down
    q[2, 3], q[3, 0] = outage, recover
    q -= np.diag(q.sum(1))
    mark = np.zeros_like(q); mark[2, 3] = outage
    return q, mark


def uniformized(q, mark, duration):
    """Generic empirical Markov reference: full/killed law and repeated counts.

    With the registered rate cap and duration<=.9, 96 terms leave a Poisson
    tail below 1e-50. This is a full distribution baseline, not a mean baseline.
    """
    rate = float(np.max(-np.diag(q)))
    p, p0 = np.eye(4) + q / rate, np.eye(4) + (q - mark) / rate
    power = killed_power = np.eye(4)
    accumulated = np.zeros(4)
    reward = mark.sum(1) / rate
    weight = np.exp(-rate * duration)
    transition, killed, count = weight * power, weight * killed_power, weight * accumulated
    for n in range(1, 97):
        accumulated = accumulated + power @ reward
        power, killed_power = power @ p, killed_power @ p0
        weight *= rate * duration / n
        transition += weight * power; killed += weight * killed_power; count += weight * accumulated
    return transition, killed, count


def kernels(candidate, context, engine, duration):
    q, mark = generator(candidate, context)
    if engine == 'ordinary':
        p, killed, count = uniformized(q, mark, duration)
    elif engine == 'analytic':
        augmented = np.zeros((5, 5)); augmented[:4, :4] = q; augmented[:4, 4] = mark.sum(1)
        evolved = expm(augmented * duration)
        p, killed, count = evolved[:4, :4], expm((q - mark) * duration), evolved[:4, 4]
    else:
        raise ValueError(engine)
    hit = p - killed
    if min(p.min(), killed.min(), hit.min(), count.min()) < -1e-11:
        raise ArithmeticError('Negative transition/count outside FP64 tolerance')
    return [np.kron(np.maximum(killed, 0), np.eye(2)), np.kron(np.maximum(hit, 0), np.eye(2))], np.repeat(np.maximum(count, 0), 2)


def project(belief, kind):
    joint = np.asarray(belief).reshape(4, 2)
    if kind == 'full':
        return joint.ravel()
    if kind == 'factorized':
        return (joint.sum(1)[:, None] * joint.sum(0)).ravel()
    if kind == 'mean':
        result = np.zeros_like(joint); result[3] = joint[3]
        mass = joint[:3].sum(0)
        mean = np.divide((np.arange(3)[:, None] * joint[:3]).sum(0), mass, out=np.zeros(2), where=mass > 0)
        lower = np.minimum(np.floor(mean).astype(int), 1)
        for bit in range(2):
            fraction = mean[bit] - lower[bit]
            result[lower[bit], bit] = mass[bit] * (1 - fraction)
            result[lower[bit] + 1, bit] = mass[bit] * fraction
        return result.ravel()
    raise ValueError(kind)
