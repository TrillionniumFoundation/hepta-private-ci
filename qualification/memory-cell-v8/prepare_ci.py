"""Prepare exact V8 transport over the existing pinned Python/encoder profile."""

import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys


PROJECT = Path(__file__).resolve().parent


def identity(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def checked(root, name, expected, maximum):
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("invalid relative transport path")
    path = root / relative
    if any(item.is_symlink() for item in (path, *path.parents)) or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("unsafe or oversized transport file")
    data = path.read_bytes()
    if len(data) != expected["bytes"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
        raise ValueError("transport identity differs: " + name)
    return data


def main():
    output = Path(sys.argv[1])
    if not output.is_absolute() or any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError("absolute nonsymlink preparation path required")
    subprocess.run([sys.executable, "-B", str(PROJECT.parent / "memory-cell-v7/prepare_language_ci.py"), str(output)], check=True)
    source = PROJECT / "fixtures/address-model"
    index = json.loads((source / "PARTS.json").read_text())
    if index["schema"] != "hepta.memory.v8.model-transport.v1" or not 1 <= len(index["parts"]) <= 64:
        raise ValueError("unexpected V8 transport")
    if len({part["path"] for part in index["parts"]}) != len(index["parts"]):
        raise ValueError("duplicate V8 transport part")
    manifest = checked(source, "manifest.json", index["manifest"], 512_000)
    weights = b"".join(checked(source, part["path"], part, 400_000) for part in index["parts"])
    decoded = json.loads(manifest)
    if (len(weights), hashlib.sha256(weights).hexdigest()) != (decoded["weights_bytes"], decoded["weights_sha256"]):
        raise ValueError("V8 reconstructed weights differ")
    fixture = checked(source, index["native_fixture"]["path"], index["native_fixture"], 512_000)
    model = output / "v8-model"
    model.mkdir(exist_ok=False)
    (model / "manifest.json").write_bytes(manifest)
    (model / "weights.npz").write_bytes(weights)
    fixture_path = output / "v8-held-native-fixture.json"
    fixture_path.write_bytes(fixture)
    exported = {"MEMORY_CELL_V8_ADDRESS_MODEL_DIR": str(model),
                "MEMORY_CELL_V8_ADDRESS_MODEL_DIGEST": index["manifest"]["sha256"],
                "MEMORY_CELL_V8_NATIVE_FIXTURE": str(fixture_path),
                "MEMORY_CELL_V8_NATIVE_FIXTURE_DIGEST": index["native_fixture"]["sha256"]}
    receipt = {"schema": "hepta.memory.v8.preparation.v1", "source_commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True).strip(),
        "transport": identity(source / "PARTS.json"), "manifest": identity(model / "manifest.json"),
        "weights": identity(model / "weights.npz"), "native_fixture": identity(fixture_path),
        "legacy_preparation": identity(output / "PREPARATION.json"), "environment": exported,
        "fitting_performed": False, "inference_requests": 0,
        "candidate_serving_admitted": decoded["calibration"]["empirical_gate_passed"],
        "native_v8_evaluation_mode": "qualification shadow; no final-use grant"}
    (output / "V8_PREPARATION.json").write_text(json.dumps(receipt, indent=2) + "\n")
    with (output / "github.env").open("a") as handle:
        handle.write("".join(f"{key}={value}\n" for key, value in exported.items()))
    with (output / "environment.sh").open("a") as handle:
        handle.write("".join(f"export {key}={shlex.quote(value)}\n" for key, value in exported.items()))
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
