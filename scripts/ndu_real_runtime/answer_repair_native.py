"""Pinned answer-weight-only native fitting; writes a separate research candidate."""

import argparse
import hashlib
import types
import io
import json
from pathlib import Path
import resource
import sys
import time


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, expected):
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        raise ValueError("Pinned input must be a regular file")
    raw = p.read_bytes()
    if sha(raw) != expected:
        raise ValueError("Pinned input identity differs")
    return raw


def write_once(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with Path(path).open("xb") as stream:
        stream.write(raw)
    return sha(raw)


def execute(request_path, expected_request, output):
    started, cpu = time.perf_counter(), time.process_time()
    request_raw = read(request_path, expected_request)
    request = json.loads(request_raw)
    runner_sha = sha(Path(__file__).read_bytes())
    if request.get("native_runner_sha256") != runner_sha:
        raise ValueError("Native runner source identity differs")
    plan = request["plan"]
    collection = json.loads(
        read(request["collection_plan"], request["collection_sha256"])
    )
    for pin in collection["source_pins"]:
        read(pin["path"], pin["sha256"])
    config = collection["execution_config"]
    inventory = sha(json.dumps(collection["source_pins"], sort_keys=True).encode())
    if inventory != plan["source_inventory_sha256"]:
        raise ValueError("Repair source inventory differs")
    read(
        Path(config["scripts_root"]) / "ndu_real_materials/evaluator.py",
        plan["normalizer_sha256"],
    )
    records = read(request["records"], plan["fit_records_sha256"])
    base = read(request["weights"], plan["base_weights_sha256"])
    core_raw = read(request["repair_core"], request["repair_core_sha256"])
    core = types.ModuleType("pinned_answer_repair")
    core.__file__ = request["repair_core"]
    exec(compile(core_raw, request["repair_core"], "exec"), core.__dict__)
    core.validate_plan(plan)
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=False)
    sys.path[:0] = [
        config["pillow_path"],
        config["scripts_root"],
        config["repository_root"],
    ]
    import torch
    from ndu_real_runtime.neural import ReceiptPortfolioModel
    from ndu_real_runtime.training import validate_record
    from ndu_real_materials.evaluator import canonical

    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    model = ReceiptPortfolioModel("ordinary").float().eval()
    model.load_state_dict(
        torch.load(io.BytesIO(base), map_location="cpu", weights_only=True), strict=True
    )
    frozen = {k: v.detach().clone() for k, v in model.state_dict().items()}
    observed, rows = [], []
    handle = model.answer.register_forward_pre_hook(
        lambda module, inputs: observed.append(inputs[0].detach().cpu().numpy().copy())
    )
    try:
        for number, line in enumerate(records.splitlines(), 1):
            if number > 10000 or len(line) > 2 * 1024**2:
                raise ValueError("Original row bound exceeded")
            row = validate_record(json.loads(line))
            if (
                row["source_group"] not in plan["original_fit_sources"]
                or row["split"] != "train"
            ):
                raise ValueError("Original row is outside fitting sources")
            with torch.inference_mode():
                model.public_state_step(
                    torch.tensor(row["candidate_features"], dtype=torch.float32),
                    row["public_metadata"],
                    memory=None,
                    memory_mode="reset",
                )
            expected = canonical(row["expected_text"], row["reference_field"])
            if expected is None:
                raise ValueError("Reference outside pinned normalizer")
            positives = [
                i
                for i, c in enumerate(row["candidate_metadata"])
                if canonical(c["text"], row["reference_field"]) == expected
            ]
            rows.append(
                dict(
                    source_id=row["source_group"],
                    observation_id=row["record_id"],
                    role="train",
                    encoded=observed.pop().tolist(),
                    positives=positives,
                )
            )
    finally:
        handle.remove()
    initial = frozen["answer.weight"].reshape(-1).double().tolist()
    head = core.fit(rows, plan, initial, float(frozen["answer.bias"].item()))
    candidate = dict(frozen)
    candidate["answer.weight"] = torch.tensor(
        head["weights"], dtype=frozen["answer.weight"].dtype
    ).reshape_as(frozen["answer.weight"])
    model.load_state_dict(candidate, strict=True)
    changed = [
        k for k, v in frozen.items() if not torch.equal(v, model.state_dict()[k])
    ]
    if set(changed) - {"answer.weight"}:
        raise ValueError("A non-answer parameter changed")
    disagreements = sum(
        int(
            torch.argmax(
                model.answer(torch.tensor(r["encoded"], dtype=torch.float32)).squeeze(
                    -1
                )
            ).item()
        )
        != core.select(head, r["encoded"])
        for r in rows
    )
    if disagreements:
        raise ValueError("Export dtype changed candidate selection")
    weights = destination / "candidate-weights.pt"
    with weights.open("xb") as stream:
        torch.save(model.state_dict(), stream)
    restored = torch.load(weights, map_location="cpu", weights_only=True)
    if any(not torch.equal(v, restored[k]) for k, v in model.state_dict().items()):
        raise ValueError("Cold reload differs")
    head_sha = write_once(destination / "head.json", head)
    write_once(destination / "REQUEST.json", request)
    unique = core.validate_rows(rows, set(plan["original_fit_sources"]))
    for pin in collection["source_pins"]:
        read(pin["path"], pin["sha256"])
    read(request["repair_core"], request["repair_core_sha256"])
    read(__file__, runner_sha)
    result = dict(
        schema="ndu.ctrl.answer-repair-native-result.v1",
        status="completed",
        request_sha256=expected_request,
        native_runner_sha256=runner_sha,
        repair_core_sha256=sha(core_raw),
        base_weights_sha256=sha(base),
        candidate_weights_sha256=sha(weights.read_bytes()),
        head_sha256=head_sha,
        source_files_verified=len(collection["source_pins"]),
        fit_sources=len(plan["original_fit_sources"]),
        original_rows=len(rows),
        baseline_fitting=core.measure(unique, initial),
        candidate_fitting=head["fitting"],
        tuning_trials=head["trials"],
        selected_trial=head["selected_trial"],
        changed_parameter_names=changed,
        cold_reload_equal=True,
        numpy_export_selection_disagreements=disagreements,
        torch=str(torch.__version__),
        device="cpu",
        wall_seconds=time.perf_counter() - started,
        cpu_seconds=time.process_time() - cpu,
        max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        duration_scope="worker includes import/read/encode/tune/refit/export; excludes launcher and final receipt serialization",
        future_labels_opened=False,
        independent_future_evaluation_performed=False,
        provider_charges=None,
        energy_joules=None,
        production_update="no-update",
    )
    write_once(destination / "RESULT.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--expected-request-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    return execute(args.request, args.expected_request_sha256, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
