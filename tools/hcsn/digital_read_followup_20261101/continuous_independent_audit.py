"""Independent flux, mass and restore checks for the continuous reference only."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
from . import continuous_renewal as renewal


def renewal_audit():
    max_flux_error, max_mass_error, cases = 0., 0., 0
    for drift in (-1.1, -.4, 0., .4, 1.1):
        law = renewal.Law(drift=drift)
        for x in (-.79, -.4, 0., .4, .79):
            for duration in (.001, .03, .4, 1.99):
                step = duration*1e-5
                numerical = (renewal.exit_cdf(x, duration+step, law)-renewal.exit_cdf(x, duration-step, law))/(2*step)
                max_flux_error = max(max_flux_error, float(abs(numerical-renewal.exit_density(x, duration, law)).max()))
                mass = renewal.killed_cdf(x, law.boundary, duration, law)+renewal.exit_cdf(x, duration, law).sum()
                max_mass_error = max(max_mass_error, abs(float(mass)-1))
                cases += 1
    # Recovery consumes remaining time and reset evolves immediately, rather
    # than returning at the external interval boundary.
    law = renewal.Law()
    starting = renewal.State(-law.boundary, -1, .075)
    rng = np.random.default_rng(81523)
    payload = renewal.checkpoint(starting, rng, law)
    restored, fresh_rng, fresh_law = renewal.restore(json.loads(json.dumps(payload)))
    result1, events1 = renewal.advance(starting, .5, law, rng)
    result2, events2 = renewal.advance(restored, .5, fresh_law, fresh_rng)
    assert (result1, events1) == (result2, events2)
    assert rng.bit_generator.state == fresh_rng.bit_generator.state
    # Negative calls and guard failures must not consume random state.
    before = deepcopy(rng.bit_generator.state)
    for invalid in (-1., float("nan"), 2.001):
        try:
            renewal.advance(starting, invalid, law, rng)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid interval accepted")
        assert rng.bit_generator.state == before
    assert max_flux_error < 1e-6 and max_mass_error < 1e-9
    return dict(flux_derivative_cases=cases, max_flux_derivative_absolute_error=max_flux_error,
                max_survival_exit_mass_error=max_mass_error, checkpoint_roundtrip=True,
                invalid_input_rng_atomicity_cases=3,
                scope="Numerical identities and local restore; not autodiff, production, or process-crash qualification",
                passed=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = dict(schema="continuous-independent-audit-v1", checks=renewal_audit(),
                  source_sha256={Path(path).name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                                 for path in (renewal.__file__, __file__)})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
