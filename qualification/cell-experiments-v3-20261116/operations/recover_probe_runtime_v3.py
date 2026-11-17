"""Resume pinned public data in bounded ranges after a confirmed setup stop."""

import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request


ROOT = Path("/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a")
OPS = ROOT / "operations/recovery-02"
OPS.mkdir(exist_ok=False)
START = time.time_ns()
MODEL = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
API = json.loads((ROOT / "operations/UPSTREAM_MODEL_API.json").read_text())
REVISION = "2e1fd397ee46e1388853d2af2c993145b0f1098a"
if API["sha"] != REVISION:
    raise ValueError("the pinned source revision changed")


def save(name, value):
    with (OPS / name).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b""):
            result.update(block)
    return result.hexdigest()


def command(name, argv, timeout):
    begin = time.perf_counter()
    with (OPS / (name + ".log")).open("xb") as stream:
        result = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    receipt = {"argv": argv, "exit_code": result.returncode, "wall_seconds": time.perf_counter() - begin}
    save(name + ".json", receipt)
    print(json.dumps({"stage": name, **receipt}), flush=True)
    if result.returncode:
        raise RuntimeError(name + " failed; retained log identifies the failure")


def install():
    python = str(ROOT / "venv/bin/python")
    command("BEFORE_FREEZE", [python, "-m", "pip", "freeze", "--all"], 45)
    command("INSTALL_TORCH_PYPI", [python, "-m", "pip", "install", "--no-cache-dir",
            "--disable-pip-version-check", "--index-url", "https://pypi.org/simple",
            "--report", str(OPS / "TORCH_INSTALL_REPORT.json"), "torch==2.9.1"], 1200)
    command("INSTALL_LIBRARIES", [python, "-m", "pip", "install", "--no-cache-dir",
            "--disable-pip-version-check", "--report", str(OPS / "LIBRARIES_INSTALL_REPORT.json"),
            "numpy==1.26.4", "transformers==4.57.3", "peft==0.18.0",
            "safetensors==0.7.0", "tokenizers==0.22.2"], 600)
    probe = (
        "import json,torch,transformers,peft,safetensors,tokenizers,numpy;"
        "assert torch.cuda.is_available(),'CUDA unavailable';"
        "assert torch.cuda.is_bf16_supported(),'BF16 unavailable';"
        "print(json.dumps({'torch':torch.__version__,'transformers':transformers.__version__,"
        "'peft':peft.__version__,'safetensors':safetensors.__version__,"
        "'tokenizers':tokenizers.__version__,'numpy':numpy.__version__,"
        "'cuda_build':torch.version.cuda,'device':torch.cuda.get_device_name(0),"
        "'free_total_bytes':torch.cuda.mem_get_info()}))"
    )
    command("RUNTIME", [python, "-c", probe], 90)
    command("PIP_FREEZE", [python, "-m", "pip", "freeze", "--all"], 45)
    return {"python": python}


def download():
    destination = ROOT / "materials-recovered"
    destination.mkdir()
    names = {"config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json",
             "special_tokens_map.json", "vocab.json", "merges.txt", "model.safetensors", "LICENSE", "README.md"}
    files, partials = [], []
    for row in API["siblings"]:
        name = row["rfilename"]
        if name not in names:
            continue
        path, original = destination / name, ROOT / "materials" / name
        size = row["size"]
        if not 0 <= size <= 4 * 1024**3:
            raise ValueError("unbounded upstream file")
        if original.exists():
            shutil.copyfile(original, path)
            partials.append({"path": name, "preserved_original_bytes": original.stat().st_size,
                             "preserved_original_sha256": sha256(original)})
        else:
            path.touch(exist_ok=False)
        if path.stat().st_size > size:
            raise ValueError("retained partial is larger than the pinned upstream file")
        while (offset := path.stat().st_size) < size:
            end = min(offset + 8 * 1024**2, size) - 1
            url = f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}?download=true&range_start={offset}"
            for attempt in range(5):
                try:
                    request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-{end}",
                                                                    "User-Agent": "hepta-e1e6-development-v3"})
                    with urllib.request.urlopen(request, timeout=45) as response:
                        expected = f"bytes {offset}-{end}/{size}"
                        if not (response.status == 206 and response.headers.get("Content-Range") == expected):
                            if not (response.status == 200 and offset == 0 and end + 1 == size):
                                raise ValueError("upstream did not honor the exact bounded range")
                        block = response.read(end - offset + 2)
                    if len(block) != end - offset + 1:
                        raise ValueError("incomplete bounded range")
                    with path.open("ab") as stream:
                        stream.write(block)
                        stream.flush()
                        os.fsync(stream.fileno())
                    with (OPS / "RANGES.jsonl").open("a") as stream:
                        stream.write(json.dumps({"path": name, "offset": offset, "bytes": len(block),
                                                 "sha256": hashlib.sha256(block).hexdigest()}) + "\n")
                    if end + 1 == size or (end + 1) // (128 * 1024**2) != offset // (128 * 1024**2):
                        print(json.dumps({"download": name, "retained_bytes": end + 1, "expected_bytes": size}), flush=True)
                    break
                except Exception as error:
                    with (OPS / "RANGE_ERRORS.jsonl").open("a") as stream:
                        stream.write(json.dumps({"path": name, "offset": offset, "attempt": attempt,
                                                 "error": type(error).__name__ + ": " + str(error)[:300]}) + "\n")
                    if attempt == 4:
                        raise
                    time.sleep(attempt + 1)
        sha = sha256(path)
        if row.get("lfs", {}).get("sha256") not in (None, sha):
            raise ValueError("completed file differs from upstream LFS SHA256")
        if not row.get("lfs"):
            raw = path.read_bytes()
            blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
            if blob != row["blobId"]:
                raise ValueError("downloaded text differs from upstream Git blob")
        files.append({"path": name, "bytes": size, "sha256": sha,
                      "upstream_git_blob": row["blobId"], "upstream_lfs_sha256": row.get("lfs", {}).get("sha256")})
    receipt = {"model_id": MODEL, "revision": REVISION, "files": files,
               "base_directory": "materials-recovered", "original_partial_files_preserved": partials,
               "model_loaded": False, "trust_remote_code": False}
    save("MODEL_MATERIALS.json", receipt)
    return receipt


def guarded(name, operation):
    try:
        return operation()
    except BaseException as error:
        save(name + "_FAILED.json", {"error": repr(error), "completed_at_ns": time.time_ns()})
        print(json.dumps({"stage_failed": name, "error_type": type(error).__name__}), flush=True)
        raise


save("STARTED.json", {"started_at_ns": START, "prior_setup_exit_code": -15,
                     "prior_setup_closed": True, "preserves_original_materials": True,
                     "model_loaded": False, "training_started": False})
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    runtime = pool.submit(guarded, "ENVIRONMENT", install)
    materials = pool.submit(guarded, "MATERIALS", download)
    result = {"runtime": runtime.result(), "materials": materials.result()}
save("READY.json", {"status": "READY", "started_at_ns": START, "completed_at_ns": time.time_ns(), **result})
print("ISOLATED_RUNTIME_RECOVERY_READY", flush=True)
