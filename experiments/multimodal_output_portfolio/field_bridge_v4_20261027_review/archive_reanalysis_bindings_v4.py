"""Manifest-only binding checks for a literal V4 statistical replay.

No generator, observer, checkpoint deserializer, corpus loader, or live-run
lookup is used. Unrestored media/checkpoints stay covered by the full archive
integrity receipt; old V1-V3 generated histories are outside this archive.
"""
import ast
import gzip
from pathlib import Path

import archive_integrity_v4 as integrity

BASE = "repository/experiments/multimodal_output_portfolio/"
SCIENCE = BASE + "field_bridge_v4_20261027/"
REVIEW = BASE + "field_bridge_v4_20261027_review/"
OLD_SCIENCE = BASE + "field_bridge_v3_20261027/"
LEGACY = "legacy/v3-run/"
V2_REGISTRY = "legacy/v2-source-identity/SOURCE_IDENTITIES.json"
SEEDS = (17, 29, 43)
METHODS = ("ordinary_0", "ordinary_1", "ordinary_2", "ordinary_3", "raw_field",
           "origin_field", "origin_generic", "origin_richer", "origin_h7")
SCHEDULES = (14000, 14001, 14002, 14003)
ADAPTATION = ["qualification_" + name for name in ("gradient", "rehearsal", "probe", "guard")]
ENDPOINTS = ["qualification_task", "qualification_clean"]
require, canonical, file_sha = integrity.require, integrity.canonical, integrity.file_sha


def exact(actual, expected, label):
    require(canonical(actual) == canonical(expected), "Literal archive binding differs: " + label)


def required_members(manifest):
    """Deterministic metadata/array restore plan from the complete member list."""
    members = integrity.validate_manifest(manifest)
    names = {SCIENCE + name for name in ("PROTOCOL.json", "SOURCE_ALLOCATION.json",
                                        "SOURCE_IDENTITIES.json.gz", "qualification_analysis.py")}
    names.update(REVIEW + name for name in ("archive_integrity_v4.py", "archive_reanalysis_v4.py",
                                            "archive_reanalysis_bindings_v4.py"))
    names.update(OLD_SCIENCE + name for name in
                 ("PROTOCOL.json", "SOURCE_ALLOCATION.json", "SOURCE_IDENTITIES.json.gz", "assets.py"))
    names.add(V2_REGISTRY)
    names.add(LEGACY + "DEVELOPMENT_SELECTION.json")
    names.add(manifest["provenance"]["asset_root_path"].rstrip("/") + "/RESTORATION.json")
    names.update("run/" + name for name in ("TRAINING_SEAL.json", "QUALIFICATION_START.json", "QUALIFICATION.json",
                                           "V4_EXECUTION_LEDGER.json", "STUDY_DISPOSITION.json"))
    names.update(name for name in members if name.startswith("freezes/") and name.endswith(".json"))
    names.update(name for name in members if name.startswith("run/PHASE_RECEIPTS/") and name.endswith(".json"))
    names.update(manifest["provenance"].get("receipts", {}))
    names.update(manifest["provenance"].get("archive_tools", {}))
    for seed in SEEDS:
        for phase in ("train", "evaluate"):
            prefix = f"run/{phase}/{seed}/"
            names.update(prefix + name for name in ("START.json", "COMPLETE.json", "ASSET_IDENTITIES.json"))
            for method in METHODS:
                names.update(prefix + f"{method}/schedule-{sid}/COMPLETE.json" for sid in SCHEDULES)
        names.update(f"run/evaluate/{seed}/" + name for name in ("ENDPOINTS.npz", "ENDPOINT_IDENTITIES.json"))
        names.update(f"run/PHASE_RECEIPTS/{phase}-{seed}.json" for phase in ("train", "evaluate"))
    for phase in ("seal-training", "qualify"):
        optional = f"run/{phase}/START.json"
        if optional in members:
            names.add(optional)
    require(names <= set(members), "Missing required replay members: " + repr(sorted(names - set(members))))
    return sorted(names)


class Restored:
    def __init__(self, root, receipt_path, expected_receipt_sha256):
        self.root = Path(root).resolve()
        require(file_sha(receipt_path) == expected_receipt_sha256, "Integrity receipt SHA differs")
        self.receipt = integrity.strict_json(Path(receipt_path).read_bytes())
        r = self.receipt
        require(r["schema"] == "hepta.field-bridge.v4.archive-integrity.1" and r["passed"] is True
                and r["external_archive_identity_supplied"] is True
                and r["outer_gzip_crc_verified_to_physical_eof"] is True
                and r["all_inner_gzip_crc_verified"] is True and r["exception_allowlist"] == [],
                "Full archive SHA/CRC/EOF verification with no exceptions is required")
        require(r["restored_root"] == str(self.root) and r["manifest_restored"] is True, "Wrong literal restore root")
        raw = (self.root / "MANIFEST.json").read_bytes()
        require(integrity.sha(raw) == r["manifest_sha256"], "Restored MANIFEST SHA differs")
        self.manifest = integrity.strict_json(raw)
        self.members = integrity.validate_manifest(self.manifest)
        exact(r["members"], self.manifest["members"], "full manifest coverage")
        exact(r["provenance"], self.manifest["provenance"], "manifest provenance")
        require(r["payload_members"] == len(self.members)
                and r["payload_bytes"] == sum(row["bytes"] for row in self.members.values()), "Archive totals differ")
        self.selected = {row["path"]: row for row in r["restored_members"]}
        require(len(self.selected) == len(r["restored_members"])
                and set(self.selected) == set(required_members(self.manifest)), "Literal restore inventory differs")
        for name, row in self.selected.items():
            exact(row, self.members[name], "selected member identity")
            self.path(name)
        self.freezes = {}
        for name in self.selected:
            if name.startswith("freezes/") and name.endswith(".json"):
                record = self.json(name)
                if isinstance(record, dict) and {"allowed_phases", "source_files", "registered_commit", "protocol_sha256"} <= set(record):
                    identity = self.digest(name)
                    require(identity not in self.freezes or self.freezes[identity][1] == record, "Freeze identity collision")
                    self.freezes[identity] = (name, record)

    def digest(self, name):
        integrity.safe_name(name)
        require(name in self.members, "Required archived payload absent: " + name)
        return self.members[name]["sha256"]

    def path(self, name):
        require(name in self.selected, "Unrestored member requested: " + name)
        path = self.root / name
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(self.root)
                and path.stat().st_size == self.members[name]["bytes"] and file_sha(path) == self.digest(name),
                "Literal restored bytes changed: " + name)
        return path

    def json(self, name):
        return integrity.strict_json(self.path(name).read_bytes())

    def bind(self, prefix, values):
        require(isinstance(values, dict), "Invalid reference map")
        for relative, identity in values.items():
            require(self.digest(prefix + relative) == identity, "Archived reference differs: " + prefix + relative)

    def complete(self, prefix):
        """Only current V4 COMPLETE inventories, never historical partial inputs."""
        require(prefix.startswith(("run/train/", "run/evaluate/")), "Completeness applies only to V4 current paths")
        record = self.json(prefix + "COMPLETE.json")
        actual = {name[len(prefix):] for name in self.members if name.startswith(prefix) and name != prefix + "COMPLETE.json"}
        require(set(record["files"]) == actual and "FAILED.json" not in actual, "Current V4 complete inventory differs")
        self.bind(prefix, record["files"])
        return record

    def scope(self, scope, protocol, phase=None):
        expected = {"study_id": protocol["study_id"], "protocol_sha256": self.digest(SCIENCE + "PROTOCOL.json"),
                    "source_allocation_sha256": protocol["source_allocation_sha256"],
                    "source_manifest_sha256": protocol["source_manifest_sha256"],
                    "old_training_protocol_sha256": protocol["old_training_protocol_sha256"]}
        require(all(scope.get(k) == v for k, v in expected.items()), "Phase scope differs")
        require(scope["freeze_sha256"] in self.freezes, "Phase freeze bytes are not literally restored")
        name, freeze = self.freezes[scope["freeze_sha256"]]
        require(freeze["schema"] == "hepta.field-bridge.v4.external-freeze.1"
                and freeze["protocol_sha256"] == expected["protocol_sha256"]
                and freeze["registered_commit"] == scope["registered_commit"]
                and freeze["registered_commit"] in self.manifest["provenance"]["registered_commits"]
                and freeze.get("study_id") == protocol["study_id"], "Freeze registration/scope differs")
        require(phase is None or phase in freeze["allowed_phases"], "Freeze does not authorize recorded phase")
        self.bind(BASE, freeze["source_files"])
        self.bind("run/", freeze.get("artifacts", {}))
        self.bind(LEGACY, freeze.get("old_artifacts", {}))
        if phase in ("evaluate", "qualify"):
            sealed = self.json("run/TRAINING_SEAL.json")
            required = {"TRAINING_SEAL.json": self.digest("run/TRAINING_SEAL.json"), **sealed["files"]}
            require(all(freeze.get("artifacts", {}).get(k) == v for k, v in required.items()),
                    "Endpoint freeze does not bind every sealed training artifact")
        return name, freeze

    def start(self, prefix, phase, seed, protocol):
        record = self.json(prefix + "START.json")
        require(record["schema"] == "hepta.field-bridge.v4.phase-start.1" and record["phase"] == phase
                and record["seed"] == seed and record["study_id"] == protocol["study_id"], "START identity differs")
        _, freeze = self.scope(record["scope"], protocol, phase)
        require(record["source_files"]
                and integrity.sha(canonical(record["source_files"])) == record["scope"]["source_files_sha256"]
                and all(freeze["source_files"].get(k) == v for k, v in record["source_files"].items()),
                "START source closure differs from freeze")
        self.bind(BASE, record["source_files"])
        return record

    def phase_cost(self, phase, seed, scope, complete_path, protocol):
        name = f"run/PHASE_RECEIPTS/{phase}-{seed if seed is not None else 'all'}.json"
        record = self.json(name)
        require(record["schema"] == "hepta.field-bridge.v4.phase-cost-receipt.1"
                and record["study_id"] == protocol["study_id"] and record["phase"] == phase and record["seed"] == seed
                and record["scope"] == scope and record["complete_sha256"] == self.digest(complete_path),
                "Complete phase-cost binding differs")
        return record


def verify_registry(view, protocol):
    allocation = view.json(SCIENCE + "SOURCE_ALLOCATION.json")
    require(view.digest(SCIENCE + "SOURCE_ALLOCATION.json") == protocol["source_allocation_sha256"]
            and allocation["manifest_sha256"] == protocol["source_manifest_sha256"]
            and integrity.sha(canonical({k: v for k, v in allocation.items() if k != "manifest_sha256"}))
                == allocation["manifest_sha256"], "New source allocation differs")
    packed = view.path(SCIENCE + "SOURCE_IDENTITIES.json.gz").read_bytes()
    raw = gzip.decompress(packed)
    require(integrity.sha(packed) == protocol["source_registry_gzip_sha256"] == allocation["registry_gzip_sha256"]
            and integrity.sha(raw) == allocation["registry_sha256"], "New source registry differs")
    registry = integrity.strict_json(raw)
    require(registry["schema"] == "hepta.field-bridge.v4.source-identities.1"
            and registry["prior_allocations"] == allocation["prior_allocations"], "New registry provenance differs")
    prior = allocation["prior_allocations"]
    old_v2 = view.json(V2_REGISTRY)
    require(view.digest(V2_REGISTRY) == prior["v2_registry_sha256"], "Full V2 source registry differs")
    old_allocation = view.json(OLD_SCIENCE + "SOURCE_ALLOCATION.json")
    require(old_allocation["manifest_sha256"] == prior["v3_manifest_sha256"]
            and integrity.sha(canonical({k: v for k, v in old_allocation.items() if k != "manifest_sha256"}))
                == old_allocation["manifest_sha256"], "Full V3 allocation differs")
    old_packed = view.path(OLD_SCIENCE + "SOURCE_IDENTITIES.json.gz").read_bytes()
    old_raw = gzip.decompress(old_packed)
    require(integrity.sha(old_packed) == old_allocation["registry_gzip_sha256"]
            and integrity.sha(old_raw) == prior["v3_registry_sha256"] == old_allocation["registry_sha256"],
            "Full V3 registry differs")
    old_v3 = integrity.strict_json(old_raw)
    old2 = {h for role in old_v2["source_splits"].values() for h in role["pixel_sha256"]}
    old3 = {identity.split(":")[-1] for role in old_v3["roles"].values() for identity in role["identities"]}
    require(len(old2) == 29000 and len(old3) == 28048 and not old2 & old3, "Historical exclusion inventory differs")
    counts = dict(zip(ADAPTATION + ENDPOINTS, (2000, 512, 256, 512, 1024, 2048)))
    require(set(registry["roles"]) == set(counts), "New source role membership differs")
    all_pixels = []
    for name, count in counts.items():
        role = registry["roles"][name]
        ids = role["identities"]
        require(role["official_partition"] == "train" and len(ids) == count, "New source role count/partition differs")
        pixels = []
        for identity in ids:
            parts = identity.split(":")
            require(len(parts) == 4 and parts[:2] == ["mnist", "train"] and parts[2].isdecimal()
                    and str(int(parts[2])) == parts[2] and 0 <= int(parts[2]) < 60000
                    and integrity.valid_digest(parts[3]), "Noncanonical source identity")
            pixels.append(parts[3])
        summary = allocation["roles"][name]
        require(summary["images"] == count and summary["pairs"] == count // 2
                and summary["identity_sha256"] == integrity.sha("\n".join(ids).encode())
                and summary["pixel_set_sha256"] == integrity.sha("\n".join(sorted(pixels)).encode()),
                "New source role identity digest differs")
        all_pixels.extend(pixels)
    require(len(all_pixels) == len(set(all_pixels)) == 6352 and not set(all_pixels) & (old2 | old3),
            "Registered-source independence differs")
    return registry, allocation


def verify_assets(view, allocation):
    """Bind original dataset/model/observer files without loading their payloads."""
    asset_root = view.manifest["provenance"]["asset_root_path"].rstrip("/") + "/"
    require(asset_root.startswith("assets/"), "Asset root is outside its declared archive root")
    constants = {}
    for node in ast.parse(view.path(OLD_SCIENCE + "assets.py").read_bytes()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("ORIGINAL_ARCHIVE", "PINNED"):
                constants[node.targets[0].id] = ast.literal_eval(node.value)
    require(set(constants) == {"ORIGINAL_ARCHIVE", "PINNED"} and len(constants["PINNED"]) == 9,
            "Frozen original asset constants differ")
    restoration = view.json(asset_root + "RESTORATION.json")
    require(restoration["archive_sha256"] == constants["ORIGINAL_ARCHIVE"], "Original archive reference differs")
    selected = {row["path"]: row["sha256"] for row in restoration["selected_files"]}
    require(len(selected) == len(restoration["selected_files"]), "Duplicate original restoration identity")
    view.bind(asset_root, selected)
    view.bind(asset_root, constants["PINNED"])
    require(all(selected.get(k) == v for k, v in constants["PINNED"].items()), "Original pinned asset restoration differs")
    for row in allocation["dataset_files"]:
        name = asset_root + "ndu-data/" + row["name"]
        require(view.digest(name) == row["sha256"] and view.members[name]["bytes"] == row["bytes"],
                "Registered original dataset file differs")
    return constants


def verify_loaded_assets(view, prefix, seed, observers, protocol, constants):
    record = view.json(prefix + "ASSET_IDENTITIES.json")
    ids = record["identities"]
    require(record["schema"] == "hepta.field-bridge.v4.asset-identities.1"
            and record["study_id"] == protocol["study_id"]
            and ids["loaded_observers"] == observers and set(ids["models"]) == {str(seed)}
            and ids["original_archive_sha256"] == constants["ORIGINAL_ARCHIVE"]
            and ids["pinned_files"] == constants["PINNED"], "Phase asset identities differ")
    model = ids["models"][str(seed)]
    name = f"ndu-runs/full-002/seed-{seed}-terminal_entropic_ndu.pt"
    require(model["file_sha256"] == constants["PINNED"][name]
            and integrity.valid_digest(model["parameter_sha256"]), "Original model file identity differs")


def verify_bindings(view, protocol, registry, allocation):
    require(view.manifest["provenance"]["protocol"] ==
            {"path": SCIENCE + "PROTOCOL.json", "sha256": view.digest(SCIENCE + "PROTOCOL.json")},
            "Manifest names a different registered protocol")
    require(not any(name.endswith("/FAILED.json") and name.startswith(tuple("run/" + p + "/" for p in
                    ("train", "seal-training", "evaluate", "qualify"))) for name in view.members),
            "A failed scientific phase cannot be reinterpreted as successful evidence")
    constants = verify_assets(view, allocation)
    require(view.digest(OLD_SCIENCE + "PROTOCOL.json") == protocol["old_training_protocol_sha256"]
            and view.json(OLD_SCIENCE + "PROTOCOL.json")["training"] == protocol["training"],
            "Original numerical training configuration differs")
    old_selection = view.json(LEGACY + "DEVELOPMENT_SELECTION.json")
    require(old_selection["passed"] is False
            and old_selection["ordinary_action_indices"] == protocol["qualification"]["ordinary_action_indices"]
            and old_selection["selected_adaptive"] == "richer", "Failed historical gate or comparator was changed")
    seal = view.json("run/TRAINING_SEAL.json")
    require(seal["schema"] == "hepta.field-bridge.v4.training-seal.1" and seal["study_id"] == protocol["study_id"]
            and seal["paths"] == 108 and seal["all_training_completed_before_any_endpoint"] is True,
            "Training seal identity differs")
    view.scope(seal["scope"], protocol)
    train_files = {name[4:] for name in view.members if name.startswith("run/train/")}
    train_files.update(f"PHASE_RECEIPTS/train-{seed}.json" for seed in SEEDS)
    require(set(seal["files"]) == train_files, "All current training files must be sealed")
    view.bind("run/", seal["files"])
    training_freeze_name = view.manifest["provenance"]["training_freeze_path"]
    training_freeze = view.json(training_freeze_name)
    require(len(training_freeze["old_artifacts"]) == 25, "Original learning input inventory differs")
    view.bind(LEGACY, training_freeze["old_artifacts"])
    for rows in protocol["frozen_v3_learning_artifacts"].values():
        for name, row in rows.items():
            require(view.digest(LEGACY + name) == row["sha256"]
                    and view.members[LEGACY + name]["bytes"] == row["bytes"], "Pinned historical input differs")
    files, policies, common_source = {"TRAINING_SEAL.json": view.digest("run/TRAINING_SEAL.json"), **seal["files"]}, {}, None
    for seed in SEEDS:
        train = f"run/train/{seed}/"
        start, done = view.start(train, "train", seed, protocol), view.complete(train)
        require(start["scope"]["freeze_sha256"] == view.digest(training_freeze_name)
                and seal["model_seed_complete_sha256"][str(seed)] == view.digest(train + "COMPLETE.json"),
                "Original training freeze or sealed seed completion differs")
        for key, name in (("bank_sha256", f"bank/{seed}/BANK.json"),
                          ("controller_file_sha256", f"fit/{seed}/CONTROLLERS.json"),
                          ("reference_file_sha256", f"reference/{seed}/REFERENCE.json")):
            require(start["scope"][key] == view.digest(LEGACY + name), "Training input pin differs")
        verify_loaded_assets(view, train, seed, ["reward"], protocol, constants)
        require(done["schema"] == "hepta.field-bridge.v4.trained-seed.1" and done["seed"] == seed
                and done["study_id"] == protocol["study_id"] and done["scope"] == start["scope"]
                and done["source_roles"] == ADAPTATION and done["observer_names"] == ["reward"]
                and done["endpoint_accessed"] is False, "Trained seed identity differs")
        require(start["requested_roles"] == ADAPTATION and start["loaded_observer_names"] == ["reward"]
                and start["started_unix_ns"] < seal["sealed_unix_ns"], "Training access/chronology differs")
        view.phase_cost("train", seed, done["scope"], train + "COMPLETE.json", protocol)
        expected_paths = {f"{method}/schedule-{sid}" for method in METHODS for sid in SCHEDULES}
        require(set(done["paths"]) == expected_paths and done["methods"] == list(METHODS)
                and done["schedule_ids"] == list(SCHEDULES), "Trained path grid differs")
        evaluation = f"run/evaluate/{seed}/"
        eval_start, evaluated = view.start(evaluation, "evaluate", seed, protocol), view.complete(evaluation)
        verify_loaded_assets(view, evaluation, seed, ["reward", "audit"], protocol, constants)
        require(evaluated["schema"] == "hepta.field-bridge.v4.evaluated-seed.1" and evaluated["seed"] == seed
                and evaluated["study_id"] == protocol["study_id"] and evaluated["scope"] == eval_start["scope"]
                and evaluated["source_roles"] == ENDPOINTS and set(evaluated["paths"]) == expected_paths,
                "Evaluated seed identity differs")
        require(eval_start["requested_roles"] == ENDPOINTS and eval_start["loaded_observer_names"] == ["reward", "audit"]
                and eval_start["training_seal_sha256"] == evaluated["training_seal_sha256"]
                    == view.digest("run/TRAINING_SEAL.json")
                and eval_start["started_unix_ns"] > seal["sealed_unix_ns"], "Endpoint access/chronology differs")
        view.phase_cost("evaluate", seed, evaluated["scope"], evaluation + "COMPLETE.json", protocol)
        source = eval_start["source_files"]
        require(source.get("field_bridge_v4_20261027/qualification_analysis.py") ==
                view.digest(SCIENCE + "qualification_analysis.py"), "Analyzer is absent from recorded source closure")
        common_source = source if common_source is None else common_source
        exact(source, common_source, "same endpoint source closure")
        require(eval_start["scope"]["source_files_sha256"] == seal["scope"]["source_files_sha256"]
                == start["scope"]["source_files_sha256"], "Training/evaluation source closure changed")
        files.update({f"evaluate/{seed}/{name}": identity for name, identity in evaluated["files"].items()})
        files[f"evaluate/{seed}/COMPLETE.json"] = view.digest(evaluation + "COMPLETE.json")
        for relative in sorted(expected_paths):
            trained = view.complete(train + relative + "/")
            endpoint = view.complete(evaluation + relative + "/")
            require(trained["schema"] == "hepta.field-bridge.v4.trained-path.1"
                    and trained["study_id"] == protocol["study_id"] and trained["seed"] == seed
                    and trained["final_step"] == 288 and trained["endpoint_accessed"] is False
                    and relative == f"{trained['method']}/schedule-{trained['schedule_id']}"
                    and trained["policy_identity"]["scope"] == done["scope"], "Trained path identity differs")
            require(trained["policy_sha256"] == integrity.sha(canonical(trained["policy_identity"]))
                    == done["paths"][relative]["policy_sha256"]
                    and done["paths"][relative]["complete_sha256"] == view.digest(train + relative + "/COMPLETE.json"),
                    "Trained policy binding differs")
            require(endpoint["schema"] == "hepta.field-bridge.v4.evaluated-path.1"
                    and endpoint["study_id"] == protocol["study_id"] and endpoint["seed"] == seed
                    and relative == f"{endpoint['method']}/schedule-{endpoint['schedule_id']}"
                    and endpoint["policy_sha256"] == trained["policy_sha256"]
                    and endpoint["trained_checkpoint_sha256"] == trained["checkpoint"]["file_sha256"]
                        == view.digest(train + relative + "/checkpoint.pt")
                    and evaluated["paths"][relative] == view.digest(evaluation + relative + "/COMPLETE.json"),
                    "Endpoint policy/checkpoint binding differs")
            require(set(endpoint["files"]) == {"task.npz", "clean.npz"}, "Complete media inventory differs")
            policies[f"{seed}/{relative}"] = {"policy_sha256": endpoint["policy_sha256"],
                "trained_checkpoint_sha256": endpoint["trained_checkpoint_sha256"],
                "endpoint_receipt_sha256": evaluated["paths"][relative]}
    for phase in ("seal-training", "qualify"):
        name = f"run/{phase}/START.json"
        if name in view.selected:
            control_start = view.start(f"run/{phase}/", phase, None, protocol)
            completed = "run/" + ("TRAINING_SEAL.json" if phase == "seal-training" else "QUALIFICATION.json")
            view.phase_cost(phase, None, control_start["scope"], completed, protocol)
            require(control_start["requested_roles"] == [] and control_start["loaded_observer_names"] == [],
                    "Control phase unexpectedly loaded scientific roles or observers")
            if phase == "seal-training":
                exact(control_start["scope"], seal["scope"], "seal creation scope")
    return {"protocol_sha256": view.digest(SCIENCE + "PROTOCOL.json"),
        "training_seal_sha256": view.digest("run/TRAINING_SEAL.json"),
        "source_manifest_sha256": allocation["manifest_sha256"], "source_registry_sha256": allocation["registry_sha256"],
        "source_files_sha256": integrity.sha(canonical(common_source)), "source_files": common_source,
        "files": files, "paths": policies}
