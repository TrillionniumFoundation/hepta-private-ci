"""Create-only evidence, published source identities and exact CPU environment."""

from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import re
import subprocess
import sys
import time

import numpy as np


SOURCE_FILES = ("io.py", "exposure.py", "published.py", "census.py", "data_prepare.py",
                "models.py", "matching.py", "gates.py", "infer.py", "evaluate.py",
                "statistics.py", "harness.py", "template.json", "registration/published-manifest.json",
                "registration/environment-preflight.json")
FORBIDDEN = {"final-targets.npz", "final_labels.json", "validation_labels.json"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def file_hash(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("ordinary file required: " + str(path))
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path, maximum=64 << 20):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("invalid bounded JSON file: " + str(path))
    return json.loads(path.read_bytes(), object_pairs_hook=unique_keys)


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field: " + key)
        result[key] = value
    return result


def write(path, value):
    payload = canonical(value) + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(payload)
    return {"sha256": digest(payload), "bytes": len(payload)}


def arrays(path, **values):
    if any(np.asarray(value).dtype.hasobject for value in values.values()):
        raise ValueError("pickle-capable array forbidden")
    with Path(path).open("xb") as stream:
        np.savez_compressed(stream, **values)
    return {"sha256": file_hash(path), "bytes": Path(path).stat().st_size}


def read_arrays(path, expected_keys):
    with np.load(path, allow_pickle=False) as archive:
        if set(archive.files) != set(expected_keys):
            raise ValueError("unexpected tensor archive fields")
        result = {key: archive[key] for key in expected_keys}
    if any(value.dtype.hasobject or not np.isfinite(value).all() for value in result.values()):
        raise ValueError("nonfinite or unsafe evidence tensor")
    return result


def identity(path):
    return {"sha256": file_hash(path), "bytes": Path(path).stat().st_size}


def require_identity(path, expected):
    actual = identity(path)
    if actual["sha256"] != expected["sha256"] or ("bytes" in expected and actual["bytes"] != expected["bytes"]):
        raise ValueError("bound file changed: " + str(path))
    return actual


def seal(root, name):
    root = Path(root)
    files = {str(p.relative_to(root)): identity(p) for p in sorted(root.rglob("*")) if p.is_file()}
    write(root / name, {"schema": "hepta.ndu-fresh-factorial.seal.v1", "files": files,
                       "at_utc": datetime.now(timezone.utc).isoformat()})
    return file_hash(root / name)


def verify_seal(root, name):
    root = Path(root)
    manifest = read_json(root / name)
    if manifest["schema"] != "hepta.ndu-fresh-factorial.seal.v1":
        raise ValueError("unknown seal schema")
    actual_names = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and p != root / name}
    if set(manifest["files"]) != actual_names:
        raise ValueError("incomplete seal or unsealed extra file")
    for relative, expected in manifest["files"].items():
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("seal path escapes evidence root")
        require_identity(root / relative, expected)
    return manifest


def deny_final(event, arguments):
    if event == "open" and arguments and isinstance(arguments[0], (str, bytes, os.PathLike)):
        if Path(os.fsdecode(arguments[0])).name in FORBIDDEN:
            raise PermissionError("new final targets are not an input to this stage")


def source_hashes(template):
    from .published import verify_published
    root = Path(__file__).parent
    names = sorted(set(SOURCE_FILES) | set(template["original_source_files"]))
    published = verify_published(template)
    confirmation = template["environment_confirmation"]
    if confirmation["status"] == "verified_before_source_freeze":
        require_identity(root / confirmation["preflight_path"], {"sha256": confirmation["preflight_sha256"]})
    names += ["registration/published/" + name for name in sorted(published["files"])]
    result = {name: file_hash(root / name) for name in names}
    if any(result[name] != expected for name, expected in template["original_source_files"].items()):
        raise ValueError("original full-002 implementation differs from its committed source")
    return result


def ordinary_absolute(value):
    path = Path(value)
    if not path.is_absolute() or str(path) != os.path.normpath(str(value)) or path.resolve() != path:
        raise ValueError("registered paths must be absolute, normalized and free of symlink aliases")
    return path


def require_owner(plan, path, stage):
    owner = ordinary_absolute(plan["source_owner_directory"])
    actual = ordinary_absolute(path)
    if actual != owner / stage:
        raise ValueError("stage must use its one pre-registered source-owner directory")
    return actual


def published_source(template, expected_commit, protocol=None):
    root = Path(__file__).parent
    result = source_hashes(template)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                            text=True, check=True, timeout=10).stdout.strip()
    if commit != expected_commit:
        raise ValueError("executed source head differs from published commit")
    names = sorted(result)
    if protocol is not None:
        if Path(protocol).resolve().parent != root.resolve():
            raise ValueError("execute the published protocol beside its source")
        names.append(Path(protocol).name)
    for command in (["git", "ls-files", "--error-unmatch", "--", *names],
                    ["git", "diff", "--quiet", "HEAD", "--", *names]):
        subprocess.run(command, cwd=root, check=True, capture_output=True, timeout=10)
    if "algorithm_source_files" in template and result != template["algorithm_source_files"]:
        raise ValueError("algorithms changed after exposure review and protocol freeze")
    return {"git_commit": commit, "files": result, "publication_verification": "root verifies this commit through GitHub before source preparation"}


def cpu_environment(plan):
    if platform.python_version_tuple()[:2] != tuple(plan["environment"]["python_major_minor"].split(".")):
        raise ValueError("registered Python major/minor required")
    for name, expected in plan["environment"]["packages"].items():
        if importlib.metadata.version(name) != expected:
            raise ValueError("registered package version required: " + name)
    if any(os.environ.get(key) not in {"1", "2"} for key in
           ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")):
        raise ValueError("set every numerical thread environment limit to one or two before launching")
    import torch
    if torch.version.cuda is not None:
        raise ValueError("registered CPU-only Torch build required")
    torch.set_num_threads(2)
    torch.set_num_interop_threads(2)
    torch.use_deterministic_algorithms(True)
    return torch, {"python": platform.python_version(), "platform": platform.platform(),
                   "packages": {name: importlib.metadata.version(name) for name in plan["environment"]["packages"]},
                   "torch_threads": torch.get_num_threads(), "torch_interop_threads": torch.get_num_interop_threads(),
                   "cuda_build": torch.version.cuda, "deterministic_algorithms": True,
                   "reference_python": plan["environment"]["reference_python"],
                   "python_patch_policy": plan["environment"]["python_patch_policy"]}


def clock():
    return time.perf_counter_ns(), time.process_time_ns()


def cost(start):
    return {"wall_ns": time.perf_counter_ns() - start[0], "cpu_ns": time.process_time_ns() - start[1],
            "process_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "energy_measured": False}


def run_stage(callback, arguments):
    root = Path(arguments["output"])
    existed = root.exists()
    try:
        return callback(**arguments)
    except Exception as error:
        if not existed and root.is_dir() and not (root / "failure.json").exists():
            write(root / "failure.json", {"stage": callback.__name__, "error_type": type(error).__name__,
                  "message": str(error), "at_utc": datetime.now(timezone.utc).isoformat(),
                  "partial_outputs_preserved": True, "authority": "DENY_ALL"})
        raise


def validate_data(data, plan):
    root = require_owner(plan, data, "data")
    receipt = read_json(root / "data-receipt.json")
    if receipt["protocol_canonical_sha256"] != digest(plan) or receipt["source_count"] != 90:
        raise ValueError("new source preparation differs from registered protocol")
    expected = {"training.npz", "training-source.json", "observer-training.npz", "observer-source.json", "observations.npz", "cases.json",
                "reserved-sources.json", "final-targets.npz"}
    if set(receipt["files"]) != expected:
        raise ValueError("data preparation file census differs")
    for name in sorted(expected - {"final-targets.npz"}):
        require_identity(root / name, receipt["files"][name])
    cases = read_json(root / "cases.json")["cases"]
    if (len(cases) != 90 or len({x["case_id"] for x in cases}) != 90
            or len({p for x in cases for p in x["source_ids"]}) != 180):
        raise ValueError("duplicate or missing paired source")
    expected_cases = [(split, item["offset"] + i, plan["corruptions"][i % 6] if split == "future" else "clean")
                      for split in ("future", "retention") for item in [plan["case_ranges"][split]]
                      for i in range(item["count"])]
    pixels = set()
    for case, (split, index, corruption) in zip(cases, expected_cases, strict=True):
        if (case["case_id"] != f"{split}-{index:04}" or case["split"] != split
                or case["index"] != index or case["corruption"] != corruption or len(case["source_ids"]) != 2):
            raise ValueError("registered source/corruption schedule differs")
        for source in case["source_ids"]:
            match = re.fullmatch(r"mnist:(train|test):[0-9]+:([0-9a-f]{64})", source)
            if (not match or match[1] != ("test" if split == "future" else "train")
                    or match[2] in pixels or match[2] in plan["exposed_source_pixels"]):
                raise ValueError("malformed, repeated or previously exposed source")
            pixels.add(match[2])
    return receipt, cases
