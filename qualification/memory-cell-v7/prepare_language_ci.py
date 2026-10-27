"""Prepare the frozen language-worker CI profile without fitting or querying it.

Run with Python 3.12: python prepare_language_ci.py /absolute/output/directory
Append output/github.env to GITHUB_ENV, or source output/environment.sh.
--model-only checks and reconstructs the repository transport without downloads.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.request
import venv


PROJECT = Path(__file__).resolve().parent
MANIFEST_SHA256 = "90c231694a32addf7ba63492649eb97d69081edf65900a272dbcd611db599be0"
PARTS_SHA256 = "d2d138eec898b43d2f0149b722a6f052dbc999b25359a645938ced818cc863cb"
ENCODER_SOURCE_SHA256 = "6db659cdc0a0ae7b57dd45da6d210e85cc81d0f91f6fc75822146c2dc644b0e5"
FORMAL_PYTHON = "3.12.14"
PIP_VERSION = "25.0.1"
# The five numeric/runtime versions are TRAINING.json source.versions at formal
# source commit f445e938a11a050006a721ff2b6c1a1b2b41d4e0. The remaining versions
# are their complete dependency closure observed in that same training venv.
PACKAGES = {
    "anyio": "4.15.1", "certifi": "2026.10.19", "click": "8.5.0",
    "coloredlogs": "15.0.1", "filelock": "4.2.4", "flatbuffers": "25.12.19",
    "fsspec": "2026.9.0", "h11": "0.16.0", "hf-xet": "1.7.0",
    "httpcore": "1.0.9", "httpx": "0.28.1", "huggingface-hub": "1.33.0",
    "humanfriendly": "10.0", "idna": "3.19", "joblib": "1.5.3",
    "mpmath": "1.3.0", "numpy": "2.3.5", "onnxruntime": "1.23.2",
    "packaging": "26.3", "protobuf": "7.36.2", "pyyaml": "6.0.3",
    "scikit-learn": "1.8.0", "scipy": "1.17.0", "sympy": "1.14.0",
    "threadpoolctl": "3.6.0", "tokenizers": "0.22.1", "tqdm": "4.70.1",
    "typing-extensions": "4.16.0",
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_path(value):
    path = Path(os.path.abspath(value))
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("symlinked preparation path: " + str(path))
    if any(char in str(path) for char in ("\n", "\r", "\0")):
        raise ValueError("control character in preparation path")
    return path


def component(root, name):
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("invalid artifact component")
    return safe_path(root / relative)


def checked_bytes(path, expected_sha256, expected_bytes=None, maximum=8_000_000):
    path = safe_path(path)
    if not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("missing or oversized artifact: " + str(path))
    raw = path.read_bytes()
    if digest(raw) != expected_sha256 or (expected_bytes is not None and len(raw) != expected_bytes):
        raise ValueError("artifact bytes/hash differ: " + str(path))
    return raw


def publish_file(path, raw):
    """Existing files must agree; incomplete work never replaces a valid asset."""
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        checked_bytes(path, digest(raw), len(raw), maximum=max(len(raw), 1))
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".preparing-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            # No replace: concurrent preparations must not overwrite each other.
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def reconstruct_model(source, output):
    source, output = safe_path(source), safe_path(output)
    raw_manifest = checked_bytes(source / "manifest.json", MANIFEST_SHA256)
    manifest = json.loads(raw_manifest)
    transport = json.loads(checked_bytes(source / "PARTS.json", PARTS_SHA256))
    encoder_raw = checked_bytes(source / "encoder-source.json", ENCODER_SOURCE_SHA256, maximum=65536)
    encoder = json.loads(encoder_raw)
    if transport["schema"] != "hepta.memory.v7.model-transport.v1" or transport["manifest_sha256"] != MANIFEST_SHA256:
        raise ValueError("unexpected frozen model transport")
    weights = b"".join(checked_bytes(component(source, part["path"]), part["sha256"], part["bytes"])
                       for part in transport["parts"])
    if any((manifest[key], transport[key]) != (expected, expected) for key, expected in
           (("weights_sha256", digest(weights)), ("weights_bytes", len(weights)))):
        raise ValueError("reconstructed model weights differ")
    policy = {name: digest((PROJECT / "addressing" / name).read_bytes()) for name in
              ("model.py", "capabilities.py", "contracts.py", "planner.py")}
    if digest(canonical(policy)) != manifest["policy_digest"]:
        raise ValueError("current worker policy differs from frozen model")
    identity = {"source_sha256": digest(canonical(encoder)), "dimension": 384,
                "pooling": "masked-mean-l2", "native_batch": 1, "max_tokens": 128}
    if digest(canonical(identity)) != manifest["encoder_digest"]:
        raise ValueError("encoder source differs from frozen model")
    if len(encoder_raw) + sum(item["bytes"] for item in encoder["files"].values()) != manifest["encoder_bytes"]:
        raise ValueError("encoder byte inventory differs")
    publish_file(output / "model" / "manifest.json", raw_manifest)
    publish_file(output / "model" / "weights.npz", weights)
    return manifest, encoder, encoder_raw, policy


def download_encoder(root, source, source_raw):
    root = safe_path(root)
    for name, binding in sorted(source["files"].items()):
        path = component(root, name)
        if path.exists():
            checked_bytes(path, binding["sha256"], binding["bytes"], maximum=binding["bytes"])
            continue
        expected_url = "https://huggingface.co/{}/resolve/{}/{}".format(source["repo"], source["revision"], name)
        if binding["url"] != expected_url:
            raise ValueError("encoder URL differs from fixed revision")
        path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(3):
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".download-", delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    sha, count = hashlib.sha256(), 0
                    with urllib.request.urlopen(expected_url, timeout=60) as response:
                        while chunk := response.read(min(1_048_576, binding["bytes"] + 1 - count)):
                            count += len(chunk)
                            if count > binding["bytes"]:
                                raise ValueError("oversized encoder download")
                            stream.write(chunk)
                            sha.update(chunk)
                    if count != binding["bytes"] or sha.hexdigest() != binding["sha256"]:
                        raise ValueError("downloaded encoder bytes/hash differ: " + name)
                    stream.flush()
                    os.fsync(stream.fileno())
                    os.link(temporary, path)
                    break
                except OSError:
                    if attempt == 2:
                        raise
                    time.sleep(attempt + 1)
                finally:
                    temporary.unlink(missing_ok=True)
        print(json.dumps({"encoder_file": name, "bytes": binding["bytes"], "sha256": binding["sha256"]}), flush=True)
    publish_file(root / "source.json", source_raw)


def prepare_python(output):
    root = safe_path(output / "venv")
    python = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        venv.EnvBuilder(with_pip=True, symlinks=False).create(root)
    python = safe_path(python)
    requirements = "".join(f"{name}=={version}\n" for name, version in sorted(PACKAGES.items())).encode()
    publish_file(output / "requirements.txt", requirements)
    pip = [str(python), "-I", "-m", "pip", "--isolated", "--disable-pip-version-check", "--no-cache-dir"]
    subprocess.run([*pip, "install", "--only-binary=:all:", "--no-deps", "--index-url", "https://pypi.org/simple",
                    f"pip=={PIP_VERSION}"], check=True)
    subprocess.run([*pip, "install", "--only-binary=:all:", "--no-deps", "--index-url", "https://pypi.org/simple",
                    "--report", str(output / "pip-install.json"), "-r", str(output / "requirements.txt")], check=True)
    subprocess.run([*pip, "check"], check=True)
    command = "import importlib.metadata as m,json,platform,sys; print(json.dumps({'python':platform.python_version(),'versions':{n:m.version(n) for n in json.loads(sys.argv[1])}}))"
    installed = json.loads(subprocess.check_output([str(python), "-I", "-c", command, json.dumps(sorted(PACKAGES))]))
    if installed["versions"] != PACKAGES or not installed["python"].startswith("3.12."):
        raise ValueError("prepared Python or package versions differ")
    return python, installed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model-source", type=Path, default=PROJECT / "fixtures/address-model")
    parser.add_argument("--model-only", action="store_true", help="offline model transport verification only; emits no runtime environment")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error("the recorded runtime profile requires Python 3.12 (formal patch was 3.12.14)")
    output = safe_path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    manifest, encoder, encoder_raw, policy = reconstruct_model(args.model_source, output)
    if args.model_only:
        print(json.dumps({"schema": "hepta.memory.v7.model-preparation.v1", "manifest_sha256": MANIFEST_SHA256,
                          "weights_sha256": manifest["weights_sha256"], "runtime_prepared": False}))
        return
    python, installed = prepare_python(output)
    download_encoder(output / "encoder", encoder, encoder_raw)
    environment = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    warmed = subprocess.run([str(python), "-I", "-u", "-B", str(PROJECT / "addressing/worker.py"),
                             "--model", str(output / "model"), "--model-digest", MANIFEST_SHA256,
                             "--encoder", str(output / "encoder")], input=b"", capture_output=True,
                            env=environment, timeout=60, check=True)
    if warmed.stdout or len(warmed.stderr) > 65536:
        raise ValueError("unexpected worker prewarm output")
    ready = json.loads(warmed.stderr)
    if (ready.get("schema"), ready.get("model_digest"), ready.get("policy_digest")) != (
            "hepta.memory.v7.address-worker-ready.v1", MANIFEST_SHA256, manifest["policy_digest"]):
        raise ValueError("worker did not load the frozen model and policy")
    exported = {
        "MEMORY_CELL_TRAINING_PYTHON": str(python),
        "MEMORY_CELL_ADDRESS_MODEL_DIR": str(output / "model"),
        "MEMORY_CELL_ADDRESS_MODEL_DIGEST": MANIFEST_SHA256,
        "MEMORY_CELL_ADDRESS_ENCODER_DIR": str(output / "encoder"),
        "MEMORY_CELL_LANGUAGE_RECEIPT_PATH": str(output / "language-runtime-receipt.json"),
    }
    receipt = {"schema": "hepta.memory.v7.language-ci-preparation.v1", "formal_python": FORMAL_PYTHON,
               "runtime": installed, "platform": platform.platform(), "environment": exported,
               "manifest_sha256": MANIFEST_SHA256, "weights_sha256": manifest["weights_sha256"],
               "transport_sha256": PARTS_SHA256, "encoder_source_sha256": ENCODER_SOURCE_SHA256,
               "encoder_revision": encoder["revision"], "encoder_files": encoder["files"], "policy_files": policy,
               "pip_install_report_sha256": digest((output / "pip-install.json").read_bytes()),
               "preparation_script_sha256": digest(Path(__file__).read_bytes()), "worker_ready": ready,
               "inference_requests": 0, "fitting_performed": False, "held_reads": 0,
               "limitation": "Frozen-weight loading profile; differing Python patches are recorded, not claimed bitwise equivalent."}
    publish_file(output / "PREPARATION.json", canonical(receipt) + b"\n")
    publish_file(output / "github.env", "".join(f"{key}={value}\n" for key, value in exported.items()).encode())
    publish_file(output / "environment.sh", "".join(f"export {key}={shlex.quote(value)}\n" for key, value in exported.items()).encode())
    print(json.dumps({"preparation": str(output / "PREPARATION.json"), "github_env": str(output / "github.env")}), flush=True)


if __name__ == "__main__":
    main()
