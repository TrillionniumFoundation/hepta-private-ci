"""P1 diagnostic: exact deterministic-delay age versus per-step phase reprojection.

Independent stdlib/Fraction oracle for the refractory-phase submodel ONLY.
Original remaining delay is uniform in one 0.025-second cell. After physical
time T=0.02, released mass enters a permanent absorbing marker. This omits
the active diffusion, physical re-entry after reset, rewards and gradients.
It is a diagnostic, NOT an HCSN operator replacement or continuum admission.
"""
from fractions import Fraction
import json
import sys
import unittest

CELLS = 8
WIDTH = Fraction(1, 40)  # refractory=0.2 divided into 8 cells
TOTAL_TIME = Fraction(1, 50)
SPLITS = (2, 4, 8, 16, 32)
EDGES = tuple(i * WIDTH for i in range(CELLS + 1))


def _positive(value):
    return max(Fraction(0), value)


def project_uniform_cell(source, elapsed):
    """Transport exact source-uniform remaining-time interval, project ONCE.

    The final coordinate is cumulative release (an absorbing marker). Every
    value is rational, including substep durations and overlap fractions.
    """
    if not 0 <= source < CELLS or elapsed < 0:
        raise ValueError("invalid phase cell or negative elapsed time")
    left, right = EDGES[source] - elapsed, EDGES[source + 1] - elapsed
    phase = [
        _positive(min(right, EDGES[j + 1]) - max(left, EDGES[j])) / WIDTH
        for j in range(CELLS)
    ]
    released = Fraction(1) - sum(phase)
    if released < 0:
        raise ArithmeticError("negative released mass")
    return tuple(phase + [released])


def _projected_one_step(elapsed):
    rows = [project_uniform_cell(i, elapsed) for i in range(CELLS)]
    return tuple(rows + [tuple([Fraction(0)] * CELLS + [Fraction(1)])])


def project_every_substep(source, count):
    """Intentionally lossy baseline: re-uniformize within each phase bin."""
    if count < 1:
        raise ValueError("count must be positive")
    step = TOTAL_TIME / count
    kernel = _projected_one_step(step)
    vector = [Fraction(int(i == source)) for i in range(CELLS + 1)]
    for _ in range(count):
        vector = [
            sum(vector[i] * kernel[i][j] for i in range(CELLS + 1))
            for j in range(CELLS + 1)
        ]
    return tuple(vector)


def transport_unprojected_age(source, increments):
    """Age accumulator preserves the ORIGINAL uniform support between calls."""
    if any(delta < 0 for delta in increments):
        raise ValueError("negative time")
    return project_uniform_cell(source, sum(increments, Fraction(0)))


def total_variation(first, second):
    if len(first) != len(second):
        raise ValueError("dimension mismatch")
    return sum((abs(a - b) for a, b in zip(first, second)), Fraction(0)) / 2


def diagnostic():
    results = {}
    for count in SPLITS:
        row_tvs = [
            total_variation(project_every_substep(i, count),
                            project_uniform_cell(i, TOTAL_TIME))
            for i in range(CELLS)
        ]
        worst = max(row_tvs)
        results[count] = {
            "max_tv": str(worst),
            "max_tv_float": float(worst),
            "argmax_source_cell": row_tvs.index(worst),
            "mass_exact": all(
                sum(project_every_substep(i, count)) == 1
                for i in range(CELLS)
            ),
            "unprojected_age_max_tv": "0",
        }
    return results


class TestExactPhaseAgeOracle(unittest.TestCase):
    def test_direct_uniform_geometry_and_absorbing_mass(self):
        for i in range(CELLS):
            for elapsed in (Fraction(0), TOTAL_TIME, Fraction(1, 5)):
                with self.subTest(i=i, elapsed=str(elapsed)):
                    row = project_uniform_cell(i, elapsed)
                    self.assertEqual(sum(row), 1)
                    self.assertTrue(all(x >= 0 for x in row))
        self.assertEqual(project_uniform_cell(0, Fraction(1, 5))[-1], 1)

    def test_age_transport_is_exact_for_all_partition_schedules(self):
        target = [project_uniform_cell(i, TOTAL_TIME) for i in range(CELLS)]
        for n in SPLITS:
            for i in range(CELLS):
                with self.subTest(n=n, i=i):
                    self.assertEqual(
                        transport_unprojected_age(i, [TOTAL_TIME / n] * n),
                        target[i],
                    )
                    self.assertEqual(
                        transport_unprojected_age(
                            i, [TOTAL_TIME / (2 * n)] * n
                               + [TOTAL_TIME / 2]),
                        target[i],
                    )

    def test_every_step_reprojection_is_mass_conservative_but_not_a_semigroup(self):
        results = diagnostic()
        values = [Fraction(results[n]["max_tv"]) for n in SPLITS]
        self.assertEqual(values[0], Fraction("0.32"))
        self.assertEqual(values[1], Fraction("0.3904"))
        self.assertEqual(values[2], Fraction("0.41736248"))
        self.assertTrue(all(a < b for a, b in zip(values, values[1:])))
        self.assertTrue(all(results[n]["mass_exact"] for n in SPLITS))
        self.assertGreater(values[-1], Fraction("0.435"))

    def test_isolation_uses_no_stochastic_diffusion_or_model_fit(self):
        for i in range(CELLS):
            for n in SPLITS:
                with self.subTest(i=i, n=n):
                    exact = transport_unprojected_age(i, [TOTAL_TIME / n] * n)
                    self.assertEqual(total_variation(
                        exact, project_uniform_cell(i, TOTAL_TIME)), 0)


if __name__ == "__main__":
    if "--red-hypothesis" in sys.argv:
        row = diagnostic()
        print("RED_PHASE_ONLY=" + json.dumps(row, sort_keys=True), flush=True)
        assert Fraction(row[32]["max_tv"]) <= Fraction(row[2]["max_tv"]) / 2, (
            "falsified: reducing time steps while reprojecting phase bins"
            " does not halve fixed-time TV")
    else:
        print("GREEN_PHASE_ONLY=" + json.dumps(diagnostic(), sort_keys=True),
              flush=True)
        unittest.main(verbosity=2)
