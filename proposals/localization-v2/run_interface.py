"""Isolated real six-family interface attempts; no efficacy ranking or formal fits."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

from data import prepare, save, sha

ROOT = Path(__file__).resolve().parents[2]
ARMS = ("gru", "cfc", "snn_plif", "ssm_s4d", "attention", "hcsn")
SEEDS = (20261108, 20261109, 20261110)
PROFILE_SHA = "a6661067b366f386d96782687dee6ace5718ffcd8148b2def3bca286c7293600"
BUDGET = {"threads": 1, "cuda": False, "rss_bytes": 2**31,
          "per_arm_seed_seconds": 180, "suite_seconds": 1800,
          "updates_per_fit": 4, "window_events": 32, "learning_rate": .001,
          "gradient_norm_cap": 1., "external_memory_enforcement": "caller-provided hard envelope required"}


class NumericalHold(ValueError):
    pass


def sources():
    files = list(Path(__file__).parent.glob("*.py"))
    files += list((ROOT / "qualification/hcsn_differentiable").glob("*.py"))
    return {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in sorted(files)}


def rss():
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform == "darwin" else value * 1024)
    except ImportError:
        return None


def admitted_hcsn(receipt_path, features):
    if receipt_path is None:
        raise ValueError("HOLD: no new d=0.2 numerical receipt supplied")
    receipt = json.loads(receipt_path.read_text())
    gates = {"all_global_gap_interfaces", "locked_gap_perpetual", "refinement_anchors", "locked_unconditioned_sequences"}
    if (receipt.get("schema") != "hcsn-localization-v2-budget-result-v1"
            or receipt.get("status") != "passed_locked_frozen_profile"
            or receipt.get("profile_sha256") != PROFILE_SHA
            or receipt.get("source_unchanged") is not True
            or receipt.get("source_before") != receipt.get("source_after")
            or set(receipt.get("gates", {})) != gates
            or not all(v is True for v in receipt["gates"].values())):
        raise ValueError("HOLD: exact locked frozen-physics profile has not passed all gates")
    needed = {"qualification/hcsn_differentiable/" + name for name in
              ("contract.py", "operator.py", "network.py", "regenerative.py", "value.py")}
    if not needed.issubset(receipt.get("source_before", {})):
        raise ValueError("HOLD: numerical source manifest is incomplete")
    for name, expected in receipt["source_before"].items():
        if name.endswith(".py") and sha((ROOT / name).read_bytes()) != expected:
            raise ValueError(f"HOLD: numerical implementation source mismatch: {name}")
    for part, seq in (("train", "A01"), ("dev", "D01")):
        selected = receipt["selection"][seq]
        if (selected["row_ids"] != features[part]["source_rows"]
                or selected["gap_ticks"] != features[part]["delta_ticks"]):
            raise ValueError("HOLD: data windows/gaps differ from the numerical receipt")
    import torch
    from qualification.hcsn_differentiable.contract import GridSpec
    from qualification.hcsn_differentiable.network import ContinuousSpikingNetwork, TrainablePhysics
    profile = receipt["profile"]

    class HCSN(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.core = ContinuousSpikingNetwork(25, 4, 11, layer_count=1, grid=GridSpec(**profile["grid"]))
            params = {k: v for k, v in profile["physics"].items() if k != "trainable"}
            self.core.layers[0].physics = TrainablePhysics(**params).requires_grad_(False)
            physical = self.core.layers[0].physics()
            actual = {k: float(v).hex() for k, v in zip(
                ("log_boundary", "mu", "sigma", "absolute_reset", "discount"), physical.tensors())}
            if profile["physics"]["trainable"] or actual != receipt["actual_physics_hex"]:
                raise ValueError("HOLD: instantiated physics differs from the tested FP64 values")
            self.initial = math.exp(profile["initial_margin"] + params["log_boundary"])
            self.last_diagnostics = {}

        def forward(self, x, dt):
            result = self.core(x, dt, state=self.core.initial_state(x.shape[0], absolute_initial=self.initial))
            self.last_diagnostics = result.diagnostics
            return result.predictions

    model = HCSN().cpu().double()
    return model, {"arm": "hcsn", "qualification_sha256": sha(receipt_path.read_bytes()),
                   "profile_sha256": PROFILE_SHA, "profile": profile,
                   "actual_physics_hex": receipt["actual_physics_hex"], "dtype": "float64", "device": "cpu"}


def worker(args):
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    started, cpu_started = time.perf_counter(), time.process_time()
    report = {"arm": args.worker[0], "seed": int(args.worker[1]), "status": "started",
              "formal_fits_started": 0, "smoke_fits_started": 0, "completed_updates_recorded": 0,
              "source_before": sources(), "physical_energy_joules": None,
              "energy_missing_reason": "no whole-system meter", "provider_charges": None,
              "budget": BUDGET, "loss_records": [], "independent_unit": "freshly_initialized_training_run"}
    events = (output / "events.jsonl").open("x", encoding="utf-8")

    def event(kind, **values):
        events.write(json.dumps({"event": kind, "wall_seconds": time.perf_counter() - started, **values}) + "\n")
        events.flush()

    def check():
        peak = rss()
        if time.perf_counter() - started > 180 or (peak is not None and peak > 2**31):
            raise TimeoutError("fixed worker wall/RSS budget exhausted")

    try:
        sys.path.insert(0, str(ROOT))
        import torch
        from models import build_model, metadata
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        torch.manual_seed(report["seed"])
        report["torch"] = torch.__version__
        manifest = json.loads((args.prepared / "data-manifest.json").read_text())
        payload = (args.prepared / "features.json").read_bytes()
        if sha(payload) != manifest["features_sha256"]:
            raise ValueError("shared features changed after data preparation")
        features = json.loads(payload)
        report.update(features_sha256=sha(payload), frontend_sha256=manifest["frontend_sha256"])
        if report["arm"] == "hcsn":
            try:
                model, identity = admitted_hcsn(args.hcsn_qualification, features)
            except (ValueError, KeyError, OSError) as error:
                raise NumericalHold(str(error)) from error
        else:
            model = build_model(report["arm"], s4_repo=args.s4_repo)
            identity = metadata(model)
        report["model"] = identity
        trainable = [p for p in model.parameters() if p.requires_grad]
        frozen = {n: p.detach().clone() for n, p in model.named_parameters() if not p.requires_grad}
        report["trainable_parameters"] = sum(p.numel() for p in trainable)
        if any(p.device.type != "cpu" for p in model.parameters()):
            raise ValueError("GPU execution forbidden")
        optimizer = torch.optim.Adam(trainable, lr=.001)
        initial = output / "initial.pt"
        torch.save(model.state_dict(), initial)
        report["initialization_sha256"] = sha(initial.read_bytes())
        report["smoke_fits_started"] = 1
        event("fit_started", initialization_sha256=report["initialization_sha256"])
        tensors = {part: (torch.tensor(v["x"], dtype=torch.float64)[None],
                          torch.tensor(v["dt"], dtype=torch.float64)[None],
                          torch.tensor(v["y"], dtype=torch.long)) for part, v in features.items()}
        x, dt, y = tensors["train"]
        for index in range(4):
            check()
            lo, hi = index * 32, (index + 1) * 32
            optimizer.zero_grad(set_to_none=True)
            logits = model(x[:, lo:hi], dt[:, lo:hi])
            loss = torch.nn.functional.cross_entropy(logits[0], y[lo:hi])
            if logits.shape != (1, 32, 11) or not bool(torch.isfinite(loss)):
                raise FloatingPointError("invalid training output/loss")
            loss.backward()
            if any(p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in trainable):
                raise FloatingPointError("missing/nonfinite training gradient")
            norm = torch.nn.utils.clip_grad_norm_(trainable, 1.)
            if not bool(torch.isfinite(norm)) or float(norm) <= 0:
                raise FloatingPointError("zero/nonfinite total gradient norm")
            event("optimizer_step_started", update=index + 1)
            optimizer.step()
            report["completed_updates_recorded"] += 1
            event("optimizer_step_completed", update=index + 1)
            report["loss_records"].append({"window": [lo, hi], "loss_before_update": float(loss.detach()),
                                           "preclip_gradient_norm": float(norm),
                                           "diagnostics": getattr(model, "last_diagnostics", {})})
            checkpoint = output / f"update-{index + 1}.pt"
            torch.save({"model": model.state_dict(), "optimizer": optimizer.state_dict(),
                        "rng": torch.get_rng_state(), "source_rows": features["train"]["source_rows"][lo:hi]}, checkpoint)
            report["checkpoint_sha256"] = sha(checkpoint.read_bytes())
        check()
        model.eval()
        with torch.no_grad():
            x, dt, y = tensors["dev"]
            logits = model(x, dt)
            if logits.shape != (1, 64, 11) or not bool(torch.isfinite(logits).all()):
                raise FloatingPointError("invalid development output")
            report["development_cross_entropy"] = float(torch.nn.functional.cross_entropy(logits[0], y))
        report["dev_logits_sha256"] = save(output / "development-logits.json", logits[0].tolist())
        report["frozen_parameters_unchanged"] = all(torch.equal(old, dict(model.named_parameters())[n]) for n, old in frozen.items())
        if not report["frozen_parameters_unchanged"]:
            raise ValueError("frozen physical parameters changed during optimizer steps")
        check()
        report["status"] = "completed_interface_only"
    except NumericalHold as error:
        report.update(status="blocked_numeric", error=str(error))
    except (ImportError, ValueError) as error:
        report.update(status="HOLD" if not report["smoke_fits_started"] else "failed_interface",
                      error=f"{type(error).__name__}: {error}")
    except Exception:
        report.update(status="failed_or_budget_exhausted", error=traceback.format_exc())
    finally:
        report.update(source_after=sources(), wall_seconds=time.perf_counter() - started,
                      process_cpu_seconds=time.process_time() - cpu_started, peak_rss_bytes=rss())
        report["source_unchanged"] = report["source_after"] == report["source_before"]
        if not report["source_unchanged"]:
            report["status"] = "source_changed"
        event("finished", status=report["status"])
        events.close()
        report["events_sha256"] = sha((output / "events.jsonl").read_bytes())
        save(output / "result.json", report)
    return 0 if report["status"] == "completed_interface_only" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run", action="store_true", help="run the fixed 18 interface attempts after data audit")
    parser.add_argument("--s4-repo", type=Path)
    parser.add_argument("--hcsn-qualification", type=Path)
    parser.add_argument("--worker", nargs=2, metavar=("ARM", "SEED"), help=argparse.SUPPRESS)
    parser.add_argument("--prepared", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[variable] = "1"
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    if args.worker:
        if args.worker[0] not in ARMS or int(args.worker[1]) not in SEEDS or args.prepared is None:
            parser.error("worker must use a locked arm/seed and prepared data")
        return worker(args)
    if args.archive is None:
        parser.error("--archive is required")
    started = time.perf_counter()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"schema": "hcsn-localization-v2-interface-suite-v1", "status": "started",
              "budget": BUDGET, "seeds": SEEDS, "arms": ARMS, "formal_fits_started": 0,
              "source_before": sources(), "started_utc": datetime.now(timezone.utc).isoformat(), "attempts": [],
              "claim_boundary": "Three independent initializations check real interfaces; tiny unequal models/four updates cannot rank six families or establish trained SNN quality."}
    save(args.output / "locked-plan.json", report)
    try:
        _, data = prepare(args.archive, args.output / "data")
        report["data"] = data
        if args.run:
            for seed in SEEDS:
                for arm in ARMS:
                    remaining = 1800 - (time.perf_counter() - started)
                    if remaining <= 0:
                        report["attempts"].append({"arm": arm, "seed": seed, "status": "not_started_budget"})
                        continue
                    destination = args.output / f"{arm}-{seed}"
                    command = [sys.executable, str(Path(__file__).resolve()), "--worker", arm, str(seed),
                               "--prepared", str((args.output / "data").resolve()), "--output", str(destination)]
                    for flag, value in (("--s4-repo", args.s4_repo), ("--hcsn-qualification", args.hcsn_qualification)):
                        if value is not None:
                            command += [flag, str(value.resolve())]
                    begin = time.perf_counter()
                    with (args.output / f"{arm}-{seed}.stdout").open("xb") as out, (args.output / f"{arm}-{seed}.stderr").open("xb") as err:
                        try:
                            process = subprocess.run(command, stdout=out, stderr=err, timeout=min(180, remaining), check=False)
                            row = json.loads((destination / "result.json").read_text()) if (destination / "result.json").exists() else {"status": "worker_exited_without_result"}
                            row["exit_code"] = process.returncode
                        except subprocess.TimeoutExpired:
                            row = {"status": "killed_at_budget", "completed_updates": None,
                                   "detail": "Read durable events; an in-flight optimizer step can remain unresolved."}
                    row.update(arm=arm, seed=seed, process_wall_seconds=time.perf_counter() - begin,
                               output_directory=str(destination))
                    report["attempts"].append(row)
        report["status"] = ("data_only_verified" if not args.run else "completed_interfaces_only"
                            if all(r["status"] == "completed_interface_only" for r in report["attempts"]) else "partial_or_held_interfaces")
    except Exception:
        report.update(status="blocked_data_or_runner", error=traceback.format_exc())
    finally:
        report.update(source_after=sources(), wall_seconds=time.perf_counter() - started)
        report["source_unchanged"] = report["source_before"] == report["source_after"]
        if not report["source_unchanged"]:
            report["status"] = "source_changed"
        save(args.output / "suite.json", report)
    print(json.dumps({"status": report["status"], "output": str(args.output), "attempts": len(report["attempts"])}))
    return 0 if report["status"] in ("data_only_verified", "completed_interfaces_only") else 2


if __name__ == "__main__":
    raise SystemExit(main())
