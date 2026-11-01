"""Independent positive forward PDE with delayed boundary-flux reinjection.

Interior point masses evolve with centered nonnegative neighbor rates. An upper
absorbing wall is a numerical truncation; its lost mass is explicitly retained.
The lower absorption flux is counted immediately. For regenerative runs it is
re-injected after the full refractory delay, not at the observation endpoint.
Moving-boundary coordinates have drift mu-b'(t), with b deterministic and C1.
"""

import math
import time

import numpy as np


def solve(case, spacing, edges, *, regenerate, speed=0.0, curvature=0.0, upper=8.0):
    x, mu, sigma, horizon = [case[k] for k in ("x", "mu", "sigma", "horizon")]
    reset, refractory = case.get("reset", 0.8), case.get("refractory", 0.2)
    if min(x, sigma, horizon, spacing) <= 0 or (regenerate and refractory <= 0):
        raise ValueError("Interior state and positive delayed-reinjection parameters required")
    cpu, wall = time.process_time(), time.perf_counter()
    intervals = int(round(upper / spacing))
    h = upper / intervals
    grid = np.arange(1, intervals) * h
    diffusion = sigma * sigma / 2
    steps = int(math.ceil(horizon * sigma * sigma / (0.4 * h * h)))
    dt = horizon / steps
    if regenerate and refractory < dt:
        raise ValueError("Refractory delay unresolved by this numerical time grid")

    def atom(position):
        coordinate = position / h - 1
        left = int(math.floor(coordinate))
        if left < 0 or left + 1 >= len(grid):
            raise ValueError("Initial/reset location outside interior nodes")
        answer = np.zeros_like(grid)
        answer[left:left + 2] = [left + 1 - coordinate, coordinate - left]
        return answer

    p, reset_law = atom(x), atom(reset)
    flux_history = np.zeros(steps + 1)
    count, lost, recovery, minimum = 0.0, 0.0, 0.0, 0.0
    for step in range(steps):
        t = (step + 0.5) * dt
        drift = mu - speed - 2 * curvature * t
        up, down = diffusion / h**2 + drift / (2 * h), diffusion / h**2 - drift / (2 * h)
        if min(up, down) < 0 or dt * (up + down) > 1:
            raise ArithmeticError("PDE positivity/CFL violated; no rate clipping")
        flux = down * p[0]
        flux_history[step] = flux
        delayed = 0.0
        if regenerate:
            at = step - refractory / dt
            if at >= 0:
                left = int(math.floor(at))
                fraction = at - left
                delayed = (1 - fraction) * flux_history[left] + fraction * flux_history[left + 1]
        updated = (1 - dt * (up + down)) * p
        updated[1:] += dt * up * p[:-1]
        updated[:-1] += dt * down * p[1:]
        if regenerate:
            updated += dt * delayed * reset_law
            recovery += dt * (flux - delayed)
        count += dt * flux
        lost += dt * up * p[-1]
        p = updated
        minimum = min(minimum, float(p.min()), recovery)
    bins = []
    # Piecewise-constant cell mass avoids classifying a whole boundary node into
    # one bin. The two exterior half cells are empty; no mass is renormalized.
    for lo, hi in zip(edges[:-1], edges[1:]):
        overlap = np.maximum(0.0, np.minimum(grid + h / 2, hi) - np.maximum(grid - h / 2, lo)) / h
        bins.append(float(p @ overlap))
    accounted = float(p.sum()) + lost + (recovery if regenerate else count)
    return {"spacing": h, "steps": steps, "dt": dt, "active": [float(p.sum()),
            float(p @ grid), float(p @ (grid * grid)), *bins],
            "refractory_mass": recovery, "event_count": count, "upper_loss": lost,
            "accounted_mass": accounted, "minimum_probability": minimum,
            "final_positions": grid.tolist(), "final_probability": p.tolist(),
            "cpu_seconds": time.process_time() - cpu, "wall_seconds": time.perf_counter() - wall,
            "regenerate": regenerate, "boundary_speed": speed, "boundary_curvature": curvature}
