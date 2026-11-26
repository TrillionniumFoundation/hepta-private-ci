"""Cold numeric research invocation. No labels, training, owner or token adapter."""
import argparse
import math
from pathlib import Path
import time

from profile_io import canonical, digest, fields, parse, read_named, require, sha, write_new
from small_hcsn_profile import MAX_BATCH, MAX_STEPS, load_profile

TASK_SCHEMA = "hepta.smallhcsn.numeric-task.v1"
MAX_RESULT_BYTES = 16 * 1024 * 1024


def validate_task(task):
    fields(task, ("schema", "task_id", "profile_sha256", "candidate_sha256", "x", "initial"),
           "label-free numeric task")
    require(task["schema"] == TASK_SCHEMA and isinstance(task["task_id"], str)
            and 1 <= len(task["task_id"]) <= 128, "numeric task identity")
    digest(task["profile_sha256"])
    digest(task["candidate_sha256"])
    x = task["x"]
    require(isinstance(x, list) and 1 <= len(x) <= MAX_STEPS, "numeric time bound")
    require(isinstance(x[0], list) and 1 <= len(x[0]) <= MAX_BATCH, "numeric batch bound")
    batch = len(x[0])
    for tick in x:
        require(isinstance(tick, list) and len(tick) == batch, "ragged numeric batch")
        for row in tick:
            require(isinstance(row, list) and len(row) == 6
                    and all(type(value) in (int, float) and math.isfinite(value) for value in row),
                    "six finite numeric channels required")
    initial = task["initial"]
    require(isinstance(initial, dict), "numeric initial condition")
    if initial.get("kind") == "margin":
        fields(initial, ("kind", "margin"), "initial margin")
        require(isinstance(initial["margin"], list) and len(initial["margin"]) == batch
                and all(type(value) in (int, float) and math.isfinite(value)
                        for value in initial["margin"]), "one finite margin per trajectory required")
    else:
        fields(initial, ("kind", "artifact"), "resumed physical state")
        require(initial["kind"] == "resume", "unsupported initial condition")
        fields(initial["artifact"], ("path", "bytes", "sha256"), "population artifact")
        digest(initial["artifact"]["sha256"])
    return batch


def run(manifest_path, expected_manifest_sha256, material_root, task_path,
        expected_task_sha256, state_root, output_dir):
    raw = read_named(task_path, expected_task_sha256, 1024 * 1024)
    task = parse(raw)
    batch = validate_task(task)  # Unknown target/label fields fail before any model import.
    require(task["profile_sha256"] == digest(expected_manifest_sha256), "task profile differs")
    profile = load_profile(manifest_path, expected_manifest_sha256, material_root)
    require(task["candidate_sha256"] == profile.candidate_sha256, "task candidate differs")
    torch = profile.torch
    x = torch.tensor(task["x"], dtype=torch.float64, device="cpu")
    if task["initial"]["kind"] == "margin":
        margin = torch.tensor(task["initial"]["margin"], dtype=torch.float64)[:, None]
        state = profile.initial_state(batch, margin)
    else:
        state = profile.load_state(task["initial"]["artifact"], state_root)
    require(state.density.shape[0] == batch, "resumed population batch differs")
    started = time.perf_counter()
    with torch.no_grad():
        logits, features, final_state = profile.forward(x, state)
    elapsed = time.perf_counter() - started
    output = Path(output_dir)
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    state_pin = profile.save_state(final_state, output / "population.pt")
    result = {
        "schema": "hepta.smallhcsn.numeric-result.v1", "scope": "research_numeric_inference",
        "task_id": task["task_id"], "task_sha256": sha(raw),
        "profile_sha256": profile.profile_sha256, "candidate_sha256": profile.candidate_sha256,
        "model_state_sha256": profile.model_state_sha256,
        "source_binding_sha256": profile.source_binding_sha256,
        "start_step": state.step, "end_step": final_state.step,
        "logits": logits.tolist(), "features": features.tolist(),
        "last_probabilities": logits[-1].softmax(-1).tolist(),
        "predicted_class_indices": logits[-1].argmax(-1).tolist(),
        "final_population_sha256": profile._population_identity(final_state),
        "population": state_pin, "wall_s": elapsed,
        "diagnostics_scope": "this_call_only", "chunk_diagnostics": dict(profile.model.last_diagnostics),
        "production_adoption": False, "real_cross_user_acceptance": False,
    }
    result_pin = write_new(output / "result.json", canonical(result) + b"\n", MAX_RESULT_BYTES)
    return result_pin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("profile", "profile-sha256", "material-root", "task", "task-sha256",
                 "state-root", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    result = run(args.profile, args.profile_sha256, args.material_root, args.task,
                 args.task_sha256, args.state_root, args.output)
    print(canonical(result).decode())


if __name__ == "__main__":
    main()
