"""Independent staged audits of one exact, genuinely updated shared-head HCSN."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import resource
import sys
import time
import traceback

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "source"))
sys.path.insert(0, str(root / "source/proposals/localization-v3"))

import mpmath as mp
import numpy as np
import torch
from cores import CoreStudyModel, tensor_digest
from qualification.hcsn_differentiable.contract import GridSpec, PhysicalParameters
from qualification.hcsn_differentiable.training_domain import TrainingDomainRecorder, read_trace, model_digest
from qualification.hcsn_differentiable.training_domain_audit import audit_trace
from qualification.hcsn_differentiable.training_domain_finite import audit_finite_schedule


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("stage", choices=["export", "training-audit", "eval-A01-0", "eval-A01-256", "eval-A04-3072"]
                    + [f"finite-{i}" for i in range(5)])
args = parser.parse_args()
stage = args.stage
result_path = root / f"{stage}-receipt.json"
if result_path.exists():
    parser.error("retained stage result already exists; choose a new attempt directory")
plan = json.loads((root / "plan.json").read_text())
sources = {str(p.relative_to(root / "source")): sha(p) for p in (root / "source").rglob("*.py")}
assert sources == plan["source_before"]
assert sha(root / "training-probe/after.pt") == plan["checkpoint_sha256"]
assert sha(root / "training-probe/training-domain.jsonl") == plan["training_trace_sha256"]
torch.set_num_threads(1)
torch.set_num_interop_threads(1)
torch.use_deterministic_algorithms(True)
report = {"schema": "hcsn-width16-independent-audit-stage-v1", "stage": stage,
          "plan_sha256": sha(root / "plan.json"), "runner_sha256": sha(Path(__file__)),
          "python": sys.version, "torch": torch.__version__, "numpy": np.__version__, "mpmath": mp.__version__,
          "scientific_admission": "HOLD", "training_adequacy_established": False,
          "energy_joules": None, "source_before": sources}
started = time.perf_counter()
try:
    if stage == "export":
        config = plan["model"]
        model = CoreStudyModel(**config, hcsn_grid=plan["grid"])
        checkpoint = torch.load(root / "training-probe/after.pt", weights_only=True)
        model.load_state_dict(checkpoint["model"])
        model.eval()
        wrapper_before = model_digest(model)
        network = model.core.network
        seen = {}
        def hook(module, arguments, keywords, result):
            seen["result"] = result
        handle = network.register_forward_hook(hook, with_kwargs=True)
        manifest = json.loads((root / "data/data-manifest.json").read_text())
        assert sha(root / "data/data-manifest.json") == plan["data_manifest_sha256"]
        laws, traces = {}, []
        for episode_id in plan["episodes"]:
            path = root / "data" / f"{episode_id}.json"
            expected = next(r["sha256"] for r in manifest["episodes"] if r["id"] == episode_id)
            assert sha(path) == expected
            episode = json.loads(path.read_text())
            assert episode["partition"] == "train" and episode["sequence"][0] == "A"
            x, dt = [torch.tensor(episode[name], dtype=torch.float64)[None] for name in ("x", "dt")]
            trace_path = root / f"evaluation-{episode_id}.jsonl"
            recorder = TrainingDomainRecorder(trace_path, data_sha256=expected,
                configuration_sha256=report["plan_sha256"], max_records=512, max_bytes=32 * 1024 * 1024)
            model.core.recorder = recorder
            model.core.record_context = {"episode_id": episode_id, "update_index": 2}
            before = time.perf_counter()
            with torch.no_grad():
                predictions = model(x, dt)
            recorder.close()
            output = seen.pop("result")
            _, visits, footer, digest = read_trace(trace_path)
            assert len(visits) == len(episode["y"]) and not footer["truncated"]
            rows = []
            for fixture in plan["finite_fixtures"]:
                if fixture["episode"] != episode_id:
                    continue
                position, count = fixture["position"], fixture["intervals"]
                probability = output.trace[position][0]["probability"][0].detach()
                durations = episode["dt"][position + 1:position + 1 + count]
                key = f"{episode_id}:{position}:{count}"
                laws[key] = {"probability": probability, "durations": durations,
                    "grid": asdict(network.layers[0].grid), "operator": network.layers[0].operator.configuration(),
                    "parameters": dict(zip(("log_boundary", "mu", "sigma", "absolute_reset", "discount"),
                                      (float(v.detach()) for v in network.layers[0].physics().tensors())))}
                rows.append(key)
            traces.append({"episode": episode_id, "sha256": digest, "records": len(visits),
                           "truncated": footer["truncated"], "wall_seconds": time.perf_counter() - before,
                           "network_model_sha256": model_digest(network), "fixture_laws": rows,
                           "prediction_shape": list(predictions.shape)})
        handle.remove()
        model.core.recorder = None
        torch.save(laws, root / "final-starting-laws.pt")
        report.update(status="completed_export", traces=traces,
                      wrapper_sha256=wrapper_before, wrapper_unchanged=wrapper_before == model_digest(model),
                      common_frontend_sha256=tensor_digest(model.frontend), common_head_sha256=tensor_digest(model.head),
                      laws_sha256=sha(root / "final-starting-laws.pt"),
                      cache_receipts=[layer.operator.cache_receipt() for layer in network.layers])
    elif stage == "training-audit" or stage.startswith("eval-"):
        trace_path = root / "training-probe/training-domain.jsonl" if stage == "training-audit" else root / f"evaluation-{stage[5:]}.jsonl"
        before = time.perf_counter()
        audit = audit_trace(trace_path, max_records=4096)
        path = root / f"{stage}.json"
        path.write_text(json.dumps(audit, indent=2, allow_nan=False) + "\n")
        failures = [{"index": r["index"], "dt": r.get("dt"), "status": r["status"],
                     "scaled_value_error": r.get("maximum_scaled_value_error"), "error": r.get("detail")}
                    for r in audit["visits"] if r["status"] != "passed"]
        report.update(status="completed_audit", audit_status=audit["status"],
                      audit_sha256=sha(path), trace_sha256=sha(trace_path),
                      audited_records=audit["audited_records"], complete_retained_coverage=audit["complete_retained_coverage"],
                      source_matches_trace=audit["source_matches_trace"], failed_visits=failures,
                      maximum_scaled_value_error=max(r.get("maximum_scaled_value_error", 0) for r in audit["visits"]),
                      maximum_mass_error=max(r.get("maximum_mass_error", 0) for r in audit["visits"]))
    else:
        index = int(stage.split("-")[1])
        export = json.loads((root / "export-receipt.json").read_text())
        assert sha(root / "final-starting-laws.pt") == export["laws_sha256"]
        fixture = plan["finite_fixtures"][index]
        key = f'{fixture["episode"]}:{fixture["position"]}:{fixture["intervals"]}'
        inputs = torch.load(root / "final-starting-laws.pt", weights_only=True)[key]
        grid = GridSpec(**inputs["grid"])
        params = PhysicalParameters(*(torch.tensor(inputs["parameters"][name], dtype=torch.float64)
            for name in ("log_boundary", "mu", "sigma", "absolute_reset", "discount")))
        # This frozen source's default oracle is valid only for the exact
        # retained regenerative rewards/configuration; assert that identity.
        from qualification.hcsn_differentiable.operator import DifferentiableDistributionOperator
        assert DifferentiableDistributionOperator(grid).configuration() == inputs["operator"]
        result = audit_finite_schedule(inputs["probability"], grid, params, inputs["durations"], reference_order=plan["reference_order"])
        retained = {**inputs, "probability": inputs["probability"].tolist()}
        result.update(inputs=retained, inputs_sha256=hashlib.sha256(json.dumps(retained, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), fixture=fixture)
        path = root / f"{stage}.json"
        path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
        report.update(status="completed_finite_fixture", fixture=fixture, fixture_status=result["status"],
                      result_sha256=sha(path), scaled_errors=result["scaled_errors"],
                      projected=result["projected"], reference=result["reference"], mass_residual=result["mass_residual"],
                      reference_refinement_delta=result["reference_refinement_delta"])
except Exception:
    report.update(status="error", detail=traceback.format_exc())
    print(report["detail"], flush=True)
finally:
    report["wall_seconds"] = time.perf_counter() - started
    report["maximum_resident_kib_linux"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report["source_after"] = {str(p.relative_to(root / "source")): sha(p) for p in (root / "source").rglob("*.py")}
    report["source_unchanged"] = report["source_after"] == sources
    result_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: report[k] for k in ("stage", "status", "wall_seconds", "source_unchanged")}), flush=True)
raise SystemExit(0 if report["status"].startswith("completed") else 1)
