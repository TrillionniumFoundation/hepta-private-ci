"""Bounded finite-CTMC exponential, with no probability repair.

This is an optional implementation of exp(t A), not a new dynamics model.
For a row subgenerator A, U=I+A/lambda is substochastic. A truncated
Poisson polynomial in U has nonnegative coefficients and loses at most its
Poisson tail in row l1 norm. Scaling/squaring amplifies that truncation bound
by at most the number of subintervals. Bounds exclude floating point error.
The dense fallback has the upstream matrix_exp numerical contract; it has
no Poisson truncation, not a proved roundoff bound.
"""

import math

import torch


MAX_STATES = 128
MAX_BATCH = 4096
MAX_RATE_TIME = 2048.0
MAX_SQUARINGS = 12
MAX_DEGREE = 24
CHUNK_MEAN = 0.5


def _tail(mean, degree):
    if mean == 0:
        return 0.0, 0.0
    ratio = mean / (degree + 2)
    if ratio >= 1:
        return math.inf, math.inf
    first = math.exp(-mean + (degree + 1) * math.log(mean)
                     - math.lgamma(degree + 2))
    tail = first / (1 - ratio)
    moment = first * ((degree + 1) / (1 - ratio)
                      + ratio / (1 - ratio) ** 2)
    return tail, moment


def _inputs(generator, duration, event_rate):
    if (not torch.is_tensor(generator) or generator.ndim < 2
            or generator.shape[-1] != generator.shape[-2]):
        raise ValueError("Expected square generator [...,N,N]")
    if generator.dtype not in (torch.float32, torch.float64):
        raise ValueError("Only float32 and float64 are supported")
    n = generator.shape[-1]
    if n < 1 or n > MAX_STATES or generator.numel() // (n * n) > MAX_BATCH:
        raise ValueError("Finite operator state/batch cap exceeded")
    duration = torch.broadcast_to(torch.as_tensor(
        duration, dtype=generator.dtype, device=generator.device), generator.shape[:-2])
    if (not bool(torch.isfinite(generator).all()) or not bool(torch.isfinite(duration).all())
            or bool((duration < 0).any())):
        raise ValueError("Finite generator and nonnegative finite duration required")
    diagonal = generator.diagonal(dim1=-2, dim2=-1)
    off = generator - torch.diag_embed(diagonal)
    # Construction roundoff may affect row sums, but negative jumps are refused.
    if bool((off < 0).any()) or bool((diagonal > 0).any()):
        raise ValueError("Require nonnegative off-diagonal jumps and nonpositive diagonal")
    rows = generator.sum(-1)
    row_slack = 64 * torch.finfo(generator.dtype).eps * generator.abs().sum(-1).clamp_min(1)
    if bool((rows > row_slack).any()):
        raise ValueError("Require a row subgenerator")
    rate = (-diagonal).amax(-1).detach()
    if event_rate is not None:
        event_rate = torch.broadcast_to(torch.as_tensor(
            event_rate, dtype=generator.dtype, device=generator.device), generator.shape[:-1])
        if not bool(torch.isfinite(event_rate).all()) or bool((event_rate < 0).any()):
            raise ValueError("Finite nonnegative event intensity required")
        # Counting includes firing self-marks, which need not appear in -diag(Q).
        rate = torch.maximum(rate, event_rate.detach().amax(-1))
    # A=0 uses lambda=1 to keep the derivative at a zero generator meaningful.
    rate = torch.where(rate > 0, rate, torch.ones_like(rate))
    if bool((generator.abs().sum(-1).amax(-1) * duration > MAX_RATE_TIME).any()):
        raise ValueError("Finite operator rate-duration cap exceeded")
    if event_rate is not None and bool((event_rate.amax(-1) * duration > MAX_RATE_TIME).any()):
        raise ValueError("Count rate-duration cap exceeded")
    return duration, rate, event_rate


def _polynomial(jump, weights):
    """Positive-coefficient Paterson-Stockmeyer evaluation, preserving autograd."""
    degree = len(weights) - 1
    width = max(1, math.isqrt(degree + 1))
    eye = torch.eye(jump.shape[-1], dtype=jump.dtype, device=jump.device).expand_as(jump)
    powers = [eye, jump]
    for _ in range(2, width + 1):
        powers.append(powers[-1] @ jump)
    blocks = []
    for start in range(0, degree + 1, width):
        block = torch.zeros_like(jump)
        for k in range(start, min(start + width, degree + 1)):
            block = block + weights[k][..., None, None] * powers[k - start]
        blocks.append(block)
    result = blocks[-1]
    for block in reversed(blocks[:-1]):
        result = powers[width] @ result + block
    return result


def propagate(generator, duration, *, event_rate=None, tolerance=None,
              max_squarings=MAX_SQUARINGS, max_degree=MAX_DEGREE):
    """Return transition, optional repeated count, and explicit approximation data.

    The scalar ``truncation_bound`` bounds the largest row l1 transition error
    in exact arithmetic. ``count_truncation_bound`` bounds absolute error per
    initial state in E[N_t]. A count may exceed one. No row normalization is
    applied. Input-dependent detached planning does not alter the limiting
    matrix exponential; gradient accuracy is separately tested.
    """
    duration, rate, event_rate = _inputs(generator, duration, event_rate)
    tolerance = (1e-12 if generator.dtype == torch.float64 else 1e-6) if tolerance is None else tolerance
    if not math.isfinite(tolerance) or not 0 < tolerance < .01:
        raise ValueError("Require a finite tolerance in (0,0.01)")
    if not isinstance(max_squarings, int) or not 0 <= max_squarings <= MAX_SQUARINGS:
        raise ValueError("Invalid squaring work cap")
    if not isinstance(max_degree, int) or not 1 <= max_degree <= MAX_DEGREE:
        raise ValueError("Invalid polynomial work cap")
    mean = rate * duration
    squarings = torch.ceil(torch.log2((mean.detach() / CHUNK_MEAN).clamp_min(1))).long()
    maximum_squarings = int(squarings.max())
    chunks = torch.pow(2.0, squarings).to(generator.dtype)
    small_mean = mean / chunks
    # Account even for small positive row-sum construction roundoff. If
    # alpha=max(0,max A1), ||I+A/lambda||_infinity <= 1+alpha/lambda;
    # the tail uses this enlarged Poisson mean and exp(alpha*t) growth.
    growth = generator.sum(-1).amax(-1).clamp_min(0).detach()
    worst_mean = float((small_mean.detach() + growth * duration.detach() / chunks).max())
    growth_factor = math.exp(float((growth * duration.detach()).max()))
    m = float(chunks.max())
    firing_mean = 0.0 if event_rate is None else float((event_rate.amax(-1) * duration).detach().max())
    degree = 1
    while degree <= max_degree:
        tail, moment = _tail(worst_mean, degree)
        transition_bound = growth_factor * m * tail
        # Over m chunks, error of repeated-count composition has both a local
        # count tail and the accumulated error of preceding transition factors.
        # The augmented constant coordinate is also truncated. A union bound
        # over omitted Poisson arrivals therefore counts both earlier and
        # later chunks, giving (m-1), not (m-1)/2, in the second term.
        count_bound = growth_factor * (m * moment + (m - 1) * firing_mean * tail)
        if max(transition_bound, count_bound if event_rate is not None else 0) <= tolerance:
            break
        degree += 1
    fallback = maximum_squarings > max_squarings or degree > max_degree
    diagnostics = dict(method="dense_fallback" if fallback else "poisson_scaling_squaring",
                       degree=None if fallback else degree,
                       maximum_squarings=maximum_squarings,
                       truncation_bound=0.0 if fallback else transition_bound,
                       count_truncation_bound=(None if event_rate is None else
                                               0.0 if fallback else count_bound),
                       requested_truncation_tolerance=tolerance,
                       bound_excludes_roundoff=True, row_normalized=False,
                       row_growth_factor=growth_factor,
                       finite_ctmc_only=True)
    n = generator.shape[-1]
    if fallback:
        if event_rate is None:
            evolved = torch.matrix_exp(generator * duration[..., None, None])
        else:
            top = torch.cat((generator, event_rate[..., None]), -1)
            augmented = torch.nn.functional.pad(top, (0, 0, 0, 1))
            evolved = torch.matrix_exp(augmented * duration[..., None, None])
    else:
        eye = torch.eye(n, dtype=generator.dtype, device=generator.device)
        jump = eye + generator / rate[..., None, None]
        if event_rate is not None:
            top = torch.cat((jump, (event_rate / rate[..., None])[..., None]), -1)
            jump = torch.nn.functional.pad(top, (0, 0, 0, 1))
            bottom = torch.nn.functional.one_hot(
                torch.tensor(n, device=generator.device), n + 1).to(generator.dtype)
            jump = jump + bottom[:, None] * bottom
        weights = [torch.exp(-small_mean)]
        for k in range(1, degree + 1):
            weights.append(weights[-1] * small_mean / k)
        evolved = _polynomial(jump, weights)
        # The augmented bottom-right is exactly one in the exact exponential.
        # Keep the truncated value so this remains the same positive polynomial.
        for level in range(maximum_squarings):
            squared = evolved @ evolved
            evolved = torch.where((squarings > level)[..., None, None], squared, evolved)
    result = dict(transition=evolved[..., :n, :n], diagnostics=diagnostics)
    if event_rate is not None:
        result["event_vector"] = evolved[..., :n, -1]
    return result


def transition(generator, duration, **kwargs):
    """Tensor-only adapter for a model's optional propagation backend."""
    return propagate(generator, duration, **kwargs)["transition"]
