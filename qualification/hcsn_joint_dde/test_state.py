"""Cold-process continuation, source/physics fencing and retained age controls."""

from dataclasses import replace
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from scipy.integrate import solve_ivp

from qualification.hcsn_boundary_audit.refractory_transport import Packet
from .state_io import decode_state, evaluate_flux, flux_pieces
from .test_model import fixture, initial
from .graded import GradedSpatialGenerator
from .model import JointModel


CONTROLS = {"rtol": 2e-11, "atol": 2e-13, "max_step": 0.01}
FIELDS = ("active", "upper", "refractory", "events", "discounted_events",
          "discounted_active_time", "discounted_remaining_phase", "content_residual")


def resign(envelope):
    raw = json.dumps(envelope["payload"], sort_keys=True, separators=(",", ":")).encode()
    envelope["sha256"] = hashlib.sha256(raw).hexdigest()
    return json.dumps(envelope).encode()


class TestPersistentJointState(unittest.TestCase):
    def assert_rows(self, actual, expected, tolerance=3e-9):
        self.assertEqual(actual["time"], expected["time"])
        for field in FIELDS:
            np.testing.assert_allclose(actual[field], expected[field], rtol=0, atol=tolerance)
        self.assertLess(abs(actual["mass_residual"]), tolerance)

    def test_cold_process_resumes_actual_history_and_absolute_discount_clock(self):
        model = fixture()
        p, content = initial(model)
        prefix = model.solve([0.173, 0.417], p, content, export_state=True, **CONTROLS)
        reference = model.solve([0.173, 0.417, 0.6, 1.0], p, content, **CONTROLS)
        program = """
import json,sys
from pathlib import Path
from qualification.hcsn_joint_dde.test_model import fixture
from qualification.hcsn_joint_dde.test_state import CONTROLS
result=fixture().solve([.6,1.],checkpoint=Path(sys.argv[1]).read_bytes(),export_state=True,**CONTROLS)
Path(sys.argv[2]).write_bytes(result.pop('checkpoint'))
print(json.dumps(result,default=lambda a:a.tolist(),allow_nan=False))
"""
        with tempfile.TemporaryDirectory() as directory:
            before, after = Path(directory) / "before.json", Path(directory) / "after.json"
            before.write_bytes(prefix["checkpoint"])
            completed = subprocess.run([sys.executable, "-B", "-c", program, str(before), str(after)],
                                       capture_output=True, text=True, timeout=60, check=True)
            result = json.loads(completed.stdout)
            self.assertEqual(result["integration_started_at"], 0.417)
            self.assert_rows(result["rows"][-1], reference["rows"][-1])
            restored = decode_state(model, after.read_bytes())
            self.assertTrue(all(piece["right"] > 0.8 for piece in restored["history"]))
            self.assertEqual(restored["time"], 1.0)

    def test_repeated_restart_preserves_uniform_age_and_once_only_atom_release(self):
        model = fixture()
        p, content = initial(model)
        p *= 0.3
        content *= 0.3
        phase = (Packet("uniform", F(1, 25), F(3, 25), F(2, 5), (F(-1), F(2))),
                 Packet("atom", F(7, 100), F(7, 100), F(3, 10), (F(2), F(-1))))
        times = [0.052, 0.07, 0.137, 0.417, 1.0]
        reference = model.solve(times, p, content, phase, **CONTROLS)
        result = model.solve([times[0]], p, content, phase, export_state=True, **CONTROLS)
        for index, time in enumerate(times[1:], 1):
            result = model.solve([time], checkpoint=result["checkpoint"], export_state=True, **CONTROLS)
            self.assert_rows(result["rows"][0], reference["rows"][index])

    def test_zero_deadline_atom_is_not_paid_twice_after_restore(self):
        model = fixture()
        phase = (Packet("zero", F(0), F(0), F(1), (F(2),)),)
        prefix = model.solve([0.0], np.zeros(33), np.zeros((33, 1)), phase, export_state=True)
        result = model.solve([0.0, 0.2], checkpoint=prefix["checkpoint"], **CONTROLS)
        reference = model.solve([0.0, 0.2], np.zeros(33), np.zeros((33, 1)), phase, **CONTROLS)
        self.assert_rows(result["rows"][-1], reference["rows"][-1])
        self.assertEqual(result["rows"][0]["events"][0], 0)

    def test_equal_summary_moments_do_not_replace_the_remaining_age_law(self):
        model = fixture()
        weight = (np.exp(-0.15 * 0.1) - np.exp(-0.15 * 0.15)) / (np.exp(-0.15 * 0.05) - np.exp(-0.15 * 0.15))
        w = F(str(float(weight)))
        phase_a = (Packet("middle", F(1, 10), F(1, 10), F(1), (F(2),)),)
        phase_b = (Packet("early", F(1, 20), F(1, 20), w, (2*w,)),
                   Packet("late", F(3, 20), F(3, 20), 1-w, (2*(1-w),)))
        checkpoints = []
        rows = []
        for phase in (phase_a, phase_b):
            result = model.solve([0.0], np.zeros(33), np.zeros((33, 1)), phase, export_state=True)
            rows.append(result["rows"][0])
            checkpoints.append(result["checkpoint"])
        self.assert_rows(rows[0], rows[1], tolerance=1e-13)
        self.assertNotEqual(checkpoints[0], checkpoints[1])
        later = [model.solve([0.075], checkpoint=raw, **CONTROLS)["rows"][0] for raw in checkpoints]
        self.assertEqual(later[0]["active"][:, 0].sum(), 0)
        self.assertGreater(later[1]["active"][:, 0].sum(), 0.49)

    def test_digest_model_source_clock_and_missing_history_fail_closed(self):
        model = fixture()
        p, content = initial(model)
        raw = model.solve([0.417], p, content, export_state=True, **CONTROLS)["checkpoint"]
        with self.assertRaises(ValueError):
            replace(model, discount=0.16).solve([0.5], checkpoint=raw)
        with self.assertRaises(ValueError):
            model.solve([0.3], checkpoint=raw)
        with self.assertRaises(ValueError):
            model.solve([0.5], p, content, checkpoint=raw)
        for mutation in ("digest", "source", "history", "gap"):
            envelope = json.loads(raw)
            if mutation == "digest":
                envelope["payload"]["time"] = 0.4
                bad = json.dumps(envelope).encode()
            else:
                if mutation == "source":
                    envelope["payload"]["binding"]["sources"]["hcsn_joint_dde/model.py"] = "0" * 64
                elif mutation == "history":
                    envelope["payload"]["history"] = []
                else:
                    envelope["payload"]["history"].pop(1)
                bad = resign(envelope)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                model.solve([0.5], checkpoint=bad)

    def test_portable_flux_coefficients_equal_actual_bdf_dense_output(self):
        matrix = np.asarray([[-3.0, 1.0], [0.4, -1.0]])
        solution = solve_ivp(lambda t, y: matrix @ y, (0.0, 0.4), [0.8, -0.3],
                             method="BDF", dense_output=True, rtol=1e-10, atol=1e-12)
        lower = np.asarray([0.3, 0.2])
        pieces = flux_pieces(solution.sol, 1, 2, lower)
        for piece in pieces:
            for time in np.linspace(piece["left"], piece["right"], 4):
                np.testing.assert_allclose(evaluate_flux(piece, time)[0],
                                           solution.sol(time) @ lower, atol=2e-16, rtol=0)

    def test_pending_sources_and_actual_restore_budget_are_validated(self):
        model = fixture()
        phase = (Packet("release", F(7, 100), F(7, 100), F(1), (F(2),)),)
        raw = model.solve([0.0], np.zeros(33), np.zeros((33, 1)), phase, export_state=True)["checkpoint"]
        for mutation in ("drop_atom", "drop_knot", "duplicate", "budget"):
            envelope = json.loads(raw)
            payload = envelope["payload"]
            if mutation == "drop_atom":
                payload["atoms"] = []
            elif mutation == "drop_knot":
                payload["source_knots"] = [0.0]
            elif mutation == "duplicate":
                payload["atoms"].append(payload["atoms"][0])
            else:
                payload["source_knots"] = sorted(set([0.07, *np.linspace(0, 0.2, 4096).tolist()]))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                model.solve([1.0], checkpoint=resign(envelope))

    def test_official_graded_model_continues_from_its_own_retained_history(self):
        model = JointModel(GradedSpatialGenerator(32, 2.0, -0.12, 0.35), 0.5, 0.2, 0.15)
        p = np.zeros(33)
        p[8] = 1
        content = np.c_[2*p, -3*p]
        prefix = model.solve([0.173, 0.417], p, content, export_state=True, **CONTROLS)
        resumed = model.solve([1.0], checkpoint=prefix["checkpoint"], **CONTROLS)
        full = model.solve([0.173, 0.417, 1.0], p, content, **CONTROLS)
        self.assert_rows(resumed["rows"][0], full["rows"][-1])

    def test_resumed_finite_reward_and_continuation_share_the_same_generator(self):
        model = fixture()
        p, content = initial(model)
        prefix = model.solve([0.417], p, content, export_state=True, **CONTROLS)
        row = model.solve([1.0], checkpoint=prefix["checkpoint"], **CONTROLS)["rows"][0]
        values, reset_value = model.perpetual()
        terminal = row["active"][:, 0] @ values[1:-1] + row["upper"][0] * model.active_reward / model.discount
        terminal += row["discounted_remaining_phase"][0] * reset_value
        value = model.active_reward * row["discounted_active_time"][0] + model.hit_reward * row["discounted_events"][0]
        value += np.exp(-model.discount) * terminal
        self.assertAlmostEqual(value, p @ values, delta=5e-9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
