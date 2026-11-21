"""One-shot transport through the already registered source workflow.

This module is called only by the final optimized source test.  It publishes a
complete PASS or RED archive into the immutable job log because the registered
source workflow has no artifact-upload step.
"""

import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
KEY = "hcsn-n256-dense-compatible-firststep-hosted-20261121-c06d-001"
HEAD = "research/hcsn-n256-dense-compatible-firststep-opened-20261121-c06d"
BASE = "intent/hcsn-n256-dense-compatible-firststep-execution-20261121-c06d"
RECEIPT_SHA256 = "1be13af8d353621f3ac7bee386979e6d55e8930001426ff275f1cdd7028d5b21"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n")


def event_head():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    observed = event["pull_request"]["head"]["sha"]
    if len(observed) != 40 or any(character not in "0123456789abcdef" for character in observed):
        raise ValueError("pull request head identity")
    return observed


def require_transport_identity():
    receipt = HERE / "SOURCE_WORKFLOW_EXECUTION.json"
    if sha(receipt.read_bytes()) != RECEIPT_SHA256:
        raise ValueError("source workflow execution receipt identity")
    value = json.loads(receipt.read_text())
    if value["identity"] != KEY or value["maximum_dispatches"] != 1:
        raise ValueError("source workflow execution contract")
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("GitHub Actions identity")
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        raise ValueError("pull request event identity")
    if os.environ.get("GITHUB_HEAD_REF") != HEAD or os.environ.get("GITHUB_BASE_REF") != BASE:
        raise ValueError("pull request branch identity")
    if sys.version_info[:3] != (3, 12, 16):
        raise ValueError("amended Python identity")


def install_runtime(output):
    command = [
        sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
        "--no-cache-dir", "--only-binary=:all:", "-r",
        "qualification/hcsn_currentstate_n256_firststep_dense_oracle_hosted/requirements.txt",
    ]
    completed = subprocess.run(command, capture_output=True, check=False, timeout=300)
    (output / "PIP_INSTALL_STDOUT.bin").write_bytes(completed.stdout)
    (output / "PIP_INSTALL_STDERR.bin").write_bytes(completed.stderr)
    write(output / "PIP_INSTALL.json", {"command": command, "returncode": completed.returncode})
    if completed.returncode:
        raise RuntimeError(f"pip install exit {completed.returncode}")


def archive_and_emit(output):
    archive = output.parent / (output.name + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for path in sorted(output.iterdir(), key=lambda item: item.name):
            info = zipfile.ZipInfo(path.name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            package.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    raw = archive.read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    print(f"HCSN_ORIGINALS_BEGIN:{len(raw)}:{sha(raw)}:{len(encoded)}", flush=True)
    for index, start in enumerate(range(0, len(encoded), 12000)):
        print(f"HCSN_ORIGINALS_B64:{index:06d}:{encoded[start:start + 12000]}", flush=True)
    print(f"HCSN_ORIGINALS_END:{len(raw)}:{sha(raw)}", flush=True)


def main():
    require_transport_identity()
    root = Path(os.environ["RUNNER_TEMP"])
    output = root / KEY
    if output.exists():
        raise ValueError("single output path already exists")
    output.mkdir()
    started = time.time()
    status, detail = "RED", "transport did not start launcher"
    try:
        install_runtime(output)
        # launcher owns creation of RUN_OUTPUT, so move the install originals
        # aside until its fail-closed terminal record exists.
        install_originals = {path.name: path.read_bytes() for path in output.iterdir()}
        for path in list(output.iterdir()):
            path.unlink()
        output.rmdir()
        os.environ.update({
            "UNIQUE_EXECUTION_KEY": KEY,
            "ADMITTED_SOURCE_SHA": event_head(),
            "RUN_OUTPUT": str(output),
            "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
            "PYTHONHASHSEED": "0",
        })
        from . import launcher
        code = launcher.main()
        for name, raw in install_originals.items():
            (output / name).write_bytes(raw)
        status = "PASS" if code == 0 else "RED"
        detail = f"launcher exit {code}"
    except BaseException as error:
        detail = f"{type(error).__name__}: {error}"
        output.mkdir(exist_ok=True)
        write(output / "SOURCE_TRANSPORT_ERROR.json", {"detail": detail})
    finally:
        write(output / "SOURCE_TRANSPORT.json", {
            "schema": "hcsn-n256-dense-compatible-firststep-source-transport-v1",
            "identity": KEY, "status": status, "detail": detail,
            "elapsed_seconds": time.time() - started,
            "historical_sparse_red_preserved": True,
            "c2_full_replay_completed_fits": 0, "hpca_status": "NoUpdate",
            "production_adoption": False, "all_closed": False,
        })
        archive_and_emit(output)
    if status != "PASS":
        raise RuntimeError(detail)


if __name__ == "__main__":
    main()
