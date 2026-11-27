"""Differentiable finite CTMC with exact deterministic-delay renewal expansion.

For k resets, the last block of exp(T_k * (t-k*delay)) is the k-fold
Duhamel convolution. The finite sum is exact for this finite CTMC: paths with
more than floor(t/delay) completed resets cannot contribute. Matrix-exponential
roundoff remains numerical error. No timestep, hit-density uniformization,
custom backward, detached Jacobian, or fixed-initial-law conversion is used.

This bounded CPU/FP64 research oracle retains the nonreturning upper boundary.
It does not qualify continuum migration, filtering, or a trained HCSN network.
"""

import math

import torch


FIELDS = ("active", "upper", "refractory", "events", "discounted_events",
          "discounted_active_time", "discounted_remaining_phase")
PARAMETERS = ("log_boundary", "mu", "sigma", "absolute_reset", "delay", "discount")


def cascade_flow(parameters, times, active, content, phase=(), *, endpoint=2.0):
    """Return all marked flow fields with native Torch gradients.

    `active` includes zero lower-boundary and nonreturning upper-boundary mass;
    `content` has the same nodes and arbitrary signed columns. Each phase tuple
    contains (remaining_start, remaining_end, probability_and_content_vector).
    Equal fixed endpoints denote an atom; different endpoints denote a uniform
    release law. Non-atomic endpoints may themselves be scalar Torch tensors.
    Atom times must be supplied once as the same object in both tuple positions.

    All six physical parameters, initial masses/content, phase values and phase
    supports remain in the graph. Relative grid coordinates stay fixed. To
    differentiate an absolute prior w.r.t. boundary, construct its nodal weights
    with Torch before calling. Observed query times are fixed, not learnable.
    Reset knots, zero rates and release fronts are explicitly nondifferentiable.
    """
    tensors = (parameters, active, content)
    if any(not isinstance(x, torch.Tensor) or x.device.type != "cpu"
           or x.dtype != torch.float64 or not torch.isfinite(x).all() for x in tensors):
        raise ValueError("finite CPU FP64 tensors required")
    if parameters.shape != (6,) or active.ndim != 1 or content.ndim != 2:
        raise ValueError("six physical parameters and node/content arrays required")
    intervals = len(active) - 1
    if (not 4 <= intervals <= 32 or content.shape[0] != len(active)
            or not 1 <= content.shape[1] <= 4 or (active < 0).any()
            or active[0] != 0 or (content[0] != 0).any()):
        raise ValueError("bounded node arrays, positive masses and zero lower atom required")
    if (type(endpoint) not in (int, float) or not math.isfinite(endpoint)
            or not 0 < endpoint <= 16 or not isinstance(phase, tuple) or len(phase) > 4):
        raise ValueError("finite endpoint and bounded phase tuple required")
    if (not isinstance(times, (tuple, list)) or not 1 <= len(times) <= 16
            or any(type(t) not in (int, float) or not math.isfinite(t) for t in times)
            or any(t < 0 or t > 8 for t in times)
            or any(b <= a for a, b in zip(times, times[1:]))):
        raise ValueError("strictly increasing fixed query times in [0,8] required")
    boundary, drift, sigma, absolute_reset, delay, discount = parameters.unbind()
    if (sigma <= 0 or absolute_reset <= 0 or not 0 < delay <= 2
            or not .001 <= discount <= 4):
        raise ValueError("positive sigma/reset/delay and qualified discount required")
    spacing, n, channels = endpoint / intervals, intervals - 1, content.shape[1] + 1
    reset_position = (torch.log(absolute_reset) - boundary) / spacing
    position = float(reset_position.detach())
    if not 1 < position < intervals - 1 or abs(position - round(position)) <= 1e-8:
        raise ValueError("strictly interior off-knot reset required")
    down = sigma.square() / (2 * spacing**2) - drift / (2 * spacing)
    up = sigma.square() / (2 * spacing**2) + drift / (2 * spacing)
    if not torch.isfinite(down) or not torch.isfinite(up) or down <= 0 or up <= 0:
        raise ValueError("strictly positive central CTMC rates required")
    highest = math.floor(times[-1] / float(delay.detach()))
    if (highest > 8 or (highest + 2) * n + 8 > 256
            or len(times) * (2 * len(phase) + 1) * 2 * (highest + 1) > 512):
        raise ValueError("dense research-oracle budget exceeded")

    def scalar(value):
        if isinstance(value, torch.Tensor):
            if value.shape != () or value.device.type != "cpu" or value.dtype != torch.float64:
                raise ValueError("phase endpoints must be scalar CPU FP64")
            return value
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("finite phase endpoint required")
        return parameters.new_tensor(value)

    packets = []
    for left, right, vector in phase:
        start, end = scalar(left), scalar(right)
        if (not torch.isfinite(start) or not torch.isfinite(end)
                or not 0 <= start <= end <= delay
                or not isinstance(vector, torch.Tensor) or vector.shape != (channels,)
                or vector.device.type != "cpu" or vector.dtype != torch.float64
                or not torch.isfinite(vector).all() or vector[0] < 0):
            raise ValueError("phase support/value shape differs")
        atom = bool(start == end)
        if atom and (start.requires_grad or end.requires_grad) and left is not right:
            raise ValueError("a learnable atom has one shared release time")
        packets.append((start, end, vector, atom))
    # Detached scalars choose the analytic smooth region; no accepted numerical
    # value or derivative is computed from those detached quantities.
    for time in times:
        if time == 0:
            if any(edge.requires_grad and edge == 0 for a, b, _, _ in packets for edge in (a, b)):
                raise ValueError("learnable phase support is on the initialization front")
            continue
        for k in range(highest + 2):
            shifts = ([k * delay] if k else [])
            shifts += [edge + k * delay for a, b, _, _ in packets for edge in (a, b)]
            if any(abs(time - float(shift.detach())) <= 1e-9 for shift in shifts):
                raise ValueError("query lies on a release/reset derivative front")

    eye = torch.eye(n, dtype=parameters.dtype)
    transient = -(down + up) * eye
    transient = transient + down * torch.diag(torch.ones(n-1, dtype=parameters.dtype), 1)
    transient = transient + up * torch.diag(torch.ones(n-1, dtype=parameters.dtype), -1)
    lower, upper = down * eye[0], up * eye[-1]
    left = math.floor(position)
    reset = ((left + 1 - reset_position) * eye[left-1]
             + (reset_position - left) * eye[left])
    renewal = reset[:, None] * lower[None, :]
    initial = torch.cat((active[1:-1, None], content[1:-1]), dim=1)
    initial_upper = torch.cat((active[-1:], content[-1]))
    matrices = []
    for k in range(highest + 1):
        chain, xsize, ysize = (k + 1) * n, (k + 1) * n + 2, n + 2
        matrix = parameters.new_zeros((xsize + ysize + 4, xsize + ysize + 4))
        for layer in range(k + 1):
            offset = layer * n
            matrix[offset:offset+n, offset:offset+n] = transient
            if layer:
                matrix[offset:offset+n, offset-n:offset] = renewal
        last = k * n
        matrix[chain, last:last+n], matrix[chain+1, last:last+n] = upper, lower
        select = parameters.new_zeros((ysize, xsize))
        select[:n, last:last+n] = eye
        select[n, chain], select[n+1, chain+1] = 1, 1
        matrix[xsize:xsize+ysize, :xsize] = select
        j = xsize + ysize
        matrix[j, last:last+n] = lower
        matrix[j+1, last:last+n], matrix[j+1, chain] = 1, 1
        matrix[j:j+2, j:j+2] = discount * torch.eye(2, dtype=parameters.dtype)
        matrix[j+2:j+4, j:j+2] = torch.eye(2, dtype=parameters.dtype)
        matrices.append((matrix, select, xsize, ysize))

    def raw(time):
        total = parameters.new_zeros((n + 4, channels))
        if time < 0:
            return total
        for k, (matrix, select, xsize, ysize) in enumerate(matrices):
            j = xsize + ysize

            def response(duration, law, integrated):
                if duration < 0:
                    return parameters.new_zeros((n + 4, channels))
                source = torch.cat((law, law.new_zeros((len(matrix)-n, channels))), dim=0)
                value = torch.matrix_exp(matrix * duration) @ source
                ordinary = value[xsize:xsize+ysize] if integrated else select @ value[:xsize]
                discounted = value[j+2:j+4] if integrated else value[j:j+2]
                return torch.cat((ordinary, torch.exp(-discount*time)*discounted), dim=0)

            total = total + response(time-k*delay, initial, False)
            for start, end, vector, atom in packets:
                law = reset[:, None] * vector[None, :]
                if atom:
                    total = total + response(time-k*delay-start, law, False)
                else:
                    total = total + (response(time-k*delay-start, law, True)
                                     - response(time-k*delay-end, law, True)) / (end-start)
        return total

    rows = []
    for observed_time in times:
        time = parameters.new_tensor(observed_time)
        value, past = raw(time), raw(time-delay)
        remaining = value[n+1] - past[n+1]
        discounted_phase = torch.exp(discount*(time-delay)) * (value[n+2] - past[n+2])
        for start, end, vector, atom in packets:
            if atom:
                if time < start:
                    remaining = remaining + vector
                    discounted_phase = discounted_phase + torch.exp(-discount*(start-time))*vector
            elif time < end:
                lo = torch.maximum(start, time)
                remaining = remaining + (end-lo)/(end-start)*vector
                integral = torch.exp(-discount*(lo-time)) * -torch.expm1(-discount*(end-lo))
                discounted_phase = discounted_phase + integral/(discount*(end-start))*vector
        row = dict(time=observed_time, active=value[:n], upper=value[n]+initial_upper,
                         refractory=remaining, events=value[n+1], discounted_events=value[n+2],
                         discounted_active_time=value[n+3]-torch.expm1(-discount*time)/discount*initial_upper,
                         discounted_remaining_phase=discounted_phase)
        if any(not torch.isfinite(row[field]).all() for field in FIELDS):
            raise ArithmeticError("nonfinite matrix-exponential result")
        rows.append(row)
    return rows


def flatten(rows):
    """Keep the established field order for full-output derivative comparisons."""
    return torch.cat([row[field].reshape(-1) for row in rows for field in FIELDS])
