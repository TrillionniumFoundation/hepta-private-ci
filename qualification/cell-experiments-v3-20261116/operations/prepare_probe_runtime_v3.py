"""Create one isolated CUDA development runtime and pin public model materials."""

import concurrent.futures
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import venv


MODEL = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
ROOT = Path(sys.argv[1]).resolve()
START = time.time_ns()
ROOT.mkdir(parents=True, exist_ok=False)
(ROOT / "operations").mkdir()
LOGS = ROOT / "operations"


def save(name, value):
    with (LOGS / name).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")


def command(name, argv, timeout):
    started = time.perf_counter()
    with (LOGS / (name + ".log")).open("xb") as stream:
        result = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    receipt = {"argv": argv, "exit_code": result.returncode,
               "wall_seconds": time.perf_counter() - started}
    save(name + ".json", receipt)
    if result.returncode:
        raise RuntimeError(name + " failed; inspect retained log")
    print(json.dumps({"stage": name, **receipt}), flush=True)


def environment():
    venv.EnvBuilder(with_pip=True).create(ROOT / "venv")
    python = str(ROOT / "venv/bin/python")
    command("INSTALL_TORCH", [python, "-m", "pip", "install", "--no-cache-dir",
            "--disable-pip-version-check", "torch==2.9.1", "--index-url",
            "https://download.pytorch.org/whl/cu128"], 1500)
    command("INSTALL_LIBRARIES", [python, "-m", "pip", "install", "--no-cache-dir",
            "--disable-pip-version-check", "numpy==1.26.4", "transformers==4.57.3",
            "peft==0.18.0", "safetensors==0.7.0", "tokenizers==0.22.2"], 600)
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


def materials():
    request = urllib.request.Request("https://huggingface.co/api/models/" + MODEL + "?blobs=true",
                                     headers={"User-Agent": "hepta-e1e6-development-v3"})
    with urllib.request.urlopen(request, timeout=45) as response:
        api = json.load(response)
    revision = api["sha"]
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("upstream revision is not a commit SHA")
    save("UPSTREAM_MODEL_API.json", api)
    names = {"config.json", "generation_config.json", "tokenizer.json",
             "tokenizer_config.json", "special_tokens_map.json", "vocab.json",
             "merges.txt", "model.safetensors", "LICENSE", "README.md"}
    chosen = [row for row in api["siblings"] if row["rfilename"] in names]
    required = {"config.json", "tokenizer.json", "tokenizer_config.json", "model.safetensors"}
    if not required <= {row["rfilename"] for row in chosen}:
        raise ValueError("expected single safetensor model materials are incomplete")
    weights = next(row for row in chosen if row["rfilename"] == "model.safetensors")
    if not weights.get("lfs", {}).get("sha256"):
        raise ValueError("upstream weight SHA256 missing")
    destination = ROOT / "materials"
    destination.mkdir()
    inventory = []
    for row in chosen:
        name = row["rfilename"]
        request = urllib.request.Request("https://huggingface.co/" + MODEL + "/resolve/" + revision + "/" + name,
                                         headers={"User-Agent": "hepta-e1e6-development-v3"})
        path = destination / name
        total, digest = 0, hashlib.sha256()
        with urllib.request.urlopen(request, timeout=90) as response, path.open("xb") as stream:
            while block := response.read(4 * 1024 * 1024):
                total += len(block)
                if total > 4 * 1024 ** 3:
                    raise ValueError("individual model material exceeds download bound")
                digest.update(block)
                stream.write(block)
        sha = digest.hexdigest()
        if row.get("lfs", {}).get("sha256") not in (None, sha):
            raise ValueError("downloaded weight does not match upstream LFS SHA256")
        inventory.append({"path": name, "sha256": sha, "bytes": total,
                          "upstream_git_blob": row.get("blobId"),
                          "upstream_lfs_sha256": row.get("lfs", {}).get("sha256")})
        print(json.dumps({"downloaded": name, "bytes": total}), flush=True)
    receipt = {"model_id": MODEL, "revision": revision, "files": inventory,
               "trust_remote_code": False, "model_loaded": False,
               "generated_at_ns": time.time_ns()}
    save("MODEL_MATERIALS.json", receipt)
    return receipt


save("STARTED.json", {"started_at_ns": START, "root": str(ROOT),
                     "disk_free_bytes": shutil.disk_usage(ROOT).free,
                     "scope": "isolated development setup; no model training or inference"})
try:
    if shutil.disk_usage(ROOT).free < 15 * 1024 ** 3:
        raise RuntimeError("insufficient free disk for isolated CUDA setup")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        runtime = pool.submit(environment)
        model = pool.submit(materials)
        result = {"runtime": runtime.result(), "materials": model.result()}
    save("READY.json", {"status": "READY", "started_at_ns": START,
                        "completed_at_ns": time.time_ns(), **result})
    print("ISOLATED_RUNTIME_READY", flush=True)
except BaseException as error:
    save("FAILED.json", {"status": "FAILED_PRESERVED", "error": repr(error),
                         "completed_at_ns": time.time_ns(), "automatic_retry": False})
    raise
