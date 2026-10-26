"""Pure metadata audit of a transported owner; never opens model/array payloads."""

import hashlib
import json
from pathlib import Path


SEEDS = (17, 29, 43)
PROFILES = ("supervised", "terminal_entropic_ndu")
ARMS = ("b0g0", "b0g1", "b1g0", "b1g1")
STAGES = ("prepare", "bootstrap", "gates", "inference", "replay", "evaluate")
BLOCKED_SUFFIXES = {".pt", ".npz", ".png"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


class Metadata:
    def __init__(self, owner_copy, owner_files):
        self.root, self.files = Path(owner_copy), owner_files
        self.read_identities = {}

    def bound(self, name, expected):
        require(name in self.files, "missing original owner member: " + name)
        for key in ("sha256", "bytes"):
            if key in expected:
                require(self.files[name][key] == expected[key], "original member identity differs: " + name)

    def read(self, name):
        path = Path(name)
        require(not path.is_absolute() and ".." not in path.parts and path.suffix == ".json",
                "metadata reader allows bounded relative JSON only")
        path = self.root / path
        require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 64 << 20,
                "missing or unsafe transported JSON")
        raw = path.read_bytes()
        identity = {"sha256": digest(raw), "bytes": len(raw)}
        self.bound(name, identity)
        self.read_identities[name] = identity
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON")))

    def seal(self, stage, filename, required):
        name = stage + "/" + filename
        record = self.read(name)
        require(record["schema"] == "hepta.ndu-fresh-factorial.seal.v1", "unknown seal schema")
        require(set(record["files"]) == set(required), "required set differs for " + stage)
        actual = {key[len(stage) + 1:] for key in self.files if key.startswith(stage + "/")}
        require(actual == set(required) | {filename}, "original stage contains omitted/extra member: " + stage)
        for relative, expected in record["files"].items():
            require(not Path(relative).is_absolute() and ".." not in Path(relative).parts, "unsafe seal path")
            self.bound(stage + "/" + relative, expected)
        return record


def audit_generation(metadata, plan, published_head):
    m = metadata
    protocol_sha = digest(plan)
    data = m.read("data/data-receipt.json")
    cases = m.read("data/cases.json")["cases"]
    train_sources = m.read("data/training-source.json")
    observer_sources = m.read("data/observer-source.json")
    expected_data = {"training.npz", "training-source.json", "observer-training.npz", "observer-source.json",
                     "observations.npz", "cases.json", "reserved-sources.json", "final-targets.npz"}
    require(set(data["files"]) == expected_data, "data required set changed")
    require(data["protocol_canonical_sha256"] == protocol_sha and data["source_count"] == 90
            and data["source_pixels"] == 180 and data["withheld_targets_parsed_after_write"] is False,
            "data receipt scope changed")
    for name, identity in data["files"].items():
        m.bound("data/" + name, identity)
    expected_cases = [(split, start + offset, plan["corruptions"][offset % 6] if split == "future" else "clean")
                      for split, start, count in (("future", 120, 60), ("retention", 60, 30))
                      for offset in range(count)]
    require(len(cases) == 90, "case count differs")
    pixels = []
    for case, (split, index, corruption) in zip(cases, expected_cases, strict=True):
        require((case["case_id"], case["split"], case["index"], case["corruption"]) ==
                (f"{split}-{index:04}", split, index, corruption), "case schedule changed")
        require(len(case["source_ids"]) == 2, "source pair incomplete")
        pixels.extend(item.rsplit(":", 1)[-1] for item in case["source_ids"])
    require(len(set(pixels)) == 180, "final sources repeat")
    forbidden = set(plan["exposed_source_pixels"]) | set(train_sources["pixel_hashes"]) | set(observer_sources["pixel_hashes"])
    require(not set(pixels) & forbidden, "final sources overlap explicit exclusion/training/observer pools")
    require(len(plan["exposed_source_pixels"]) == 520, "explicit exclusion census changed")
    for item in (train_sources, observer_sources):
        require(len(item["source_ids"]) == len(item["pixel_hashes"]) == 10000, "prepared pool size changed")
        require([x.rsplit(":", 1)[-1] for x in item["source_ids"]] == item["pixel_hashes"], "pool IDs and pixel hashes differ")
    require(not set(train_sources["pixel_hashes"]) & set(observer_sources["pixel_hashes"]), "train/observer overlap")
    environment, source = data["environment"], data["source"]
    require(source["git_commit"] == published_head and source["files"] == plan["algorithm_source_files"], "published source binding differs")
    require(len(source["files"]) == 40, "algorithm source count changed")

    generation = m.read("bootstrap/bootstrap.json")
    start = m.read("bootstrap/generation-start.json")
    controls = m.read("bootstrap/recipe-controls.json")["controls"]
    require(len(controls) == 3 and {row["seed"] for row in controls} == set(SEEDS), "controls omit a seed")
    controls = {row["seed"]: row for row in controls}
    generation_id = digest({"study": plan["study_id"], "protocol": protocol_sha,
                            "data_receipt": m.files["data/data-receipt.json"]["sha256"],
                            "source_commit": published_head,
                            "provenance": "new_optimizer_execution_no_historical_checkpoints"})
    require(generation["generation_id"] == start["generation_id"] == generation_id, "fresh generation identity differs")
    require(generation["protocol_canonical_sha256"] == start["protocol_canonical_sha256"] == protocol_sha,
            "generation protocol differs")
    require(generation["data_receipt_sha256"] == start["data_receipt_sha256"] == m.files["data/data-receipt.json"]["sha256"],
            "generation data receipt differs")
    require(start["source_commit"] == published_head and generation["historical_weights_loaded"] is False
            and start["historical_weights_loaded"] is False and generation["audit_observer_used_for_training"] is False
            and generation["final_targets_opened"] is False and generation["observer_source_pools_disjoint"] is True,
            "fresh observer/base boundary changed")
    require(generation["environment"] == environment, "bootstrap environment changed")
    required_bootstrap = {"bootstrap.json", "generation-start.json", "recipe-controls.json", "source-freeze.json"}
    model_files, observers, base_reports = {}, {}, {}
    for ordinal, name in enumerate(("reward", "audit")):
        entry = generation["observers"][name]
        require(entry["path"] == name + "-observer.pt" and entry["report_path"] == name + "-observer.json", "observer alias")
        m.bound("bootstrap/" + entry["path"], entry["file"])
        report = m.read("bootstrap/" + entry["report_path"])
        ids = observer_sources["source_ids"][ordinal * 5000:(ordinal + 1) * 5000]
        require(report["seed"] == plan["observer_training"]["seeds"][name] and report["steps"] == 300
                and report["train_sources"] == 4000 and report["calibration_sources"] == 1000
                and report["source_ids_sha256"] == digest("\n".join(ids).encode())
                and report["parameter_sha256"] == entry["parameter_sha256"]
                and report["initial_parameter_sha256"] != report["parameter_sha256"]
                and report["selected_by_calibration"] is False, "observer training report differs")
        required_bootstrap.update((entry["path"], entry["report_path"]))
        model_files["bootstrap/" + entry["path"]] = entry["file"]
        observers[name] = report
    bases = {(x["seed"], x["profile"]): x for x in generation["bases"]}
    require(len(generation["bases"]) == len(bases) == 6 and set(bases) == {(s, p) for s in SEEDS for p in PROFILES}, "base census")
    for key, entry in bases.items():
        seed, profile = key
        stem = f"seed-{seed}-{profile}"
        require(entry["path"] == stem + ".pt" and entry["report_path"] == stem + "-training.json", "base alias")
        m.bound("bootstrap/" + entry["path"], entry["file"])
        report = m.read("bootstrap/" + entry["report_path"])
        require(report["config"] == {"seed": seed, **plan["base_training"]} and report["profile"] == profile,
                "base recipe changed")
        require(report["optimizer_updates"] == 2000 and [x["step"] for x in report["history"]] == list(range(1, 2001))
                and report["parameter_count"] == 1007464 and report["conditional_noise_scenarios"] == 2,
                "base updates/architecture changed")
        require(report["initial_parameter_sha256"] == controls[seed]["base_initial_parameter_sha256"]
                and report["batch_action_schedule_sha256"] == controls[seed]["base_batch_action_schedule_sha256"]
                and report["final_parameter_sha256"] == entry["parameter_sha256"]
                and report["final_snapshot_sha256"] == entry["snapshot_sha256"]
                and report["final_parameter_sha256"] != report["initial_parameter_sha256"]
                and report["fresh_generation_id"] == generation_id
                and report["source_manifest_sha256"] == plan["dataset_manifest_sha256"], "base provenance changed")
        required_bootstrap.update((entry["path"], entry["report_path"]))
        model_files["bootstrap/" + entry["path"]] = entry["file"]
        base_reports[key] = report
    for seed in SEEDS:
        require(base_reports[seed, PROFILES[0]]["paired_execution_cost"] == base_reports[seed, PROFILES[1]]["paired_execution_cost"],
                "paired base cost reports differ")
    m.seal("bootstrap", "bootstrap-seal.json", required_bootstrap)

    trained = m.read("training/training.json")
    require(trained["generation_id"] == generation_id and trained["protocol_canonical_sha256"] == protocol_sha
            and trained["base_updates_during_gate_fit"] == 0 and trained["gate_fits_completed"] == 12
            and trained["gate_optimizer_updates"] == 1440 and trained["final_targets_opened"] is False
            and trained["environment"] == environment, "gate training census/boundary differs")
    require(trained["bootstrap_seal_sha256"] == m.files["bootstrap/bootstrap-seal.json"]["sha256"]
            and trained["data_receipt_sha256"] == m.files["data/data-receipt.json"]["sha256"], "gate input seal changed")
    models = {(x["seed"], x["arm"]): x for x in trained["models"]}
    require(len(trained["models"]) == len(models) == 12 and set(models) == {(s, a) for s in SEEDS for a in ARMS}, "gate model census")
    required_training, gate_reports = {"source-freeze.json", "training.json"}, {}
    for (seed, arm), entry in models.items():
        stem, factors = f"seed{seed}-{arm}", plan["arms"][arm]
        require(entry["path"] == stem + ".pt" and entry["training_report_path"] == stem + "-training.json", "gate alias")
        require(all(entry[k] == v for k, v in factors.items()), "gate factors differ")
        m.bound("training/" + entry["path"], {"sha256": entry["checkpoint_file_sha256"]})
        report = m.read("training/" + entry["training_report_path"])
        control = controls[seed]
        require(report["seed"] == seed and report["fit_split"] == "train" and report["fit_pairs"] == 128
                and report["optimizer_updates"] == 120 and len(report["objective_history"]) == 120
                and report["gate_parameter_count"] == 3236 and report["batch_seed"] == seed * 1000003 + 4409
                and report["fresh_generation_id"] == generation_id, "gate recipe/update count differs")
        for key, expected in {
            "initial_gate_sha256": control["gate_initial_parameter_sha256"],
            "gate_update_schedule_sha256": control["gate_update_schedule_sha256"],
            "source_ids_sha256": control["gate_source_ids_sha256"],
            "scenario_seeds": control["gate_scenario_seeds"],
            "content_plan_metric_sha256": plan["metric_sha256"],
            "content_plan_scenario_count": 2, "content_plan_risk_aversion": 2,
            "content_plan_training_profile": factors["gate"],
            "content_plan_observer_sha256": generation["observers"]["reward"]["parameter_sha256"],
            "source_manifest_sha256": plan["dataset_manifest_sha256"],
            "base_sha256": bases[seed, factors["base"]]["snapshot_sha256"],
            "combined_sha256": entry["snapshot_sha256"], "final_gate_sha256": entry["gate_sha256"],
        }.items():
            require(report[key] == expected, "gate report differs: " + key)
        require(entry["base_sha256"] == report["base_sha256"], "gate base binding differs")
        required_training.update((entry["path"], entry["training_report_path"]))
        model_files["training/" + entry["path"]] = m.files["training/" + entry["path"]]
        gate_reports[seed, arm] = report
    for seed in SEEDS:
        for left, right in (("b0g0", "b0g1"), ("b1g0", "b1g1")):
            for key in ("base_sha256", "output_observation_sha256", "utility_table", "initial_gate_sha256",
                        "gate_update_schedule_sha256", "source_ids_sha256", "scenario_seeds", "batch_seed", "plans"):
                require(gate_reports[seed, left][key] == gate_reports[seed, right][key], "paired gate control differs: " + key)
    m.seal("training", "training-seal.json", required_training)
    for stage in ("bootstrap", "training", "inference", "replay", "evaluation"):
        require(m.read(stage + "/source-freeze.json") == source, "stage source changed: " + stage)
    sealed = m.read("model-seal.json")
    expected_seal = {"schema": "hepta.ndu-fresh-factorial.model-generation-seal.v1", "generation_id": generation_id,
        "protocol_canonical_sha256": protocol_sha, "data_receipt_sha256": generation["data_receipt_sha256"],
        "bootstrap_seal_sha256": m.files["bootstrap/bootstrap-seal.json"]["sha256"],
        "training_seal_sha256": m.files["training/training-seal.json"]["sha256"], "model_files": model_files,
        "optimizer_updates": {"observers": 600, "bases": 12000, "gates": 1440},
        "historical_checkpoint_recovery": False, "final_outcomes_used": False, "model_selection": "none"}
    require(len(model_files) == 20 and {k: v for k, v in sealed.items() if k != "at_utc"} == expected_seal
            and isinstance(sealed["at_utc"], str), "complete generation seal differs")
    require(generation["base_optimizer_updates"] == 12000 and generation["observer_optimizer_updates"] == 600,
            "bootstrap total updates differ")
    return {"data": data, "cases": cases, "bootstrap": generation, "training": trained,
            "observers": observers, "base_reports": base_reports, "gate_reports": gate_reports,
            "model_seal": sealed, "environment": environment, "source": source,
            "source_scope": "explicit prior/training/observer identities independently cross-checked; validation partition disjointness remains the pinned preparation assertion; no corpus or target/model payload opened"}
