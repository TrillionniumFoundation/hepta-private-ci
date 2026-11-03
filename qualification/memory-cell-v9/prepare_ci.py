"""Reconstruct frozen V9 transport over the existing pinned V7/V8 runtime."""

import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys


PROJECT = Path(__file__).resolve().parent


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def checked(root, name, expected, maximum):
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("invalid relative V9 transport path")
    path = root / relative
    if any(item.is_symlink() for item in (path, *path.parents)) or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("unsafe or oversized V9 transport")
    data = path.read_bytes()
    if identity(data) != {key: expected[key] for key in ("bytes", "sha256")}:
        raise ValueError("V9 transport bytes differ: " + name)
    return data


def main():
    output = Path(sys.argv[1])
    if not output.is_absolute() or any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError("absolute nonsymlink V9 preparation root required")
    request = json.loads((PROJECT / "VERIFY_REQUEST.json").read_bytes())
    subprocess.run([sys.executable, "-B", str(PROJECT.parent / "memory-cell-v8/prepare_ci.py"), str(output)], check=True)
    receipt = {"schema": "hepta.memory.v9.preparation.v1", "mode": request["mode"],
               "fitting_performed": False, "inference_requests": 0,
               "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True).strip(),
               "baseline_preparation": identity((output / "V8_PREPARATION.json").read_bytes())}
    if request["mode"] == "formal":
        source = PROJECT / "fixtures/address-model"
        index = json.loads((source / "PARTS.json").read_bytes())
        if index["schema"] != "hepta.memory.v9.model-transport.v1" or not 1 <= len(index["parts"]) <= 64:
            raise ValueError("unexpected V9 model transport")
        if len({part["path"] for part in index["parts"]}) != len(index["parts"]):
            raise ValueError("duplicate V9 model part")
        manifest = checked(source, "manifest.json", index["manifest"], 512000)
        decoded = json.loads(manifest)
        weights = b"".join(checked(source, part["path"], part, 400000) for part in index["parts"])
        if identity(weights) != {"bytes": decoded["weights_bytes"], "sha256": decoded["weights_sha256"]}:
            raise ValueError("reconstructed V9 model differs")
        fixture = checked(source, index["native_fixture"]["path"], index["native_fixture"], 512000)
        model = output / "v9-model"
        model.mkdir(exist_ok=False)
        (model / "manifest.json").write_bytes(manifest)
        (model / "weights.npz").write_bytes(weights)
        fixture_path = output / "v9-held-native-fixture.json"
        fixture_path.write_bytes(fixture)
        exported = {"MEMORY_CELL_V9_ADDRESS_MODEL_DIR": str(model),
                    "MEMORY_CELL_V9_ADDRESS_MODEL_DIGEST": index["manifest"]["sha256"],
                    "MEMORY_CELL_V9_NATIVE_FIXTURE": str(fixture_path),
                    "MEMORY_CELL_V9_NATIVE_FIXTURE_DIGEST": index["native_fixture"]["sha256"]}
        receipt.update(transport=identity((source / "PARTS.json").read_bytes()),
                       manifest=identity(manifest), weights=identity(weights), native_fixture=identity(fixture),
                       environment=exported, execution_mode="qualification shadow; no final-use grant")
        with (output / "github.env").open("a") as handle:
            handle.write("".join(f"{key}={value}\n" for key, value in exported.items()))
        with (output / "environment.sh").open("a") as handle:
            handle.write("".join(f"export {key}={shlex.quote(value)}\n" for key, value in exported.items()))
    elif request["mode"] != "development":
        raise ValueError("unknown verification mode")
    with (output / "V9_PREPARATION.json").open("x") as handle:
        handle.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
