"""Score a complete saved worker using the unchanged frozen scoring AST."""

import argparse
import ast
from datetime import datetime, timezone
import gzip
import hashlib
import inspect
import json
from pathlib import Path
import time
import zipfile

from .. import runtime_study as study
from ..freeze import verify
from .resume_runtime import dataset_identity, sha, write


def recover(root, seed=2017):
    root = Path(root).resolve()
    frozen = verify(root)
    if seed != 2017:
        raise ValueError("Only the verified complete interrupted worker 2017 is authorized")
    directory = root / "runtime_confirmation" / f"seed_{seed}"
    output = root / "runtime_recovery_v2"
    output.mkdir(exist_ok=True)
    receipt_path = output / f"SCORING_RECOVERY_seed_{seed}.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if not receipt["passed"] or sha(directory / "ROWS.json.gz") != receipt["scored_rows_sha256"] or sha(directory / "SUMMARY.json") != receipt["summary_sha256"]:
            raise ValueError("Existing completed scoring recovery changed")
        if (not receipt["original_inputs_unchanged"] or not receipt["reused_in_completed_cohort"]
                or receipt["reexecuted_policy"]
                or any(sha(directory / name) != value for name, value in receipt["inputs_sha256"].items())):
            raise ValueError("Existing scoring recovery no longer binds its unchanged original worker")
        return receipt
    if (directory / "ROWS.json.gz").exists() or (directory / "SUMMARY.json").exists():
        raise FileExistsError("Preserve and review incomplete scoring output before retrying; never overwrite")
    originals = {path.name: sha(path) for path in directory.iterdir() if path.is_file()}
    expected = {"PUBLIC_ROWS.json.gz": "c15e8b4b2a433fabb49b73b472bc1cbda9b961fed990a9ba9c47f1dc43f12bc5",
                "WORKER.json": "19f5ccdbc1698e020609ec0032114b55642cc7bd49f5806a0c5475dbfd73c0c1",
                "execution.zip": "281e8500b0cb87d7fbaa718b4c3528160084135ab72300c29a962d7ae241d7fb"}
    if any(originals.get(name) != value for name, value in expected.items()):
        raise ValueError("Complete worker differs from the observed immutable interrupted worker")
    worker = json.loads((directory / "WORKER.json").read_text())
    manifest = json.loads((directory / "execution.manifest.json").read_text())["files"]
    if originals["execution.zip"] != worker["archive"]["sha256"] or originals["execution.manifest.json"] != worker["archive"]["manifest_sha256"]:
        raise ValueError("Complete worker archive binding failed")
    with zipfile.ZipFile(directory / "execution.zip") as archive:
        if len(archive.namelist()) != len(manifest) or set(archive.namelist()) != set(manifest) or len(manifest) != worker["archive"]["verified_files"]:
            raise ValueError("Complete worker archive inventory failed")
    with gzip.open(directory / "PUBLIC_ROWS.json.gz", "rt") as stream:
        public_rows = json.load(stream)
    required = {(f"feedback4:confirmation:{seed}:{i}", arm) for i in range(study.REGISTRATION["confirmation_rows"]) for arm in study.ARMS}
    if len(public_rows) != len(required) or {(row["case"], row["arm"]) for row in public_rows} != required:
        raise ValueError("Complete worker must contain every original registered case and arm")
    if any("target" in row or "utility" in row or "squared_error" in row for row in public_rows):
        raise ValueError("Saved worker rows must be the original unscored public output")
    if time.perf_counter_ns() <= max(row["final_readback_ns"] for row in public_rows):
        raise ValueError("Monotonic clock domain changed; do not synthesize scoring timestamps")
    del public_rows, manifest
    original_incident = json.loads((root / "RUNTIME_INTERRUPTION.json").read_text())
    attempt = next(item for item in original_incident["attempts"] if item["seed"] == seed and item["phase"] == "confirm")
    identity_path = output / f"DATASET_IDENTITY_seed_{seed}.json"
    if not identity_path.exists():
        identity = dataset_identity(root, seed, attempt, output)
    else:
        identity = {"path": str(identity_path.relative_to(root)), "sha256": sha(identity_path)}
        checked = json.loads(identity_path.read_text())
        if not checked["passed"] or any(sha(directory / name) != item["recovered_sha256"] for name, item in checked["comparisons"].items()):
            raise ValueError("Saved cohort identity receipt no longer matches")
    function = ast.parse(inspect.getsource(study.confirm_seed)).body[0]
    begin = next(i for i, node in enumerate(function.body) if isinstance(node, ast.With) and "PUBLIC_ROWS.json.gz" in ast.unparse(node))
    end = next(i for i, node in enumerate(function.body) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "summary" for target in node.targets))
    selected = function.body[begin:end + 1]
    scoring_ast = ast.Module(body=selected, type_ignores=[])
    ast_sha = hashlib.sha256(ast.dump(scoring_ast, include_attributes=False).encode()).hexdigest()
    source_relative = str(Path(study.__file__).resolve().relative_to(Path(study.__file__).resolve().parents[3]))
    if sha(study.__file__) != frozen["sources_sha256"][source_relative]:
        raise ValueError("Scoring source is not the frozen study source")
    started_path = output / f"SCORING_STARTED_seed_{seed}.json"
    write(started_path, {"schema": "hepta.round4.saved-worker-scoring-start.v1", "started_utc": datetime.now(timezone.utc).isoformat(),
                         "inputs_sha256": originals, "frozen_source": source_relative, "frozen_source_sha256": sha(study.__file__),
                         "scoring_ast_sha256": ast_sha, "reused_in_completed_cohort": True, "reexecuted_policy": False,
                         "original_outer_wall_ns": None, "original_outer_cpu_ns": None})
    # Exact trusted source nodes: saved PUBLIC_ROWS load, frozen scoring loop,
    # scored-row write, saved WORKER load, and frozen per-arm aggregation.
    # No dataset generation, fitting, subprocess, native call, or policy loop.
    context = dict(vars(study))
    context.update(output=directory, data=study.load_data(directory / "DATA.npz"))
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    exec(compile(scoring_ast, study.__file__, "exec"), context, context)
    scoring_cost = {"wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
                    "scope": "Frozen scoring and aggregation of the already completed saved worker only", "native_requests": 0, "native_ticks": 0}
    if any(row["score_started_ns"] <= row["final_readback_ns"] for row in context["rows"]):
        raise ValueError("Actual recovered score timestamps violate the frozen ordering check")
    report = {"seed": seed, "independent_trajectories": study.REGISTRATION["confirmation_rows"], "executions": len(context["rows"]),
              "summary": context["summary"], "worker": worker,
              "model_file_sha256": sha(root / "runtime_prepared" / f"seed_{seed}" / "MODELS.json"),
              "data_sha256": originals["DATA.npz"], "rows_sha256": sha(directory / "ROWS.json.gz"),
              "wall_ns": None, "cpu_ns": None, "outer_confirmation_invocation_interrupted": True,
              "outer_confirmation_unknown_costs_must_not_be_zero": True, "scoring_recovery": scoring_cost,
              "reused_in_completed_cohort": True, "reexecuted_policy": False,
              "target_only_in_scoring_process_after_final_readback": True, "same_uid_hostile_isolation_claimed": False}
    write(directory / "SUMMARY.json", report)
    unchanged = all(sha(directory / name) == value for name, value in originals.items())
    verify(root)
    receipt = {"schema": "hepta.round4.completed-worker-scoring-recovery.v1", "seed": seed, "passed": unchanged,
               "inputs_sha256": originals, "original_inputs_unchanged": unchanged, "dataset_identity": identity,
               "frozen_source_sha256": sha(study.__file__), "scoring_ast_sha256": ast_sha,
               "scored_rows_sha256": sha(directory / "ROWS.json.gz"), "summary_sha256": sha(directory / "SUMMARY.json"),
               "original_worker_costs": {key: worker[key] for key in ("wall_ns", "cpu_ns", "native")},
               "original_outer_wall_ns": None, "original_outer_cpu_ns": None, "original_outer_exit_code": None,
               "scoring_recovery": scoring_cost, "reused_in_completed_cohort": True, "reexecuted_policy": False,
               "count_completed_worker_native_cost_once_in_formal_cohort": True, "native_energy": None, "financial_cost": None}
    write(receipt_path, receipt)
    if not unchanged:
        raise ValueError("Original completed worker input changed during scoring recovery")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=2017)
    args = parser.parse_args()
    print(json.dumps(recover(args.run_dir, args.seed), sort_keys=True))
