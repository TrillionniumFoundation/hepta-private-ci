"""Fresh-process offline CPU generation, not original production authority.

Model files are copied into sealed memfds after matching their frozen pins.
The dependency tree is an explicitly trusted public runtime, checked before and
after use; it is not protected against an adversarial same-owner host writer.
No default authenticated observer or causal-benefit assertion is supplied.
"""

from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
import sys
import time

from hepta_ci_exec import execute_logged
import hepta_ci_exec

from . import episodic_provider_handoff
from .episodic_provider_handoff import (
    _canonical,
    _json,
    _pin,
    _read_regular,
    _sync_directory,
    _write,
)

_LOADED_SOURCE = _read_regular(Path(__file__), 65536)
_LOADED_DEPENDENCIES = {
    Path(module.__file__): _read_regular(Path(module.__file__), 65536)
    for module in (hepta_ci_exec, episodic_provider_handoff)
}

MODEL_NAMES = {
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "merges.txt",
    "vocab.json",
}
WORKER = r"""
import hashlib, json, os, resource, sys
from pathlib import Path
os.environ.pop("PWD", None)
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
print("MEM11_BOOTSTRAP " + json.dumps({
 "namespaces": {n: os.readlink("/proc/self/ns/"+n)
 for n in ("mnt", "pid", "net", "ipc", "uts", "user")},
 "empty": all(not os.listdir(p) for p in ("/home/provider", "/cache", "/work"))
}, sort_keys=True), flush=True)
sys.path.insert(0, "/runtime/site")
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
torch.set_num_threads(4)
torch.manual_seed(0)
raw = Path("/input/request.json").read_bytes()
request = json.loads(raw)
tokenizer = AutoTokenizer.from_pretrained("/model", local_files_only=True,
 trust_remote_code=False)
model = AutoModelForCausalLM.from_pretrained("/model", local_files_only=True,
 trust_remote_code=False, use_safetensors=True, dtype=torch.float32).eval()
prompt = tokenizer.apply_chat_template([{"role":"user", "content":request["input"]}],
 tokenize=False, add_generation_prompt=True)
inputs = tokenizer(prompt, return_tensors="pt", truncation=False)
if inputs["input_ids"].shape[1] > 1024:
 raise ValueError("input token budget exceeded")
with torch.inference_mode():
 result = model.generate(**inputs, do_sample=False,
  max_new_tokens=request["max_output_tokens"], use_cache=True,
  pad_token_id=tokenizer.eos_token_id)
tokens = result[0, inputs["input_ids"].shape[1]:].tolist()
usage = resource.getrusage(resource.RUSAGE_SELF)
print("MEM11_RESULT " + json.dumps({"request_sha256":hashlib.sha256(raw).hexdigest(),
 "text":tokenizer.decode(tokens, skip_special_tokens=True), "tokens":tokens,
 "prompt_tokens":int(inputs["input_ids"].shape[1]),
 "user_cpu_seconds":usage.ru_utime, "system_cpu_seconds":usage.ru_stime,
 "max_rss_kib":usage.ru_maxrss}, sort_keys=True), flush=True)
"""


@dataclass(frozen=True)
class LocalProviderProfile:
    """Frozen public model/runtime material; no private directories are allowed."""

    model_name: str
    model_dir: str
    model_assets: dict
    site_packages: str
    runtime_sha256: str
    python_sha256: str
    python_executable: str = "/usr/bin/python3"


def _records(raw):
    records = (
        [
            _document(line[16:])
            for line in raw.splitlines()
            if line.startswith(b"MEM11_BOOTSTRAP ")
        ],
        [
            _document(line[13:])
            for line in raw.splitlines()
            if line.startswith(b"MEM11_RESULT ")
        ],
    )
    if any(not isinstance(record, dict) for group in records for record in group):
        raise ValueError("backend records must be objects")
    return records


def _document(raw):
    try:
        return _json(raw)
    except (RecursionError, UnicodeError) as error:
        raise ValueError("invalid or excessively nested provider document") from error


def runtime_inventory(path):
    """Hash the complete regular-file dependency tree, without following links."""
    root = Path(path).resolve(strict=True)
    entries, pending, count, total = {}, [root], 0, 0
    while pending:
        with os.scandir(pending.pop()) as directory:
            for entry in directory:
                count += 1
                if count > 65536:
                    raise ValueError("runtime entry budget exceeded")
                item = Path(entry.path)
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    pending.append(item)
                    continue
                if not stat.S_ISREG(info.st_mode) or total + info.st_size > 8 * 1024**3:
                    raise ValueError("nonregular runtime asset or byte budget exceeded")
                digest, size = hashlib.sha256(), 0
                descriptor = os.open(item, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if (
                        opened.st_dev,
                        opened.st_ino,
                        opened.st_size,
                        opened.st_mode,
                    ) != (info.st_dev, info.st_ino, info.st_size, info.st_mode):
                        raise ValueError("runtime asset changed before hashing")
                    while raw := stream.read(min(1048576, info.st_size + 1 - size)):
                        size += len(raw)
                        if size > info.st_size:
                            raise ValueError("runtime asset grew during hashing")
                        digest.update(raw)
                    after = os.fstat(stream.fileno())
                    if size != info.st_size or (
                        opened.st_dev,
                        opened.st_ino,
                        opened.st_size,
                        opened.st_mtime_ns,
                        opened.st_ctime_ns,
                    ) != (
                        after.st_dev,
                        after.st_ino,
                        after.st_size,
                        after.st_mtime_ns,
                        after.st_ctime_ns,
                    ):
                        raise ValueError("runtime asset changed while hashing")
                total += size
                entries[str(item.relative_to(root))] = {
                    "bytes": size,
                    "sha256": digest.hexdigest(),
                }
    if not entries:
        raise ValueError("empty dependency tree")
    return {
        "sha256": _pin(_canonical(entries))["sha256"],
        "files": len(entries),
        "entries": count,
        "bytes": total,
    }


def run_local_provider(
    root, request_raw, *, request_id, launch_sha256, profile, timeout_seconds=60
):
    """Attempt one immutable-request offline generation; re-entry never relaunches.

    The caller must preserve this journal and its provisioned durable parent.
    Physical host authenticity and original-owner authorization remain upstream.
    Model and runtime hashes must be frozen before any outcome is observed.
    The process deadline excludes inventory/snapshot setup; the caller must
    supervise the whole operation and charge that setup/recovery cost too.
    """
    if sys.platform != "linux" or not hasattr(os, "memfd_create"):
        raise ValueError("Linux sealed-memfd namespace runtime required")
    if not isinstance(profile, LocalProviderProfile):
        raise ValueError("frozen local profile required")
    if _read_regular(Path(__file__), 65536) != _LOADED_SOURCE:
        raise ValueError("loaded provider source changed")
    if any(
        _read_regular(path, 65536) != raw for path, raw in _LOADED_DEPENDENCIES.items()
    ):
        raise ValueError("loaded provider dependency source changed")
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
        raise ValueError("bounded request identity required")
    for value in (launch_sha256, profile.runtime_sha256, profile.python_sha256):
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError("frozen SHA-256 required")
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 300:
        raise ValueError("bounded process deadline required")
    if type(request_raw) is not bytes or not 1 <= len(request_raw) <= 65536:
        raise ValueError("bounded exact request bytes required")
    request = _document(request_raw)
    if (
        not isinstance(request, dict)
        or set(request)
        != {"model", "input", "store", "max_output_tokens", "temperature"}
        or request["model"] != profile.model_name
        or request["store"] is not False
        or not isinstance(request["input"], str)
        or type(request["max_output_tokens"]) is not int
        or not 1 <= request["max_output_tokens"] <= 128
        or type(request["temperature"]) not in (int, float)
        or request["temperature"] != 0
    ):
        raise ValueError("single text greedy Responses request required")
    if set(profile.model_assets) != MODEL_NAMES:
        raise ValueError("complete eight-asset safetensors model required")
    for pin in profile.model_assets.values():
        if (
            not isinstance(pin, dict)
            or set(pin) != {"bytes", "sha256"}
            or type(pin["bytes"]) is not int
            or not 0 <= pin["bytes"] <= 1024**3
        ):
            raise ValueError("bounded frozen model pin required")
        if not isinstance(pin["sha256"], str) or len(pin["sha256"]) != 64:
            raise ValueError("model SHA-256 required")
    if sum(pin["bytes"] for pin in profile.model_assets.values()) > 1024**3:
        raise ValueError("model total byte budget exceeded")
    python = Path(profile.python_executable)
    if not python.is_absolute() or not str(python.resolve()).startswith("/usr/"):
        raise ValueError("system Python under /usr required")
    python_pin = _pin(_read_regular(python.resolve(strict=True), 64 * 1024**2))
    if python_pin["sha256"] != profile.python_sha256:
        raise ValueError("system Python changed")
    model = Path(profile.model_dir).resolve(strict=True)
    runtime = Path(profile.site_packages).resolve(strict=True)
    admission = {
        "schema": "hepta.mem11.local-provider.v1",
        "request_id": request_id,
        "launch_sha256": launch_sha256,
        "request": _pin(request_raw),
        "profile": asdict(profile),
        "worker": _pin(WORKER.encode()),
        "timeout_seconds": timeout_seconds,
    }
    admission["provider_source"] = _pin(_LOADED_SOURCE)
    admission["dependency_sources"] = {
        path.name: _pin(raw) for path, raw in _LOADED_DEPENDENCIES.items()
    }
    root = Path(root).absolute()
    root.mkdir(exist_ok=True, mode=0o700)
    _sync_directory(root.parent)
    output = root / hashlib.sha256(request_id.encode()).hexdigest()
    unknown = {
        **admission,
        "status": "UNKNOWN",
        "local_generation_returned": False,
        "observer_authenticated": False,
        "scientific_acceptance": "HOLD",
    }
    try:
        output.mkdir(mode=0o700)
    except FileExistsError:
        if not (output / "ADMISSION.json").exists():
            return {**unknown, "reason": "INTERRUPTED_ADMISSION"}
        if _read_regular(output / "ADMISSION.json", 65536) != _canonical(admission):
            raise ValueError("durable local request identity conflict")
        if not (output / "RECEIPT.json").exists():
            return unknown
        retained = _document(_read_regular(output / "RECEIPT.json", 1048576))
        if not isinstance(retained, dict):
            raise ValueError("retained local receipt must be an object")
        if any(retained.get(k) != v for k, v in admission.items()):
            raise ValueError("retained local receipt conflicts with admission")
        for name, pin in (
            ("request.bin", admission["request"]),
            ("combined.log", retained.get("combined_log")),
        ):
            if pin is not None and (
                not (output / name).is_file()
                or _pin(_read_regular(output / name, 1048576)) != pin
            ):
                return {**unknown, "reason": "RETAINED_BYTES_CHANGED"}
        if retained.get("status") not in {
            "SETUP_FAILED",
            "EXECUTION_FAILED",
            "RETURNED",
            "SOURCE_CHANGED",
        }:
            raise ValueError("invalid local terminal status")
        if retained["status"] == "RETURNED":
            log = _read_regular(output / "combined.log", 1048576)
            boots, results = _records(log)
            execution = retained.get("execution")
            if not isinstance(execution, dict):
                raise ValueError("retained execution must be an object")
            if (
                not isinstance(retained.get("combined_log"), dict)
                or _pin(log) != retained["combined_log"]
                or retained.get("local_generation_returned") is not True
                or boots != [retained.get("bootstrap")]
                or results != [retained.get("result")]
                or execution.get("returncode") != 0
                or execution.get("timed_out") is not False
                or execution.get("output_limit_exceeded") is not False
                or not results
                or results[0].get("request_sha256") != admission["request"]["sha256"]
            ):
                raise ValueError(
                    "returned terminal is not bound to complete generation evidence"
                )
        elif retained.get("local_generation_returned") is not False:
            raise ValueError("nonreturned terminal claims generation")
        return retained
    _sync_directory(root)
    _write(output / "ADMISSION.json", _canonical(admission))
    _write(output / "request.bin", request_raw)
    receipt = {
        **unknown,
        "status": "SETUP_FAILED",
        "started_at_unix_ns": time.time_ns(),
    }
    descriptors = []
    try:
        import fcntl

        bwrap = shutil.which("bwrap")
        if not bwrap:
            raise ValueError("bubblewrap unavailable")
        before = runtime_inventory(runtime)
        if before["sha256"] != profile.runtime_sha256:
            raise ValueError("runtime inventory changed")
        receipt["runtime_before"] = before
        command = [
            bwrap,
            "--unshare-all",
            "--unshare-user",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
            "--clearenv",
        ]
        for path in ("/usr", "/lib", "/lib64"):
            if Path(path).exists():
                command += ["--ro-bind", path, path]
        command += [
            "--symlink",
            "usr/bin",
            "/bin",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--tmpfs",
            "/home",
            "--dir",
            "/home/provider",
            "--tmpfs",
            "/cache",
            "--tmpfs",
            "/work",
            "--dir",
            "/input",
            "--dir",
            "/model",
            "--dir",
            "/runtime",
            "--ro-bind",
            str(runtime),
            "/runtime/site",
            "--chdir",
            "/work",
        ]
        for key, value in {
            "HOME": "/home/provider",
            "XDG_CACHE_HOME": "/cache",
            "HF_HOME": "/cache/hf",
            "TMPDIR": "/tmp",
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
        }.items():
            command += ["--setenv", key, value]
        sealed = {
            "/input/request.json": request_raw,
            "/input/worker.py": WORKER.encode(),
        }
        for name, pin in profile.model_assets.items():
            path = model / name
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size != pin["bytes"]
            ):
                raise ValueError("regular model file required")
            raw = _read_regular(path, pin["bytes"])
            if _pin(raw) != pin:
                raise ValueError("model asset changed")
            sealed["/model/" + name] = raw
        for target, raw in sealed.items():
            fd = os.memfd_create("mem11", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
            descriptors.append(fd)
            with os.fdopen(os.dup(fd), "wb") as stream:
                stream.write(raw)
            os.lseek(fd, 0, os.SEEK_SET)
            fcntl.fcntl(fd, 1033, 0x000F)
            if fcntl.fcntl(fd, 1034) != 0x000F:
                raise ValueError("model/input sealing failed")
            command += ["--ro-bind-data", str(fd), target]
        command += ["--", str(python), "-I", "-S", "-B", "/input/worker.py"]
        namespaces = {
            n: os.readlink("/proc/self/ns/" + n)
            for n in ("mnt", "pid", "net", "ipc", "uts", "user")
        }
        receipt["host_namespaces"] = namespaces
        receipt["python"] = {"path": str(python), **python_pin}
        receipt["bubblewrap"] = _pin(
            _read_regular(Path(bwrap).resolve(strict=True), 64 * 1024**2)
        )
        receipt["execution"] = execute_logged(
            command,
            output / "combined.log",
            maximum_bytes=1048576,
            timeout_seconds=timeout_seconds,
            pass_fds=tuple(descriptors),
        )
        receipt["runtime_after"] = runtime_inventory(runtime)
        receipt["status"] = "EXECUTION_FAILED"
        raw = _read_regular(output / "combined.log", 1048576)
        receipt["combined_log"] = _pin(raw)
        boots, results = _records(raw)
        if (
            receipt["execution"]["returncode"] == 0
            and not receipt["execution"]["timed_out"]
            and not receipt["execution"]["output_limit_exceeded"]
            and receipt["runtime_after"] == before
            and len(boots) == len(results) == 1
            and boots[0]["empty"] is True
            and isinstance(boots[0].get("namespaces"), dict)
            and set(boots[0]["namespaces"]) == set(namespaces)
            and all(isinstance(boots[0]["namespaces"][n], str) for n in namespaces)
            and all(boots[0]["namespaces"][n] != namespaces[n] for n in namespaces)
            and results[0]["request_sha256"] == admission["request"]["sha256"]
        ):
            receipt.update(
                status="RETURNED",
                local_generation_returned=True,
                bootstrap=boots[0],
                result=results[0],
            )
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        receipt["error"] = type(error).__name__ + ": " + str(error)
    finally:
        for fd in descriptors:
            os.close(fd)
        try:
            receipt["source_unchanged"] = _read_regular(
                Path(__file__), 65536
            ) == _LOADED_SOURCE and all(
                _read_regular(path, 65536) == raw
                for path, raw in _LOADED_DEPENDENCIES.items()
            )
        except (OSError, ValueError):
            receipt["source_unchanged"] = False
        if not receipt["source_unchanged"]:
            receipt.update(status="SOURCE_CHANGED", local_generation_returned=False)
        receipt["ended_at_unix_ns"] = time.time_ns()
        _write(output / "RECEIPT.json", _canonical(receipt))
    return receipt
