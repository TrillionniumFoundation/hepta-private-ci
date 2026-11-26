"""Materialize exact, isolated source/evidence views without numerical imports."""

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile


FIRST = "qualification/hcsn_firstcycle_review/"
TORCH = "qualification/hcsn_adjoint_torch/"
ARCHIVE = "qualification/hcsn_initial_vjp/evidence/NUMPY001-ORIGINALS.tar.gz"
MANIFEST_SHA = "afcc90fb68730219a60a94a48e28c9169a060858c8b11b9be623b7f496c76de6"
BASELINE_SHA = "85e543dc770257e5470af867415d6d1f55e859fac116f37204fc0e5a6bb2348e"
BASELINE_ARRAY_SHA = "2dcfe03f2911cb0b6c55b2c24f095d7688d150eb84177d1bb7e4970daa8fa305"
UNMAPPED_FIRST_BLOBS = {
    FIRST + "verify_retained.py": "654549db8558b2f1ff8f4a9a7279a25b931d965b",
    FIRST + "evidence/attempt001/SUMMARY.json": "f7b9b9f3a61d1b7b1f2e4daca79b27e0accc91df",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def blob_digest(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def read_json(path):
    raw = path.read_bytes()
    require(len(raw) <= 2_000_000, "metadata/envelope exceeds fixed size cap")
    return json.loads(raw)


def relative_path(name):
    require(isinstance(name, str), "non-string source path")
    path = PurePosixPath(name)
    require(
        not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in name
        and str(path) == name,
        "noncanonical or escaping source path",
    )
    return path


def decode_profile(base, profile, entries):
    files, records = {}, []
    for entry in entries:
        name = entry["path"]
        relative_path(name)
        require(name not in files, "duplicate source path")
        blob = entry["git_blob_sha1"]
        require(re.fullmatch("[0-9a-f]{40}", blob), "invalid blob identity")
        envelope = read_json(base / "assets" / (blob + ".json"))
        require(envelope["git_blob_sha1"] == blob, "asset identity differs")
        if envelope["encoding"] == "base64":
            raw = base64.b64decode("".join(envelope["content"].split()), validate=True)
        elif envelope["encoding"] == "utf-8":
            raw = envelope["content"].encode("utf-8")
        else:
            raise ValueError("unsupported envelope encoding")
        require(len(raw) <= 2_000_000, "decoded asset exceeds fixed size cap")
        require(blob_digest(raw) == blob, "Git blob identity differs: " + name)
        actual = digest(raw)
        expected = entry["sha256"]
        if expected is None:
            require(
                profile == "firstcycle" and UNMAPPED_FIRST_BLOBS.get(name) == blob,
                "missing independent SHA256 pin outside two pinned metadata files",
            )
        else:
            require(actual == expected, "frozen SHA256 differs: " + name)
        files[name] = raw
        records.append(dict(entry, bytes=len(raw), sha256=actual))
    return files, records


def check_firstcycle(files):
    summary_path = FIRST + "evidence/attempt001/SUMMARY.json"
    for path, blob in UNMAPPED_FIRST_BLOBS.items():
        require(blob_digest(files[path]) == blob, "retained metadata identity differs")
    summary = json.loads(files[summary_path])
    require(summary["status"] == "HOLD_NO_GO" and summary["all_closed"] is False,
            "historical scientific status differs")
    require(summary["source_sha256_before"] == summary["source_sha256_after"],
            "historical source maps disagree")
    require(summary["retained_inputs_unchanged"] is True, "historical inputs changed")
    required = {}
    maps = ("source_sha256_before", "retained_execution_sources", "retained_input_sha256")
    require([len(summary[k]) for k in maps] == [2, 8, 8], "retained denominator differs")
    for key in maps:
        for old_path, expected in summary[key].items():
            require(old_path.count("/qualification/") == 1, "ambiguous retained path")
            name = "qualification/" + old_path.split("/qualification/", 1)[1]
            require(name not in required, "duplicate retained source/input")
            required[name] = expected
    require(set(summary["output_sha256"]) == {"REFERENCE.json", "ROWS.json"},
            "retained output set differs")
    for name, expected in summary["output_sha256"].items():
        required[FIRST + "evidence/attempt001/" + name] = expected
    require(set(files) == set(required) | set(UNMAPPED_FIRST_BLOBS),
            "retained isolated view is not the exact 22-file set")
    for name, expected in required.items():
        require(digest(files[name]) == expected, "original retained pin differs: " + name)
    return {"original_sha256_pins_matched": len(required), "input_pins_matched": 8,
            "original_git_blob_pins_matched": len(files), "numerical_verifier_executed": False,
            "scientific_status": "HOLD_NO_GO"}


def check_torch(files):
    manifest_path = TORCH + "TORCH-SOURCE.json"
    require(digest(files[manifest_path]) == MANIFEST_SHA, "current frozen manifest differs")
    manifest = json.loads(files[manifest_path])
    expected = manifest["source_sha256"]
    require(len(expected) == 10, "Torch frozen source denominator differs")
    require(manifest["new_torch_executions"] == 0 and manifest["status"] == "INTENT_NOT_EXECUTED",
            "Torch original registration status differs")
    require(set(files) == set(expected) | {manifest_path, ARCHIVE}, "Torch view is not exact")
    request = json.loads(files[TORCH + "TORCH-REQUEST.json"])
    require(set(request["source_paths"]) == set(expected), "request source set differs")
    for name, sha in expected.items():
        require(digest(files[name]) == sha, "original Torch pin differs: " + name)
    require(digest(files[ARCHIVE]) == BASELINE_SHA, "baseline archive identity differs")
    with tarfile.open(fileobj=io.BytesIO(files[ARCHIVE]), mode="r:gz") as archive:
        members = [m for m in archive.getmembers() if m.name.endswith("numpy001/ARRAYS.npz")]
        require(len(members) == 1 and members[0].isfile(), "baseline array member differs")
        require(members[0].size <= 32_000_000, "baseline array size exceeds fixed cap")
        handle = archive.extractfile(members[0])
        require(handle is not None, "baseline array cannot be read")
        with handle:
            raw = handle.read(32_000_001)
        require(len(raw) == members[0].size and digest(raw) == BASELINE_ARRAY_SHA,
                "original NumPy baseline array bytes differ")
    return {"original_source_pins_matched": 10, "prefrozen_inventory_sha256": MANIFEST_SHA,
            "baseline_archive_sha256": BASELINE_SHA, "baseline_arrays_sha256": BASELINE_ARRAY_SHA,
            "native_probe_executed": False, "scientific_status": "INTENT_NOT_EXECUTED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    assembly_path = base / "ASSEMBLY.json"
    assembly = read_json(assembly_path)
    require(assembly["schema"] == "hcsn-isolated-frozen-views-v1", "assembly schema differs")
    profiles = assembly["profiles"]
    require(set(profiles) == {"firstcycle", "torch"}, "profile set differs")
    require({k: len(v) for k, v in profiles.items()} == {"firstcycle": 22, "torch": 12},
            "fixed file denominators differ")
    decoded, records = {}, {}
    for profile, entries in profiles.items():
        decoded[profile], records[profile] = decode_profile(base, profile, entries)
    checks = {"firstcycle": check_firstcycle(decoded["firstcycle"]),
              "torch": check_torch(decoded["torch"])}
    output = args.output.expanduser().resolve()
    output.mkdir(parents=False, exist_ok=False)
    for profile, files in decoded.items():
        for name, raw in files.items():
            path = output / profile / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:
                handle.write(raw)
            path.chmod(0o444)
            require(path.read_bytes() == raw, "materialized bytes differ")
    index = {"schema": "hcsn-isolated-frozen-views-materialized-v1",
             "status": "BYTE_BINDING_PASS_NUMERICS_NOT_RUN", "mixed_source_assembly": True,
             "assembly_sha256": digest(assembly_path.read_bytes()),
             "materializer_sha256": digest(Path(__file__).read_bytes()),
             "profiles": records, "checks": checks, "production_source_overwrites": 0,
             "original_manifest_edits": 0, "npz_array_loads": 0,
             "new_model_calls": 0, "new_oracle_calls": 0, "new_training_calls": 0}
    with (output / "INDEX.json").open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(index, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": index["status"], "checks": checks}, sort_keys=True))


if __name__ == "__main__":
    main()
