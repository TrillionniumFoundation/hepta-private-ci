"""R17 real saved-file manipulations; refuse forged outputs even under python -O."""

import hashlib, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
import numpy as np


def digest(b):
    return hashlib.sha256(b).hexdigest()


class TamperTests(unittest.TestCase):
    def attempt(self, mode, message):
        root = Path(os.environ["R17_RUNS"])
        source = Path(__file__).with_name("audit.py")
        with tempfile.TemporaryDirectory(prefix="r17-adversarial-") as temp:
            here = Path(temp)
            runs = here / "runs"
            runs.mkdir()
            for n in ("SWEEP_PLAN.json", "COMPLETE.json"):
                shutil.copy2(root / n, runs / n)
            completed = json.loads((runs / "COMPLETE.json").read_text())
            first = completed["results"][0]["name"]
            for row in completed["results"]:
                if row["name"] == first:
                    shutil.copytree(root / first, runs / first)
                else:
                    (runs / row["name"]).symlink_to(
                        root / row["name"], target_is_directory=True
                    )
            candidate = runs / first
            report = json.loads((candidate / "REPORT.json").read_text())
            seal = json.loads((candidate / "FIT_SEAL.json").read_text())
            if mode == "census":
                completed["results"].pop()
            elif mode == "weights":
                p = candidate / "WEIGHTS.npz"
                with np.load(p, allow_pickle=False) as z:
                    th = z["theta"].copy()
                th[0] += 0.2
                np.savez_compressed(p, theta=th)
            elif mode == "cost":
                report["cost"] += 0.08
            elif mode == "transfers":
                report["transfers"]["biased_input"] += 0.03
            elif mode == "initial":
                p = candidate / "INITIAL.npz"
                with np.load(p, allow_pickle=False) as z:
                    th = z["theta"].copy()
                th[0] += 0.04
                np.savez_compressed(p, theta=th)
            elif mode == "checkpoint":
                p = candidate / "CHECKPOINTS.npz"
                with np.load(p, allow_pickle=False) as z:
                    arrays = {name: z[name].copy() for name in z.files}
                self.assertGreater(len(arrays["theta"]), 2)
                arrays["theta"][1, 0] += 0.1
                np.savez_compressed(p, **arrays)
                seal["checkpoints_sha"] = digest(p.read_bytes())
                report["fit"] = seal
            elif mode == "clock":
                seal["fit_cpu"] = 0.0
                report["fit"] = seal
            if mode in ("cost", "transfers", "checkpoint", "clock"):
                (candidate / "REPORT.json").write_text(json.dumps(report))
                completed["results"][0]["report_sha"] = digest(
                    (candidate / "REPORT.json").read_bytes()
                )
            if mode in ("checkpoint", "clock"):
                (candidate / "FIT_SEAL.json").write_text(json.dumps(seal))
            (runs / "COMPLETE.json").write_text(json.dumps(completed))
            cmd = [
                sys.executable,
                "-O",
                str(source),
                "--runs",
                str(runs),
                "--out",
                str(here / "checked"),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=55)
            self.assertNotEqual(r.returncode, 0, (mode, r.stdout, r.stderr))
            self.assertIn(message, r.stderr)
            self.assertFalse((here / "checked/AUDIT.json").exists())

    def test_incomplete_census(self):
        self.attempt("census", "incomplete census")

    def test_wrong_initial(self):
        self.attempt("initial", "initial mismatch")

    def test_changed_weights(self):
        self.attempt("weights", "weight mismatch")

    def test_rehashed_false_cost(self):
        self.attempt("cost", "false final cost")

    def test_rehashed_false_transfer(self):
        self.attempt("transfers", "false transfer panel")

    def test_rehashed_checkpoint_values(self):
        self.attempt("checkpoint", "checkpoint cost mismatch")

    def test_rehashed_shortened_fit_time(self):
        self.attempt("clock", "invalid checkpoint CPU chronology")


class CompletenessTests(unittest.TestCase):
    """Synthetic initial tensors only: no optimizer, fit, or historical result."""

    @staticmethod
    def write_json(path, value):
        data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
        path.write_bytes(data)
        return digest(data)

    @staticmethod
    def save_arrays(path, **arrays):
        with path.open("xb") as stream:
            np.savez_compressed(stream, **arrays)

    @classmethod
    def setUpClass(cls):
        import problem
        import run
        import solver

        cls.temporary = tempfile.TemporaryDirectory(prefix="r17-completeness-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.baseline = cls.root / "baseline"
        cls.baseline.mkdir()
        cls.script = Path(__file__).with_name("audit.py")
        plan = dict(
            parent=run.PARENT,
            protocol=run.PROTOCOL,
            specs=run.specs(),
            source=run.sources(),
            cap=run.CPU_CAP,
            synthetic_fixture=True,
        )
        plan_sha = cls.write_json(cls.baseline / "SWEEP_PLAN.json", plan)
        results = []
        for case in run.specs():
            folder = cls.baseline / run.name(case)
            folder.mkdir()
            theta = np.asarray(solver.INITIALS[case["seed"]], dtype=np.float64)
            cost, gradient, hessian = problem.objective(theta, run.kappa(case))
            child = dict(
                case=case,
                source=plan["source"],
                protocol_commit=run.PROTOCOL,
                synthetic_fixture=True,
            )
            child_sha = cls.write_json(folder / "PLAN.json", child)
            cls.save_arrays(folder / "INITIAL.npz", theta=theta)
            cls.save_arrays(folder / "WEIGHTS.npz", theta=theta)
            cls.save_arrays(
                folder / "CHECKPOINTS.npz",
                theta=np.asarray([theta]),
                cpu=np.asarray([0.0]),
                cost=np.asarray([cost]),
            )
            seal = dict(
                plan_sha=child_sha,
                initial_sha=digest(theta.tobytes()),
                weight_sha=digest(theta.tobytes()),
                checkpoints_sha=digest((folder / "CHECKPOINTS.npz").read_bytes()),
                fit_cpu=0.001,
                status="synthetic_zero_fit",
            )
            cls.write_json(folder / "FIT_SEAL.json", seal)
            report = dict(
                plan_sha=child_sha,
                case=case,
                initial_sha=seal["initial_sha"],
                weight_sha=seal["weight_sha"],
                fit=seal,
                cost=cost,
                independent_leaf_cost=problem.direct(theta, run.kappa(case)),
                gradient_inf=float(np.max(np.abs(gradient))),
                hessian_min=float(np.linalg.eigvalsh(hessian)[0]),
                transfers=problem.transfer(theta, run.kappa(case)),
                num_checkpoints=1,
                peak_rss=0,
                source=plan["source"],
                synthetic_fixture=True,
            )
            report_sha = cls.write_json(folder / "REPORT.json", report)
            results.append(
                dict(
                    case=case,
                    name=run.name(case),
                    status="completed",
                    returncode=0,
                    report_sha=report_sha,
                    child_cpu=0.0,
                    child_wall=0.0,
                )
            )
        cls.write_json(
            cls.baseline / "COMPLETE.json",
            dict(
                plan_sha=plan_sha,
                results=results,
                completed=64,
                failed=0,
                child_cpu=0.0,
                wall=0.0,
            ),
        )
        result = cls.run_audit(cls.baseline, "baseline-audit")
        if result.returncode != 0:
            raise AssertionError(("synthetic baseline", result.stdout, result.stderr))
        if not (cls.root / "baseline-audit" / "AUDIT.json").is_file():
            raise AssertionError("synthetic baseline audit missing")

    @classmethod
    def run_audit(cls, runs, name):
        command = [sys.executable, "-B"]
        if sys.flags.optimize:
            command.append("-O")
        command += [
            str(cls.script),
            "--runs",
            str(runs),
            "--out",
            str(cls.root / name),
        ]
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=55,
            env=dict(
                os.environ,
                OPENBLAS_NUM_THREADS="1",
                OMP_NUM_THREADS="1",
                MKL_NUM_THREADS="1",
            ),
        )

    def test_missing_executed_source_rejected_after_rehash(self):
        runs = self.root / "missing-source"
        shutil.copytree(self.baseline, runs)
        plan = json.loads((runs / "SWEEP_PLAN.json").read_text())
        del plan["source"]["problem.py"]
        plan_sha = self.write_json(runs / "SWEEP_PLAN.json", plan)
        complete = json.loads((runs / "COMPLETE.json").read_text())
        complete["plan_sha"] = plan_sha
        for entry in complete["results"]:
            folder = runs / entry["name"]
            child = json.loads((folder / "PLAN.json").read_text())
            child["source"] = plan["source"]
            child_sha = self.write_json(folder / "PLAN.json", child)
            seal = json.loads((folder / "FIT_SEAL.json").read_text())
            seal["plan_sha"] = child_sha
            self.write_json(folder / "FIT_SEAL.json", seal)
            report = json.loads((folder / "REPORT.json").read_text())
            report.update(plan_sha=child_sha, fit=seal, source=plan["source"])
            entry["report_sha"] = self.write_json(folder / "REPORT.json", report)
        self.write_json(runs / "COMPLETE.json", complete)
        result = self.run_audit(runs, "missing-source-audit")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("executed source census incomplete", result.stderr)
        self.assertFalse((self.root / "missing-source-audit" / "AUDIT.json").exists())

    def test_transfer_census_and_nonfinite_values_rejected(self):
        for mode, diagnostic in (
            ("missing", "incomplete transfer panel"),
            ("nan", "false transfer panel"),
        ):
            with self.subTest(mode=mode):
                runs = self.root / ("transfer-" + mode)
                shutil.copytree(self.baseline, runs)
                complete = json.loads((runs / "COMPLETE.json").read_text())
                entry = complete["results"][-1]
                path = runs / entry["name"] / "REPORT.json"
                report = json.loads(path.read_text())
                if mode == "missing":
                    del report["transfers"]["biased_input"]
                else:
                    report["transfers"]["biased_input"] = float("nan")
                entry["report_sha"] = self.write_json(path, report)
                self.write_json(runs / "COMPLETE.json", complete)
                result = self.run_audit(runs, "transfer-" + mode + "-audit")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(diagnostic, result.stderr)
                self.assertFalse(
                    (
                        self.root / ("transfer-" + mode + "-audit") / "AUDIT.json"
                    ).exists()
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
