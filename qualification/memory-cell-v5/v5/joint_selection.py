"""Bind selected numerical models and their selection evidence before held access."""

import json
from .config import CANDIDATES
from .contracts import canonical, file_identity, sha256
from .joint_binding import PROJECT, SEEDS, immutable_path, relative_path
from .metrics import primary_key
from .router import Router, parameter_digest


SEALED_ROUTER_FIELDS = ("files", "candidate", "training_identity", "selection_receipt_sha256",
                        "primary_sha256", "candidates_sha256", "training_source_sha256")


def selection_evidence(path, manifest, files, router, seed, source_commit, frozen_source_files):
    if path.name != "selected" or path.parent.name != f"seed-{seed}":
        raise ValueError("formal selected model must retain its declared seed directory")
    seed_path, training_path = path.parent, path.parent.parent
    name = manifest["candidate"]["name"]
    if relative_path(name).name != name:
        raise ValueError("unsafe candidate name")
    paths = {"selection_receipt": seed_path / "candidate-diagnostics" / name / "RECEIPT.json",
             "primary": seed_path / "PRIMARY.json", "candidates": seed_path / "CANDIDATES.json",
             "training_source": training_path / "SOURCE.json"}
    values, identities = {}, {}
    for key, value in paths.items():
        item = immutable_path(value)
        raw = item.read_bytes()
        values[key] = json.loads(raw)
        identities[key + "_sha256"] = sha256(raw)
    source = values["training_source"]
    if source["source_commit"] != source_commit or source["development"] is not False:
        raise ValueError("selected model was not produced by the declared formal source")
    if not isinstance(frozen_source_files, dict) or not source["files"]:
        raise ValueError("formal selection requires the complete frozen source inventory")
    for relative, identity in source["files"].items():
        relative_path(relative)
        if frozen_source_files.get(relative) != identity:
            raise ValueError("model training source differs from the frozen source: " + relative)
    training = manifest["training_identity"]
    if training["source_inventory_sha256"] != sha256(canonical(source["files"])):
        raise ValueError("manifest does not bind the actual training source inventory")
    candidates = values["candidates"]
    configurations = {candidate["name"]: candidate for candidate in CANDIDATES}
    if not isinstance(candidates, list) or len(candidates) != len(configurations) or {row["name"] for row in candidates} != set(configurations):
        raise ValueError("formal candidate evidence omits or adds a declared fit")
    for row in candidates:
        if row["candidate"] != configurations[row["name"]] or row["seed"] != seed:
            raise ValueError("candidate receipt configuration or seed differs")
        identity = row["training_identity"]
        if identity["seed"] != seed or identity["source_commit"] != source_commit or identity["source_inventory_sha256"] != training["source_inventory_sha256"]:
            raise ValueError("candidate training identities are not from one frozen run")
    receipt = values["selection_receipt"]
    if min(candidates, key=primary_key) != receipt or receipt["name"] != name:
        raise ValueError("selected candidate is not the frozen selection-rule minimum")
    if receipt["candidate"] != manifest["candidate"] or receipt["training_identity"] != training or receipt["calibration"] != manifest["calibration"]:
        raise ValueError("selected manifest differs from its actual selection receipt")
    artifact = {"files": files, "bytes": sum(item["bytes"] for item in files.values()),
                "parameter_bytes": router.numeric_parameter_bytes()}
    if receipt["artifact"] != artifact or receipt["parameter_digest"] != parameter_digest(router):
        raise ValueError("selected model state differs from the actual fitted candidate")
    primary = values["primary"]
    if primary["schema"] != "memory-cell-v5.primary-router.v1" or primary["seed"] != seed or primary["selected_using_new_held"] is not False:
        raise ValueError("primary selection boundary differs")
    if primary["candidate"] != name or any(primary[key] != receipt[key] for key in
            ("calibration", "artifact", "parameter_digest", "selection", "development_diagnostic_only")):
        raise ValueError("PRIMARY does not bind the exact selected artifact and decision")
    return identities


def selected_identity(directory, *, expected_seed=None, expected_source_commit=None, frozen_source_files=None):
    path = immutable_path(directory)
    manifest_path = immutable_path(path / "manifest.json")
    manifest = json.loads(manifest_path.read_bytes())
    training = manifest["training_identity"]
    if expected_seed is not None and (type(training["seed"]) is not int or training["seed"] != expected_seed):
        raise ValueError("selected router training seed differs from declared model mapping")
    if expected_source_commit is not None and training.get("source_commit") != expected_source_commit:
        raise ValueError("selected router training source differs from the formal freeze")
    names = ["manifest.json", *manifest["files"]]
    if len(set(names)) != len(names) or any(relative_path(name).name != name for name in names):
        raise ValueError("selected router files must be unique direct children")
    actual = list(path.iterdir())
    if {item.name for item in actual} != set(names) or any(not item.is_file() for item in actual):
        raise ValueError("selected directory has an unbound or missing state file")
    files = {name: file_identity(immutable_path(path / name)) for name in names}
    if {name: files[name] for name in manifest["files"]} != manifest["files"]:
        raise ValueError("selected payload file identities differ from its manifest")
    router = Router.load(path, expected_manifest_sha256=files["manifest.json"]["sha256"])
    evidence = {}
    if expected_source_commit is not None:
        evidence = selection_evidence(path, manifest, files, router, expected_seed, expected_source_commit, frozen_source_files)
    return {"directory": str(path), "files": files, "serialized_bytes": sum(info["bytes"] for info in files.values()),
            "numeric_parameter_bytes": manifest["numeric_parameter_bytes"], "candidate": manifest["candidate"],
            "calibration": manifest["calibration"], "training_identity": training, **evidence}


def verify_selected_models(router_directories, frozen, freeze_identity):
    if set(router_directories) != set(SEEDS):
        raise ValueError("exactly the five frozen selected router directories are required")
    seal_path = immutable_path(PROJECT / "SELECTED_MODELS.json")
    raw = seal_path.read_bytes()
    seal = json.loads(raw)
    if seal["schema"] != "hepta.memory.v5.selected-before-held.v1" or seal["source_commit"] != frozen["source_commit"] or seal["freeze_sha256"] != freeze_identity["sha256"] or seal["held_opened"] is not False:
        raise ValueError("selected-model seal does not precede this frozen held evaluation")
    if seal["assets_binding_sha256"] != frozen["assets_binding_sha256"] or set(seal["routers"]) != {str(seed) for seed in SEEDS}:
        raise ValueError("selected-model seal asset or seed scope differs")
    selected = {}
    for seed in SEEDS:
        identity = selected_identity(router_directories[seed], expected_seed=seed,
                                     expected_source_commit=frozen["source_commit"], frozen_source_files=frozen["source_files"])
        if seal["routers"][str(seed)] != {key: identity[key] for key in SEALED_ROUTER_FIELDS}:
            raise ValueError("selected numerical state or selection evidence differs from its pre-held seal")
        selected[seed] = identity
    if seal_path.read_bytes() != raw:
        raise ValueError("selected-model seal changed during admission")
    return selected, {"bytes": len(raw), "sha256": sha256(raw)}
