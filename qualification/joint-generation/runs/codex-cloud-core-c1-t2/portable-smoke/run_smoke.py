"""One artifact-only external-input smoke; no experiment data or scoring."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
RUN = HERE.parent
ROOT = RUN.parents[1]
sys.path.insert(0, str(ROOT))
START_CPU, START_WALL = time.process_time_ns(), time.perf_counter_ns()
START_UTC = datetime.datetime.now(datetime.timezone.utc).isoformat()
FORBIDDEN = {"dataset", "decoded_observations", "outcome_table", "decoded_metrics",
             "prepare_decoded_observer", "metrics_from_observations", "outcome_from_observations",
             "measure", "run_evaluation", "train", "batch_validation", "score"}
ROOT_PREFIX = str(ROOT) + os.sep
GUARD = {"project_call_events": 0, "forbidden_calls": []}


def guarded_call(frame, event, arg):
    if event == "call" and frame.f_code.co_filename.startswith(ROOT_PREFIX):
        GUARD["project_call_events"] += 1
        if frame.f_code.co_name in FORBIDDEN:
            GUARD["forbidden_calls"].append(frame.f_code.co_name)
            raise AssertionError("Artifact smoke called forbidden data/scoring function")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def original_stats():
    return {str(path.relative_to(RUN)): [path.stat().st_size, path.stat().st_mtime_ns]
            for path in RUN.rglob("*") if path.is_file() and not path.is_relative_to(HERE)}


def main():
    # Guard before imports: data modules may define/import functions, never call them.
    sys.setprofile(guarded_call)
    import numpy as np
    import PIL
    from PIL import Image
    from contracts import RunSession
    from independent.serve import export_bundle, infer, load_bundle

    prior = original_stats()
    seals = [RUN / "test-opened.json", ROOT / "core_confirmation/core-c1-test-opened.json"]
    sealed_hashes = {str(path.relative_to(ROOT)): sha(path) for path in seals}
    selection_path = RUN / "selection.json"
    selected = json.loads(selection_path.read_text())
    row = next(item for item in selected["selected"] if item["system"] == "ndu" and item["seed"] == 11)
    assert selected["selection_ready"] is True
    assert row["mode"] == "full" and row["controller_file"] is None
    selected_hash = sha(selection_path)
    artifact = export_bundle(RUN, "ndu", 11, HERE / "bundle")
    first_load, second_load = load_bundle(HERE / "bundle"), load_bundle(HERE / "bundle")
    assert first_load.digest == second_load.digest == artifact
    assert first_load.model is not second_load.model
    assert first_load.model.digest() == second_load.model.digest() == row["model_digest"]
    assert first_load.manifest["mode"] == "full"

    # Handwritten external RGB, without renderer, dataset, labels, or targets.
    rgb = np.full((8, 8, 3), .03, dtype=np.float32)
    rgb[2:6, 1:4, 0] = .85
    rgb[2:6, 1:4, 1:] = .04
    Image.fromarray(np.rint(rgb * 255).astype(np.uint8)).save(HERE / "external-input.png", format="PNG")
    timing = {"clock_id": "external-manual:1", "sync_group": "external-manual:1",
              "start_ns": 1, "end_ns": 2}
    request = {"schema": "hepta.joint-generation.media-envelope.v1",
        "objective_id": "scene-transform-v1", "run_id": "core-c1-t2:portable-smoke:ndu11",
        "artifact_sha256": artifact, "deadline_ns": time.monotonic_ns() + 600 * 10**9,
        "budget": {"compute_units": 100000, "input_bytes": 8192, "output_bytes": 8192},
        "decoding": {"mode": "sample", "seed": 42}, "outputs": ["text", "image"],
        "sync_tolerance_ns": 0,
        "streams": [{"stream_id": "text:1", "modality": "text", "timing": timing,
            "payload": {"encoding": "utf-8", "text": "blue cross right"}},
            {"stream_id": "image:1", "modality": "image", "timing": timing,
             "payload": {"dtype": "float32", "color_space": "RGB", "pixels": rgb.tolist()}}]}
    write(HERE / "request.json", request)
    first = infer(HERE / "bundle", request, HERE / "first")
    replay = infer(HERE / "bundle", request, HERE / "reloaded")
    identity = ("caption", "choices", "image_sha256", "model_digest", "bundle_digest", "spent", "mode")
    assert all(first[key] == replay[key] for key in identity)
    assert (HERE / "first/output.png").read_bytes() == (HERE / "reloaded/output.png").read_bytes()
    assert first["selection_ready"] is True and first["mode"] == "full"
    assert first["route"]["per_row"]["full_forwards"] == [1]
    assert first["route"]["per_row"]["low_forwards"] == [0]
    assert first["spent"]["controller"] == 0
    with Image.open(HERE / "first/output.png") as image:
        image.verify()
    with Image.open(HERE / "first/output.png") as image:
        png_metadata = {"format": image.format, "mode": image.mode, "size": list(image.size)}
    assert png_metadata == {"format": "PNG", "mode": "RGB", "size": [8, 8]}

    checkpoint = json.loads((HERE / "first/checkpoint.json").read_text())
    restored = RunSession.restore(checkpoint, expected_artifact_sha256=artifact, now_ns=time.monotonic_ns())
    assert restored.prefix("text") == first["caption"].encode()
    assert restored.prefix("image") == (HERE / "first/output.png").read_bytes()
    assert restored.spent == first["spent"]
    assert checkpoint == json.loads((HERE / "reloaded/checkpoint.json").read_text())
    write(HERE / "restored-checkpoint.json", restored.checkpoint())
    assert prior == original_stats(), "An existing run artifact was changed"
    assert selected_hash == sha(selection_path)
    assert sealed_hashes == {str(path.relative_to(ROOT)): sha(path) for path in seals}
    assert GUARD["forbidden_calls"] == []

    source_names = ["model.py", "data.py", "contracts.py", "multimodal_contract.py", "serve.py",
        "independent/serve.py", "independent/evaluation.py", "independent/inference.py",
        "independent/native.py", "independent/accounting.py", "independent/data_v2.py"]
    loaded_sources = {name: sha(ROOT / name) for name in source_names}
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    sys.setprofile(None)
    evidence = {"schema": "hepta.joint-generation.portable-artifact-smoke.v1",
        "experiment_id": "core-c1", "source_run": str(RUN.relative_to(ROOT)),
        "system": "ndu", "model_seed": 11, "selected_policy": "always_full",
        "selection_ready": True, "formal_qualified": False, "formal_exit_code": 1,
        "formal_status_source": "parent-confirmed sealed core-c1 result; no formal metrics or test inputs read",
        "scope": "one handcrafted external RGB/instruction, actual native generation and exact artifact reload/checkpoint replay; no qualification or accuracy claim",
        "caption": first["caption"], "choices": first["choices"], "png": png_metadata,
        "output_png_sha256": first["image_sha256"], "bundle_digest": artifact,
        "selected_model_sha256": row["model_sha256"], "selected_model_digest": row["model_digest"],
        "native_sha256": selected["native_library_sha256"], "selection_sha256": selected_hash,
        "model_file": row["model_file"], "current_source_commit": revision,
        "frozen_model_source_commit": selected["source_commit"], "plan_sha256": selected["plan_sha256"],
        "source_sha256": loaded_sources, "worker_sha256": sha(__file__),
        "original_run_file_count": len(prior), "original_run_file_stats_unchanged": True,
        "sealed_marker_sha256": sealed_hashes, "sealed_markers_unchanged": True,
        "dataset_and_external_observer_call_guard": GUARD,
        "guarded_during_import_and_serving": True, "dataset_constructed": False,
        "external_observer_called": False, "evaluation_called": False,
        "exact_reload_output_and_checkpoint": True, "checkpoint_restored": True,
        "spent": first["spent"], "route": first["route"],
        "first_infer_cpu_ns": first["cpu_ns"], "reloaded_infer_cpu_ns": replay["cpu_ns"],
        "started_utc": START_UTC, "finished_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "worker_cpu_ns_before_report_persistence": time.process_time_ns() - START_CPU,
        "worker_wall_ns_before_report_persistence": time.perf_counter_ns() - START_WALL,
        "versions": {"python": platform.python_version(), "numpy": np.__version__, "pillow": PIL.__version__,
            "system": platform.system(), "machine": platform.machine(),
            "frozen_native_compiler": selected["common"]["native_compile"]["compiler_version"]},
        "thread_environment": {key: os.environ.get(key) for key in
            ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")},
        "command": "OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 python runs/codex-cloud-core-c1-t2/portable-smoke/run_smoke.py",
        "worker_path": str(Path(__file__).relative_to(ROOT))}
    write(HERE / "report.json", evidence)
    files = {str(path.relative_to(HERE)): sha(path) for path in HERE.rglob("*") if path.is_file()}
    write(HERE / "checksums.json", files)
    print(json.dumps({key: evidence[key] for key in ("selection_ready", "formal_qualified", "caption",
          "output_png_sha256", "exact_reload_output_and_checkpoint", "checkpoint_restored")}, sort_keys=True))


if __name__ == "__main__":
    main()
