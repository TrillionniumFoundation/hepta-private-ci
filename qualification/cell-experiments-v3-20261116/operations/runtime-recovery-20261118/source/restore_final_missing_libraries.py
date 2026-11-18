"""Restore only the five absent original libraries from complete pinned wheels."""

import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import zipfile

ROOT = Path("/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a")
ORIGINAL = ROOT / "operations/recovery-03"
VENV = ROOT / "venv"
RECOVERY = ROOT / "operations/recovery-20261118-e4c"
WHEELS = RECOVERY / "wheelhouse"
OUT = RECOVERY / "install"
PREFIX = "lib/python3.12/site-packages/"
EXPECTED = {
    "torch/lib/libtorch_cpu.so": (436938961, "7918fc09ff644c9b667921100b924e33ea432c85737c2982b56283691b32a4d7"),
    "torch/lib/libtorch_cuda.so": (1022776209, "02250527966ae122ccfc89d0306736874f9c619ba04431871ef76175e7253b66"),
    "torch/lib/libtorch_cuda_linalg.so": (127492873, "435f69ace8ac6cb14f2081c341a014e3cdff8d2605e12fbf6c68f93a37f50aef"),
    "triton/_C/libtriton.so": (401081768, "5a9fda48d18d1da1c6ce3d50b415b053bcfdedc4d1109f4acc8ae7833d134437"),
    "nvidia/nvshmem/lib/libnvshmem_host.so.3": (144177272, "8337d251e616a6e13750c1a322e9dbabfa867af4480adc77e13a6079269db936"),
}
PINS = {
    "torch": (900881648, "7cb4018f4ce68b61fd3ef87dc1c4ca520731c7b5b200e360ad47b612d7844063"),
    "triton": (170470207, "d2c6b915a03888ab931a9fd3e55ba36785e1fe70cbea0b40c6ef93b20fc85232"),
    "nvidia-nvshmem-cu12": (124657145, "d00f26d3f9b2e3c3065be895e3059d6479ea5c638a3f38c9fec49b1b9dd7c1e5"),
}


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def save(name, value):
    with (OUT / name).open("x") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def emit(value):
    print(json.dumps(value, sort_keys=True), flush=True)
    with (OUT / "EVENTS.jsonl").open("a") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def publish(stream, target, item):
    if target.exists() or target.is_symlink() or target.parent.resolve() != target.parent:
        raise ValueError("target is not absent under a regular parent: " + str(target))
    temporary = target.with_name(target.name + ".restore-20261118-e4c")
    value = hashlib.sha256()
    with temporary.open("xb") as output:
        while chunk := stream.read(8 * 1024 * 1024):
            output.write(chunk)
            value.update(chunk)
        output.flush()
        os.fsync(output.fileno())
    if temporary.stat().st_size != item["bytes"] or value.hexdigest() != item["sha256"]:
        raise ValueError("installed member differs from original manifest")
    os.chmod(temporary, 0o755)
    os.link(temporary, target)
    temporary.unlink()
    if sha(target) != item["sha256"]:
        raise ValueError("published bytes differ")
    emit({"event": "RESTORED", **item})


def main():
    OUT.mkdir(exist_ok=False)
    started = time.monotonic()
    restored = []
    try:
        source = json.loads((ORIGINAL / "DOWNLOAD_MANIFEST.json").read_text())
        wheels = {row["name"]: row for row in source["items"]}
        all_items, missing, manifests = {}, {}, []
        for path in sorted(ORIGINAL.glob("INSTALLED_FILES_*.json.gz")):
            manifests.append({"path": str(path), "sha256": sha(path)})
            manifest = json.loads(gzip.decompress(path.read_bytes()))
            for item in manifest["files"]:
                previous = all_items.setdefault(item["path"], item)
                if previous != item:
                    raise ValueError("conflicting original package path")
                if not (VENV / item["path"]).is_file():
                    missing.setdefault(manifest["distribution"], []).append(item)
        actual_missing = {item["path"] for group in missing.values() for item in group}
        if actual_missing != {PREFIX + path for path in EXPECTED}:
            raise ValueError("remaining missing files differ from the observed five")
        save("PLAN.json", {
            "missing": missing, "manifests": manifests,
            "download_manifest_sha256": sha(ORIGINAL / "DOWNLOAD_MANIFEST.json"),
            "existing_file_overwrite": False, "package_versions_changed": False,
            "automatic_experiment_retry": False,
        })
        for name, items in missing.items():
            wheel = wheels[name]
            if (wheel["bytes"], wheel["sha256"]) != PINS[name]:
                raise ValueError("original wheel pin differs")
            path = WHEELS / wheel["filename"]
            if path.stat().st_size != wheel["bytes"] or sha(path) != wheel["sha256"]:
                raise ValueError("complete transferred wheel differs: " + name)
            emit({"event": "WHEEL_VERIFIED", "name": name, "sha256": wheel["sha256"]})
            with zipfile.ZipFile(path) as archive:
                for item in items:
                    member = Path(item["path"]).relative_to(PREFIX).as_posix()
                    if (item["bytes"], item["sha256"]) != EXPECTED[member]:
                        raise ValueError("installed-file pin differs")
                    with archive.open(member) as stream:
                        publish(stream, VENV / item["path"], item)
                    restored.append(item)
        missing_end, different = [], []
        checked_bytes = 0
        for name, item in sorted(all_items.items()):
            path = VENV / name
            if not path.is_file():
                missing_end.append(name)
            elif path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
                different.append(name)
            checked_bytes += item["bytes"]
        verified = {"files": len(all_items), "bytes": checked_bytes,
                    "missing": missing_end, "different": different}
        save("ORIGINAL_FILES_VERIFICATION.json", verified)
        if missing_end or different:
            raise ValueError("original environment identity is not fully restored")
        command = [str(VENV / "bin/python"), "-I", "-B", "-c", SMOKE]
        smoke = subprocess.run(command, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=120)
        (OUT / "SMOKE.txt").write_text(smoke.stdout)
        if smoke.returncode:
            raise ValueError("original environment import/CUDA smoke failed")
        result = {"status": "COMPLETE", "restored": restored, "verified": verified,
                  "smoke_exit_code": smoke.returncode, "smoke_sha256": sha(OUT / "SMOKE.txt"),
                  "wall_seconds": time.monotonic() - started,
                  "free_bytes_after": shutil.disk_usage(ROOT).free,
                  "existing_file_overwrite": False, "package_versions_changed": False,
                  "model_experiments_executed": 0}
        save("RESULT.json", result)
        emit({key: value for key, value in result.items() if key != "restored"})
        print(smoke.stdout, end="", flush=True)
    except BaseException as error:
        save("FAILED.json", {"error": str(error), "type": type(error).__name__,
                             "restored": restored, "wall_seconds": time.monotonic() - started})
        emit({"event": "FAILED", "error": str(error), "type": type(error).__name__})
        raise


SMOKE = """
import json
import torch, transformers, peft, numpy
versions = {name: module.__version__ for name, module in (
    ('torch', torch), ('transformers', transformers), ('peft', peft), ('numpy', numpy))}
expected = {'torch': '2.9.1+cu128', 'transformers': '4.57.3', 'peft': '0.18.0', 'numpy': '1.26.4'}
if versions != expected:
    raise ValueError('original package versions differ: ' + str(versions))
if not torch.cuda.is_available():
    raise ValueError('CUDA unavailable')
a = torch.ones((32, 32), dtype=torch.float32, device='cuda')
b = a @ a
torch.cuda.synchronize()
if not torch.equal(b, torch.full_like(b, 32.0)):
    raise ValueError('tiny CUDA numerical result differs')
print(json.dumps({'versions': versions, 'cuda': torch.version.cuda,
    'device': torch.cuda.get_device_name(0), 'cuda_matrix_sum': b.sum().item(),
    'scope': 'Original runtime import and tiny CUDA kernel only; no model task or learning evidence'}, sort_keys=True))
"""


if __name__ == "__main__":
    main()
