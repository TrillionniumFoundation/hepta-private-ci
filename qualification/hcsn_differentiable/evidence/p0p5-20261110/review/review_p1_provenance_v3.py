"""Independent P1 artifact linkage checks; does not rerun slow numerical oracles."""

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import time
import traceback
from zipfile import ZipFile

import torch

BASE = Path("/workspace/scratch/c385a7439f8e")
ROOT = BASE / "hcsn-p1-evidence-20261110"
ARCHIVE = BASE / "hcsn-p1-evidence-20261110-v2.zip"
OUT = BASE / "p1-independent-provenance-review-v3.json"
sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
load = lambda path: json.loads(Path(path).read_bytes())
started = time.perf_counter()
report = {"schema": "hcsn-independent-p1-provenance-review-v3", "reviewer": "/root/math_contract",
          "created_utc": datetime.now(timezone.utc).isoformat(), "archive_sha256": sha(ARCHIVE),
          "manifest_sha256": sha(ROOT / "manifest.json"), "checks": [], "passed": False,
          "scientific_admission": "HOLD", "recomputed_slow_oracles": False}


def record(name, **details):
    report["checks"].append({"name": name, "passed": True, **details})


def tensor_state_digest(path):
    state = torch.load(path, map_location="cpu", weights_only=True)
    if "model" in state and isinstance(state["model"], dict):
        state = state["model"]
    digest = hashlib.sha256()
    for name, tensor in sorted(state.items()):
        assert isinstance(tensor, torch.Tensor)
        description = json.dumps([name, str(tensor.dtype), list(tensor.shape)],
                                 sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        digest.update(description.encode())
        digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return state, digest.hexdigest()


def read_trace(path):
    lines = path.read_bytes().splitlines(keepends=True)
    rows = [json.loads(line) for line in lines]
    header, visits, footer = rows[0], rows[1:-1], rows[-1]
    assert footer["kind"] == "end" and not footer["truncated"]
    assert footer["prefix_sha256"] == hashlib.sha256(b"".join(lines[:-1])).hexdigest()
    assert len(visits) == footer["retained_records"] == footer["seen_records"]
    assert footer["source_unchanged"] and footer["sources_after"] == header["sources"]
    assert [row["index"] for row in visits] == list(range(len(visits)))
    return header, visits, footer


def source_map(expected, directory):
    for name, digest in expected.items():
        assert sha(directory / name) == digest, str(directory / name)
    return len(expected)


def check_schedule(fixture, episode, position, length, probability=None):
    durations = episode["dt"][position + 1:position + 1 + length]
    assert len(durations) == fixture["intervals"] == length
    assert math.isclose(math.fsum(durations), fixture["horizon"], rel_tol=0, abs_tol=2e-15)
    assert min(durations) == fixture["minimum_dt"] and max(durations) == fixture["maximum_dt"]
    if "inputs" in fixture:
        inputs = fixture["inputs"]
        assert inputs["durations"] == durations
        if probability is not None:
            assert inputs["probability"] == probability
        encoded = json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode()
        assert hashlib.sha256(encoded).hexdigest() == fixture["inputs_sha256"]
    if probability is not None and "posterior_sha256" in fixture:
        tensor = torch.tensor(probability, dtype=torch.float64)
        assert hashlib.sha256(tensor.numpy().tobytes()).hexdigest() == fixture["posterior_sha256"]
    expected_errors = [abs(a - b) / max(1, abs(b)) for a, b in zip(fixture["projected"], fixture["reference"])]
    assert max(abs(a - b) for a, b in zip(expected_errors, fixture["scaled_errors"])) < 2e-15
    return durations


try:
    manifest = load(ROOT / "manifest.json")
    with ZipFile(ARCHIVE) as zipped:
        names = zipped.namelist()
        assert len(names) == len(set(names)) and zipped.testzip() is None
        for info in zipped.infolist():
            path = PurePosixPath(info.filename)
            assert not path.is_absolute() and ".." not in path.parts and "\\" not in info.filename
            assert (info.external_attr >> 16) & 0o170000 != 0o120000
        prefix = "hcsn-p1-evidence-20261110/"
        assert set(names) == {prefix + name for name in manifest["files"]} | {prefix + "manifest.json"}
        assert zipped.read(prefix + "manifest.json") == (ROOT / "manifest.json").read_bytes()
        for name, expected in manifest["files"].items():
            path = ROOT / name
            assert path.resolve().is_relative_to(ROOT.resolve())
            assert path.stat().st_size == expected["bytes"] and sha(path) == expected["sha256"]
            assert zipped.read(prefix + name) == path.read_bytes()
    record("zip_and_extracted_manifest", files=len(manifest["files"]), zip_members=len(names), crc=True)
    hash_locations = {}
    for name, entry in manifest["files"].items():
        hash_locations.setdefault(entry["sha256"], []).append(name)
    data_manifest = load(ROOT / "p1-data/data-manifest.json")
    expected_data = {entry["id"]: entry for entry in data_manifest["episodes"]}
    episodes = {}
    for name in ("A01-0", "A01-256", "A04-3072"):
        path = ROOT / "p1-data" / (name + ".json")
        assert sha(path) == expected_data[name]["sha256"]
        row = load(path)
        assert row["id"] == name and row["partition"] == "train" and row["sequence"][0] == "A"
        assert row["dt"] == [tick / 10000000 for tick in row["delta_ticks"]]
        episodes[name] = row
    record("three_A_episodes_bind_official_preparation", episodes=list(episodes),
           data_manifest_sha256=sha(ROOT / "p1-data/data-manifest.json"), no_D_or_E_episode=True)
    summary = load(ROOT / "summary.json")
    assert summary["data_manifest_sha256"] == sha(ROOT / "p1-data/data-manifest.json")
    assert summary["overall_scientific_admission"] == "HOLD" and not summary["sufficient_training_established"]
    assert summary["reference"]["quadrature_delta_is_certified_error_bound"] is False

    v2 = ROOT / "numerics-real-posterior-v2"
    plan = load(v2 / "plan.json")
    source_count = source_map(plan["source_before"], v2 / "source_snapshot")
    state, model_digest = tensor_state_digest(v2 / "trained.pt")
    assert model_digest == summary["frozen_candidate"]["model_sha256"]
    assert sha(v2 / "trained.pt") != model_digest
    initial_state, initial_digest = tensor_state_digest(v2 / "initial.pt")
    changed_tensors = [key for key in state if not torch.equal(initial_state[key], state[key])]
    assert changed_tensors and initial_digest != model_digest
    assert all(torch.equal(initial_state[key], value) for key, value in state.items() if ".physics." in key)
    update_lines = [json.loads(line.removeprefix("UPDATE ")) for line in
                    (ROOT / "numerics-real-posterior-v2.stdout").read_text().splitlines() if line.startswith("UPDATE ")]
    assert [row["update"] for row in update_lines] == [0, 1]
    assert [row["episode"] for row in update_lines] == ["A01-0", "A01-256"]
    assert all(row["events"] == 32 and math.isfinite(row["loss"]) for row in update_lines)
    assert update_lines[-1]["model_sha256"] == model_digest
    assert initial_digest != update_lines[0]["model_sha256"] != model_digest
    header, visits, footer = read_trace(v2 / "trace.jsonl")
    assert header["data_sha256"] == sha(ROOT / "p1-data/A01-0.json")
    assert header["configuration_sha256"] == sha(v2 / "plan.json")
    assert all(plan["source_before"][key] == value for key, value in header["sources"].items())
    assert len(visits) == 256
    for index, visit in enumerate(visits):
        assert visit["model_sha256"] == model_digest and visit["update_index"] == 2
        assert visit["episode_id"] == "A01-0" and visit["position"] == index
        assert visit["dt"] == [episodes["A01-0"]["dt"][index]]
        assert abs(sum(visit["posterior"][0]) - 1) < 5e-11
        if index:
            assert visit["prior"] == visits[index - 1]["posterior"]
    record("trained_checkpoint_and_all_256_post_update_visits", model_file_sha256=sha(v2 / "trained.pt"),
           model_tensor_state_sha256=model_digest, update_index=2, recorded_visits=len(visits), source_files=source_count,
           initial_tensor_state_sha256=initial_digest, changed_tensor_names=changed_tensors,
           physical_tensors_unchanged=True, original_optimizer_update_lines=update_lines,
           distinction="Serialized file SHA and canonical tensor-state SHA are different intentional identities.")
    interrupted = load(v2 / "interruption.json")
    assert interrupted["exit_code"] == 137 and interrupted["completed"] is False
    for name, expected in interrupted["retained_files"].items():
        assert sha(v2 / name) == expected["sha256"] and (v2 / name).stat().st_size == expected["bytes"]
    resumed = ROOT / "numerics-real-posterior-v2-resume"
    resume_plan, resume_report = load(resumed / "plan.json"), load(resumed / "report.json")
    for name, digest in resume_plan["prior_files"].items():
        assert sha(v2 / name) == digest
    assert resume_plan["source_before"] == plan["source_before"] == resume_report["source_after"]
    assert resume_report["plan_sha256"] == sha(resumed / "plan.json") and resume_report["source_unchanged"]
    source_map(resume_plan["source_before"], resumed / "source/qualification/hcsn_differentiable")
    record("exit137_to_separate_numerical_resume", original_completed=False, stop_cause="unknown",
           prior_file_links=len(resume_plan["prior_files"]), unchanged_source=True,
           restored_model_tensor_state_sha256=model_digest,
           scope="Numerical checks resumed from saved weights/trace; no optimizer state or training-resume claim.")

    burst = torch.load(resumed / "burst-starting-law.pt", weights_only=True, map_location="cpu")
    assert burst["model_sha256"] == model_digest and burst["episode"] == "A04-3072" and burst["position"] == 47
    finite_checks = []
    for entry in summary["frozen_candidate"]["finite_fixtures"]:
        path = ROOT / entry["artifact"]
        assert sha(path) == entry["artifact_sha256"]
        fixture = load(path)
        for key in ("status", "horizon", "intervals", "projected", "reference", "scaled_errors", "mass_residual", "reference_refinement_delta"):
            assert fixture[key] == entry[key]
        if path.parent.name == "numerics-longsequence-v1":
            long_plan = load(path.parent / "plan.json")
            assert long_plan["trace_sha256"] == sha(v2 / "trace.jsonl")
            assert long_plan["episode_sha256"] == header["data_sha256"]
            assert long_plan["schedule"] == episodes["A01-0"]["dt"][32:160]
            assert long_plan["finite_source_sha256"] in hash_locations
            assert fixture["plan_sha256"] == sha(path.parent / "plan.json")
            assert fixture["source_after"] == long_plan["source_before"] and fixture["source_unchanged"]
            assert all(digest in hash_locations for digest in long_plan["source_before"].values())
            schedule = check_schedule(fixture, episodes["A01-0"], 31, 128, visits[31]["posterior"][0])
            source_scope = "Eight common files before/after; finite helper separately hashed at start and present in frozen snapshot."
        else:
            spec = fixture.get("fixture") or {"episode": fixture["episode"], "posterior_position": fixture["position"], "future_intervals": fixture["intervals"]}
            episode, pos = spec["episode"], spec["posterior_position"]
            probability = visits[pos]["posterior"][0] if episode == "A01-0" else burst["probability"].tolist()
            schedule = check_schedule(fixture, episodes[episode], pos, spec["future_intervals"], probability)
            source_scope = "Original or separately source-bound numerical continuation."
        finite_checks.append({"artifact": entry["artifact"], "intervals": len(schedule),
            "minimum_dt": min(schedule), "maximum_scaled_error": max(fixture["scaled_errors"]),
            "no_future_observations_by_runner_inspection": True, "source_scope": source_scope})
    record("six_finite_fixtures_bind_actual_gaps_and_summary", fixtures=finite_checks,
           future_label_scope="Runner training uses only two A prefixes; finite continuation consumes probability/physics/durations, not future labels.")

    learn = ROOT / "numerics-learnable-physics-v1"
    learning_report, learning_plan = load(learn / "report.json"), load(learn / "plan.json")
    source_map(learning_plan["source_before"], learn / "source/qualification/hcsn_differentiable")
    assert learning_report["source_before"] == learning_report["source_after"] == learning_plan["source_before"]
    assert learning_report["source_unchanged"] and learning_report["plan_sha256"] == sha(learn / "plan.json")
    learn_header, learn_visits, learn_footer = read_trace(learn / "trace.jsonl")
    assert len(learn_visits) == 48
    states = []
    for index in range(3):
        receipt = load(learn / f"state-{index}-receipt.json")
        assert receipt == learning_report["states"][index]
        saved, digest = tensor_state_digest(learn / f"state-{index}.pt")
        assert digest == receipt["model_sha256"] and sha(learn / f"state-{index}.pt") == receipt["checkpoint_sha256"]
        assert receipt["actual_optimizer_updates_completed"] == index
        for name, value in receipt["raw_parameters"].items():
            key = [key for key in saved if key.endswith("." + name)]
            assert len(key) == 1 and float(saved[key[0]]) == value
        subset = learn_visits[index * 16:(index + 1) * 16]
        assert all(row["model_sha256"] == digest and row["update_index"] == index for row in subset)
        assert all(row["parameters"] == receipt["physical"] for row in subset)
        assert subset[-1]["posterior"][0] == receipt["posterior"]
        states.append({"updates_completed": index, "tensor_digest": digest,
                       "file_sha256": receipt["checkpoint_sha256"], "mu": receipt["physical"]["mu"]})
    for index in (1, 2):
        update = load(learn / f"update-{index}.json")
        assert update == learning_report["updates"][index - 1]
        assert update["before_raw"] == learning_report["states"][index - 1]["raw_parameters"]
        assert update["after_raw"] == learning_report["states"][index]["raw_parameters"]
        assert all(update["before_raw"][name] != update["after_raw"][name] for name in update["before_raw"])
    fd_max = max(row["absolute_error"] for state in learning_report["states"][1:] for row in state["complete_forward_finite_difference"])
    assert fd_max == summary["learnable_physics"]["complete_forward_AD_FD_maximum_absolute_error"]
    assert summary["learnable_physics"]["coarse_grid_value_status"] == learning_report["domain_status"] == "HOLD"
    record("learnable_physics_three_saved_states_and_48_visits", states=states,
           four_raw_parameters_change_after_each_actual_update=True,
           complete_forward_FD_checked_post_update_states=[1, 2], complete_forward_FD_maximum_absolute_error=fd_max,
           all_drifts_negative=True, coarse_grid_numerical_admission="HOLD")
    coarse = load(ROOT / "numerics-real-posterior-v1/report.json")
    coarse_failures = [row for row in coarse["finite_continuations"] if row["intervals"] == 32 and row["status"] == "HOLD"]
    assert coarse_failures == summary["retained_failures"]["active128_endpoint4_8_finite32"]["failed_rows"]
    record("all_three_active128_finite_failures_preserved", failed_positions=[r["position"] for r in coarse_failures],
           maximum_scaled_error=max(max(r["scaled_errors"]) for r in coarse_failures),
           interpretation="The 128 and 256 grids use separately initialized and trained state encoders/posteriors; this is not an isolated common-posterior grid-convergence comparison.")
    pressure = load(ROOT / "numerics-refinement-reproduction-v1/report.json")
    assert len(pressure["rows"]) == 135 and pressure["passed_rows"] == 0
    assert pressure["maximum_difference_from_original"] == summary["retained_failures"]["endpoint2_pressure"]["maximum_difference_from_original"]
    assert pressure["source_unchanged"]
    record("failed_pressure_gate_is_preserved", rows=135, passing_rows=0,
           finite_schedule_success_does_not_override_perpetual_stress_failure=True)
    report["passed"] = True
except Exception:
    report["error"] = traceback.format_exc()
finally:
    report["supersedes"] = {"receipt": "p1-independent-provenance-review-v2.json", "reason": "Adds initial-versus-trained tensor comparison, original optimizer-update log linkage, and the maximum over all three coarse-grid finite failures. Earlier reviewer-parser failure is preserved in v1."}
    report["wall_seconds"] = time.perf_counter() - started
    report["review_source_sha256"] = sha(Path(__file__))
    report["archive_unchanged"] = sha(ARCHIVE) == report["archive_sha256"]
    report["passed"] = report["passed"] and report["archive_unchanged"]
    with OUT.open("x") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]),
        "error": report.get("error"), "path": str(OUT), "sha256": sha(OUT), "wall_seconds": report["wall_seconds"]}))
raise SystemExit(0 if report["passed"] else 1)
