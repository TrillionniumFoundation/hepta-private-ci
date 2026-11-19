"""Build the fixed D-only roster from archived observations, with no model calls."""

import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import zipfile


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
EVIDENCE = REPO / "qualification/hcsn_differentiable/evidence"
ARMS = ["gru", "cfc", "snn_plif", "event_time_lif", "ssm_s4d", "attention", "hcsn"]
SEEDS, LRS = [101, 211, 307], [0.001, 0.003]
MANIFEST = "0eb233da8d0b766c35356ba450d0572f1e6a87a47f1d8a17cd32c2ae6f25a1cb"
SOURCES = {}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def read(path):
    data = path.read_bytes()
    SOURCES[str(path.relative_to(REPO))] = {"bytes": len(data), "sha256": digest(data)}
    return json.loads(data)


def matrix_check(row):
    matrix = row["confusion_matrix"]
    require(len(matrix) == 11 and all(len(x) == 11 for x in matrix), "eleven classes")
    require(all(type(n) is int and n >= 0 for r in matrix for n in r), "integer counts")
    require(sum(map(sum, matrix)) == row["events"] == 31952, "complete original D")
    f1 = statistics.mean(2 * matrix[i][i] / d if d else 0.0 for i in range(11)
                         for d in [sum(matrix[i]) + sum(r[i] for r in matrix)])
    require(type(row["macro_f1_11_classes"]) in (float, int)
            and math.isfinite(row["macro_f1_11_classes"])
            and abs(f1 - row["macro_f1_11_classes"]) <= 1e-12, "D metric arithmetic")


def strict_history(rows):
    best, epoch, anchor, stale, stop = -1.0, None, -1.0, 0, None
    for number, row in enumerate(rows, 1):
        require(type(row["epoch"]) is int and row["epoch"] == number, "contiguous complete epochs")
        matrix_check(row["development"])
        score = row["development"]["macro_f1_11_classes"]
        if score > best:
            best, epoch = score, number
        if score > anchor + .002:
            anchor, stale = score, 0
        else:
            stale += 1
        if stop is None and number >= 30 and stale >= 10:
            stop = number
    return {"best": best, "best_epoch": epoch, "anchor": anchor, "stale": stale,
            "first_plateau_epoch": stop, "complete_epochs": len(rows)}


def select(candidates):
    expected = {(a, s, lr) for a in ARMS for s in SEEDS for lr in LRS}
    keys = [(r["arm"], r["seed"], r["learning_rate"]) for r in candidates]
    require(len(keys) == len(set(keys)) == 42 and set(keys) == expected, "all 42 unique opportunities")
    require(all(type(r["seed"]) is int and type(r["learning_rate"]) is float
                and type(r["adequate"]) is bool and type(r["D_macro_f1"]) is float
                and math.isfinite(r["D_macro_f1"]) and 0 <= r["D_macro_f1"] <= 1
                for r in candidates), "strict candidate types and finite quality")
    families, roster = [], []
    for arm in ARMS:
        options = []
        for lr in LRS:
            members = sorted([r for r in candidates if r["arm"] == arm and r["learning_rate"] == lr],
                             key=lambda r: r["seed"])
            options.append({"learning_rate": lr, "three_seed_mean": statistics.mean(r["D_macro_f1"] for r in members),
                            "members": [r["name"] for r in members], "adequate_count": sum(r["adequate"] for r in members)})
        winner = min(options, key=lambda x: (-x["three_seed_mean"], x["learning_rate"]))
        families.append({"arm": arm, "candidates": options, "selected_learning_rate": winner["learning_rate"],
                         "selected_three_seed_mean": winner["three_seed_mean"],
                         "selected_all_three_adequate": winner["adequate_count"] == 3})
        roster.extend(r for r in candidates if r["arm"] == arm and r["learning_rate"] == winner["learning_rate"])
    return families, sorted(roster, key=lambda r: (ARMS.index(r["arm"]), r["seed"]))


def main():
    plan_path = EVIDENCE / "p0p5-c2-progress-20261110/confirmation-E-proposal/PLAN.json"
    plan = read(plan_path)
    require(plan["current_development_study"]["arms"] == ARMS
            and plan["current_development_study"]["seeds"] == SEEDS, "original E plan roster")
    curves_dir = EVIDENCE / "p0p5-resource-replay-20261110/curves-originals"
    parts = [curves_dir / ("hcsn-original42-c1-curves-20261110-v1.zip.part" + n) for n in ("00", "01")]
    raw = b""
    for path in parts:
        data = path.read_bytes(); raw += data
        SOURCES[str(path.relative_to(REPO))] = {"bytes": len(data), "sha256": digest(data)}
    require(digest(raw) == "0ab09b443b102e056849900eb2fcb2d20933a78d6ef321373ae354f98e9b5f1d", "exact curves archive")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        data = archive.read("CURVES.json")
    require(digest(data) == "9e2ff18ec234185ac68c581c775e8ac93c15d62a68605c4897c0fc1098da2d94", "exact original curves")
    curves = json.loads(data)
    fits = {(r["phase"], r["name"]): r for r in curves["fits"]}
    observations = {}
    for row in curves["observations"]:
        if row["kind"] == "complete_epoch":
            observations.setdefault(row["name"], []).append(row)
    for rows in observations.values():
        rows.sort(key=lambda x: x["epoch"])
    c2_path = EVIDENCE / "c2-readonly-20261119/original-c2-journals-and-results.zip"
    raw = c2_path.read_bytes()
    SOURCES[str(c2_path.relative_to(REPO))] = {"bytes": len(raw), "sha256": digest(raw)}
    require(digest(raw) == "7f2001bcc178e78c5f8de120007110e93534ba5a19e490fff307065e5466d2c3", "exact original C2 archive")
    c2, invalid = {}, {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for seed in SEEDS:
            for lr in LRS:
                name = f"hcsn-s{seed}-lr{lr}"
                invalid[name] = []
                member = f"fits/{name}/events.jsonl"
                for number, line in enumerate(archive.read(member).splitlines(), 1):
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        invalid[name].append(number); continue
                    if row.get("kind") == "epoch_completed":
                        require(row["complete"] is True, "complete C2 epoch")
                        observations[name].append(row)
                member = f"fits/{name}/result.json"
                if member in archive.namelist():
                    data = archive.read(member); c2[name] = json.loads(data)
                    c2[name]["_report_identity"] = {"bytes": len(data), "sha256": digest(data), "archive_member": member}
    require(invalid == {f"hcsn-s{s}-lr{lr}": ([3075] if s == 211 and lr == .001 else
                        [3114] if s == 307 and lr == .001 else []) for s in SEEDS for lr in LRS}, "retain exact known invalid tails")
    followups = [("hcsn-s211-lr0.001", "hcsn_c2_continuation_20261119/evidence/terminal-hcsn-s211-lr0.001/RESULT.json"),
                 ("hcsn-s307-lr0.001", "hcsn_c2_continuation_20261119/evidence/first-terminal-hcsn-s307-lr0.001/RESULT.json"),
                 ("hcsn-s211-lr0.001", "hcsn_c2_partial_resume_20261119/evidence/terminal/RESULT.json")]
    latest = {}
    for name, relative in followups:
        result = read(REPO / "qualification" / relative)
        observations[name].extend(result["epochs"])
        latest[name] = (result, relative)
    review_root = EVIDENCE / "p0p5-20261110/review/baseline36-c1-native-v1"
    records = []
    for arm in ARMS:
        for seed in SEEDS:
            for lr in LRS:
                name = f"{arm}-s{seed}-lr{lr}"
                original = fits["original", name]
                final = fits.get(("C1", name), original)
                history = strict_history(observations[name])
                report_path, report_identity = final["report_path"], {"bytes": final["report_bytes"], "sha256": final["report_sha256"]}
                checkpoint = {"path": str(Path(report_path).parent / "best.pt"), "sha256": final["best_checkpoint_sha256"]}
                adequacy, metrics, phase = final["training_adequacy_established"], final["selected_development"], final["phase"]
                audit, config, logits = None, None, None
                source_map = final["source_before"]
                costs = {"original": original["outer"], "C1": final["outer"] if final["phase"] == "C1" else None}
                if arm != "hcsn":
                    audit = read(review_root / f"v1/output/original-{name}.json")
                    config = audit["model_configuration"]
                    if final["phase"] == "C1":
                        audit = read(review_root / f"v2/output/C1-{name}.json")
                    logits = {"path": str(Path(report_path).parent / "development_logits.pt"), "sha256": audit["saved_logits_sha256"]}
                elif name in c2:
                    r = c2[name]; phase = "C2_original_producer_terminal"
                    report_path = "/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training/c2-native-execution-20261110-c385-v1/fits/" + name + "/result.json"
                    report_identity = r["_report_identity"]
                    checkpoint = {"path": str(Path(report_path).parent / "best.pt"), "sha256": r["best_checkpoint_sha256"]}
                    logits = {"path": str(Path(report_path).parent / "development_logits.pt"), **r["selected_development_logits"]}
                    config, source_map, metrics = r["model_configuration"], r["source_before"], r["selected_development"]
                    adequacy = r["training_adequacy_established"]
                    costs["C2_recorded"] = {k: r[k] for k in ["cumulative_process_wall_seconds", "cumulative_process_cpu_seconds", "phase_process_wall_seconds", "phase_process_cpu_seconds", "peak_rss_bytes"]}
                else:
                    r, relative = latest[name]; phase = "independent_continuation"
                    checkpoint, logits, metrics = r["selected_best_checkpoint"], r["selected_development_logits"], r["selected_development"]
                    adequacy = r["training_adequacy_established"]
                    report_path = str(REPO / "qualification" / relative)
                    report_identity = SOURCES["qualification/" + relative]
                    costs["continuation_report"] = {k: r[k] for k in ["new_phase_wall_seconds_before_exit", "new_phase_cpu_seconds_before_exit", "original_partial_work"]}
                require(history["best_epoch"] == (r["selected_best_checkpoint"]["epoch"] if arm == "hcsn" and name in latest else
                        c2[name]["best_epoch"] if name in c2 else final["best_epoch"]), "strict-best epoch")
                require(history["best"] == metrics["macro_f1_11_classes"], "strict-best recorded D quality")
                require(adequacy is bool(history["first_plateau_epoch"] is not None and original["diagnostic_passed"]), "recorded adequacy rule")
                records.append({"name": name, "arm": arm, "seed": seed, "learning_rate": lr, "phase": phase,
                    "D_macro_f1": history["best"], "D_metrics": metrics, "strict_history": history,
                    "adequate": adequacy, "memorization_passed": original["diagnostic_passed"],
                    "checkpoint": checkpoint, "D_logits": logits, "model_configuration": config,
                    "source_file_sha256": source_map, "report": {"path": report_path, **report_identity},
                    "costs": costs, "C1_resume_start_direct_witness": False if final["phase"] == "C1" else None,
                    "quality_basis": "Recorded strict-best full D; no fresh forward in this preparation."})
    families, roster = select(records)
    output = {"schema": "hcsn-D-only-fixed-selection-v1", "families": families, "all_42_candidates": records,
              "roster": roster, "known_invalid_original_tail_lines": invalid, "input_files": SOURCES,
              "source_parent_commit": "865e8f4960577f7e4774aa6c24df85fe5b3d5cb6",
              "D_manifest_sha256": MANIFEST, "selection_rule": "common LR by arithmetic three-seed mean; exact tie lower .001; never filter by adequacy before selection",
              "confirmation_E_access": False, "automatic_trigger": False, "scientific_admission": "HOLD",
              "original_controller_terminal": "UNKNOWN", "original_independent_full_training_replays": 0,
              "actual_model_operations": 0, "status": "D_SELECTION_FIXED_ACTUAL_BYTES_PENDING"}
    with (HERE / "evidence/SELECTION.json").open("x") as stream:
        json.dump(output, stream, sort_keys=True, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps({"families": families, "roster": len(roster), "input_files": len(SOURCES)}, indent=2))


if __name__ == "__main__":
    main()
