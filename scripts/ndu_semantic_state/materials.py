"""Byte and role admission for real text/image experiment materials.

The independently pinned source-use registry must come from the experiment
owner, not from a digest chosen inside the incoming manifest. Decoding an image
does not establish that it is natural, semantically relevant, or independent.
Consequently a successful check qualifies integrity only; scientific admission
remains HOLD until real model execution and independent task evaluation exist.
"""

from collections import Counter, defaultdict
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat

from PIL import Image
import numpy as np

from .state import exact_fields, integer, sha256_value


SCHEMA = "hepta.text-image-materials.v1"
REGISTRY_SCHEMA = "hepta.source-use-registry.v2"
TASK_FAMILIES = (
    "text_sufficient", "text_image_complementary", "selective_refinement",
    "preparation_required", "continuation_not_worthwhile",
)
SPLITS = ("train", "development", "confirmation", "retention")
MODEL_ROLES = ("text_encoder", "image_encoder", "text_decoder", "image_decoder", "ordinary_core", "hepta_core")


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{label}: expected nonempty text")
    return value


def _strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError(f"Nonfinite JSON value {value}")
    return json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=pairs, parse_constant=nonfinite)


def _open_relative(root, relative):
    """Open the exact regular file without following a component symlink."""
    if not isinstance(relative, str) or "\\" in relative:
        raise ValueError("Material path must be a canonical relative POSIX path")
    path = PurePosixPath(relative)
    if path.is_absolute() or str(path) != relative or not path.parts or any(p in {".", ".."} for p in path.parts):
        raise ValueError("Material path escapes or is not canonical")
    if any(not hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK")):
        raise ValueError("This verifier requires no-follow directory-descriptor support")
    descriptor = os.open(Path(root).resolve(strict=True), os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor); descriptor = child
        file_descriptor = os.open(path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
    finally:
        os.close(descriptor)
    if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
        os.close(file_descriptor)
        raise ValueError("Material is not a regular file")
    return os.fdopen(file_descriptor, "rb")


def _read(root, path, limit, *, retain=True):
    digest, parts, length = hashlib.sha256(), [], 0
    with _open_relative(root, path) as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > limit:
            raise ValueError("Material exceeds the declared verification byte bound")
        while block := stream.read(1024 * 1024):
            length += len(block)
            if length > limit:
                raise ValueError("Material grew beyond the verification byte bound")
            digest.update(block)
            if retain:
                parts.append(block)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("Material changed during verification")
    return b"".join(parts), digest.hexdigest(), length


def check_file(root, binding, *, limit, retain=True):
    exact_fields(binding, ("path", "sha256", "bytes"), "file binding")
    expected = sha256_value(binding["sha256"], "file sha256")
    count = integer(binding["bytes"], "file bytes", limit)
    data, digest, length = _read(root, binding["path"], limit, retain=retain)
    if digest != expected or length != count:
        raise ValueError(f"Material byte binding differs: {binding['path']}")
    return data


def _decode_text(data):
    return _text(data.decode("utf-8", errors="strict"), "source text")


def _decode_image(data):
    with Image.open(io.BytesIO(data)) as image:
        if image.format not in {"PNG", "JPEG", "WEBP"} or getattr(image, "n_frames", 1) != 1:
            raise ValueError("Expected a single PNG/JPEG/WEBP image")
        if image.width < 1 or image.height < 1 or image.width * image.height > 16_000_000:
            raise ValueError("Image dimensions outside the verification profile")
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        result = np.asarray(image.convert("RGB")).copy()
    result.setflags(write=False)
    return result


def load_public_case(root, case):
    """Expose only current UTF-8 text and RGB pixels, never references or roles."""
    text = check_file(root, case["text"], limit=1024 * 1024)
    image = check_file(root, case["image"], limit=32 * 1024 * 1024)
    return {"text": _decode_text(text), "image_rgb": _decode_image(image)}


def validate_materials(root, manifest_path, registry_path, *, expected_registry_sha256, stage="development"):
    """Verify immutable bytes and original roles without running or training models.

    The return is a gate input, not a semantic PASS. ``real=true`` is not an
    accepted field, and even complete byte verification leaves research HOLD.
    """
    if stage not in {"development", "confirmation"}:
        raise ValueError("Unknown study stage")
    expected_registry_sha256 = sha256_value(expected_registry_sha256, "external registry pin")
    manifest_raw, manifest_digest, _ = _read(root, manifest_path, 8 * 1024 * 1024)
    registry_raw, registry_digest, _ = _read(root, registry_path, 8 * 1024 * 1024)
    if registry_digest != expected_registry_sha256:
        raise ValueError("Source-use registry differs from its external owner pin")
    manifest, registry = _strict_json(manifest_raw), _strict_json(registry_raw)
    exact_fields(manifest, ("schema", "experiment_id", "registry_sha256", "cases", "models"), "material manifest")
    if manifest["schema"] != SCHEMA or manifest["registry_sha256"] != registry_digest:
        raise ValueError("Manifest schema or source-use registry binding differs")
    _text(manifest["experiment_id"], "experiment id")
    exact_fields(registry, ("schema", "sources"), "source-use registry")
    if registry["schema"] != REGISTRY_SCHEMA or not isinstance(registry["sources"], list):
        raise ValueError("Invalid source-use registry")
    sources, registered_cases, historical_image_roles = {}, {}, {}
    for row in registry["sources"]:
        exact_fields(row, ("source_id", "source_family", "allowed_split", "text_sha256s", "image_sha256s",
                           "source_evidence_sha256", "used_in_training", "previously_observed", "case_bindings"), "source-use row")
        source_id = _text(row["source_id"], "source id")
        if source_id in sources or row["allowed_split"] not in SPLITS:
            raise ValueError("Duplicate source id or unknown original role")
        _text(row["source_family"], "source family")
        sha256_value(row["source_evidence_sha256"], "source evidence pin")
        for field in ("text_sha256s", "image_sha256s"):
            if not isinstance(row[field], list) or not row[field] or len(set(row[field])) != len(row[field]):
                raise ValueError("Source byte identities must be nonempty unique lists")
            for value in row[field]:
                sha256_value(value, field)
        if any(type(row[name]) is not bool for name in ("used_in_training", "previously_observed")):
            raise ValueError("Source exposure history must be explicit")
        if row["allowed_split"] == "confirmation" and (row["used_in_training"] or row["previously_observed"]):
            raise ValueError("A previously consumed source cannot become fresh confirmation")
        # Inspect the entire pinned history, including sources omitted from the
        # current case selection. New source IDs cannot erase exposure of bytes.
        for image_hash in row["image_sha256s"]:
            if image_hash in historical_image_roles and historical_image_roles[image_hash] != row["allowed_split"]:
                raise ValueError("The same image bytes cross source-role boundaries in the full registry")
            historical_image_roles[image_hash] = row["allowed_split"]
        if not isinstance(row["case_bindings"], list):
            raise ValueError("Owner registry must bind case inputs and evaluation references")
        for binding in row["case_bindings"]:
            exact_fields(binding, ("case_id", "task_family", "text_sha256", "image_sha256", "reference_sha256"), "owner case binding")
            case_id = _text(binding["case_id"], "owner case id")
            if case_id in registered_cases or binding["task_family"] not in TASK_FAMILIES:
                raise ValueError("Duplicate owner case id or unknown task family")
            for field in ("text_sha256", "image_sha256", "reference_sha256"):
                sha256_value(binding[field], field)
            if binding["text_sha256"] not in row["text_sha256s"] or binding["image_sha256"] not in row["image_sha256s"]:
                raise ValueError("Owner case binding uses bytes outside its source record")
            registered_cases[case_id] = (source_id, binding)
        sources[source_id] = row
    if not isinstance(manifest["cases"], list) or not manifest["cases"]:
        raise ValueError("No source cases")
    case_ids, seen_sources, image_roles = set(), {}, {}
    families, source_families, counts = defaultdict(set), defaultdict(set), Counter()
    for case in manifest["cases"]:
        exact_fields(case, ("id", "source_id", "source_family", "split", "task_family",
                            "text", "image", "reference", "source_evidence"), "case")
        identity = _text(case["id"], "case id")
        if identity in case_ids or case["split"] not in SPLITS or case["task_family"] not in TASK_FAMILIES:
            raise ValueError("Duplicate case or unregistered split/task family")
        case_ids.add(identity)
        row = sources.get(case["source_id"])
        if row is None or row["source_family"] != case["source_family"] or row["allowed_split"] != case["split"]:
            raise ValueError("Case reassigns or invents a source role")
        for field in ("text", "image", "reference", "source_evidence"):
            exact_fields(case[field], ("path", "sha256", "bytes"), "case file binding")
        expected_case = {"case_id": identity, "task_family": case["task_family"],
                         "text_sha256": case["text"]["sha256"], "image_sha256": case["image"]["sha256"],
                         "reference_sha256": case["reference"]["sha256"]}
        if registered_cases.get(identity) != (case["source_id"], expected_case):
            raise ValueError("Case inputs or evaluation reference differ from the original owner case binding")
        if (case["text"]["sha256"] not in row["text_sha256s"] or case["image"]["sha256"] not in row["image_sha256s"]
                or case["source_evidence"]["sha256"] != row["source_evidence_sha256"]):
            raise ValueError("Case bytes or acquisition evidence differ from the source registry")
        seen_sources.setdefault(case["source_id"], case["split"])
        image_hash = case["image"]["sha256"]
        if image_hash in image_roles and image_roles[image_hash] != case["split"]:
            raise ValueError("The same image bytes cross source-role boundaries")
        image_roles[image_hash] = case["split"]
        load_public_case(root, case)
        check_file(root, case["reference"], limit=2 * 1024 * 1024, retain=False)
        check_file(root, case["source_evidence"], limit=2 * 1024 * 1024, retain=False)
        families[case["split"]].add(case["task_family"])
        source_families[case["split"]].add(case["source_family"])
        counts[case["split"]] += 1
    required_splits = ("train", "development", "confirmation") if stage == "confirmation" else ("train", "development")
    for split in required_splits:
        if families[split] != set(TASK_FAMILIES):
            raise ValueError(f"Missing one or more registered task families in {split}")
    if not counts["retention"]:
        raise ValueError("No frozen old-capability retention set")
    if not isinstance(manifest["models"], list):
        raise ValueError("No model material list")
    roles, model_ids, declared_parameters = set(), set(), {}
    for model in manifest["models"]:
        exact_fields(model, ("id", "role", "architecture", "weights", "config", "executable", "parameter_count"), "model")
        identity = _text(model["id"], "model id")
        if identity in model_ids or model["role"] not in MODEL_ROLES or model["role"] in roles:
            raise ValueError("Duplicate model identity/role or unknown role")
        model_ids.add(identity); roles.add(model["role"])
        _text(model["architecture"], "architecture")
        declared_parameters[model["role"]] = integer(model["parameter_count"], "parameter count", 2**53 - 1)
        if not isinstance(model["weights"], list) or not model["weights"]:
            raise ValueError("No actual model weight binding")
        for binding in model["weights"]:
            if binding.get("bytes", 0) == 0:
                raise ValueError("Empty weights do not identify a content model")
            check_file(root, binding, limit=64 * 1024**3, retain=False)
        check_file(root, model["config"], limit=4 * 1024 * 1024, retain=False)
        check_file(root, model["executable"], limit=2 * 1024**3, retain=False)
    if roles != set(MODEL_ROLES):
        raise ValueError("Both modality encoders/decoders and both core bindings are required")
    overlap = {a + "__" + b: sorted(source_families[a] & source_families[b])
               for a, b in (("train", "confirmation"), ("development", "confirmation"), ("train", "retention"))}
    return {"schema": "hepta.text-image-material-check.v1", "experiment_id": manifest["experiment_id"],
            "manifest_sha256": manifest_digest, "registry_sha256": registry_digest,
            "registry_schema": REGISTRY_SCHEMA, "owner_case_bindings_verified": True,
            "full_registry_image_roles_verified": True,
            "integrity_status": "VERIFIED", "case_counts": dict(counts), "source_count": len(seen_sources),
            "source_role_bytes_verified": True, "old_capability_set_bound": True,
            "task_families_declared": {key: sorted(value) for key, value in families.items()},
            "source_family_overlaps": overlap, "declared_parameter_counts_unverified": declared_parameters,
            "model_execution_verified": False, "natural_semantic_provenance_verified": False,
            "independent_task_evaluation_verified": False, "scientific_admission": False,
            "research_status": "HOLD", "new_training_started": False}
