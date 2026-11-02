"""Independent IG sampling definitions copied exactly from frozen v2."""
from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True)
class Physics:
    nu: float
    sigma: float
    reset: float
    refractory: float

    def validate(self):
        if self.sigma <= 0 or self.reset <= 0 or self.refractory <= 0:
            raise ValueError("sigma, reset, and refractory must be positive")

def sample_counts(rng, physics, x, horizon, size, remaining=0.0):
    """Independent exact IG event sampling; no CDF or time-step detection."""
    if physics.nu >= 0:
        raise ValueError("IG simulator contract requires negative drift")
    hitting = rng.wald(x / -physics.nu, x*x / physics.sigma**2, size=size)
    hitting += remaining
    counts = np.zeros(size, dtype=int)
    while np.any(hitting <= horizon):
        active = hitting <= horizon
        counts[active] += 1
        hitting[active] += physics.refractory + rng.wald(
            physics.reset / -physics.nu, physics.reset**2 / physics.sigma**2,
            size=int(active.sum()))
    return counts
