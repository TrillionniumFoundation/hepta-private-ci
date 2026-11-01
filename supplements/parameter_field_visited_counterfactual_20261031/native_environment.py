"""Fresh source and exact public runtime before any scientific artifact download."""

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct

from . import counterfactual as k
from . import native_common as n


def executable(name):
    result = shutil.which(name)
    k.need(result is not None, "Required executable is unavailable: " + name)
    return str(Path(result).absolute())


def runtime_digest(value):
    def canonical(item):
        return json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

    def tagged(item):
        if item is None:
            return ["none"]
        if type(item) is bool:
            return ["bool", item]
        if type(item) is int:
            return ["int", str(item)]
        if type(item) is str:
            return ["str", item]
        if type(item) is dict and all(type(key) is str for key in item):
            return ["dict", [[tagged(key), tagged(item[key])] for key in sorted(item, key=lambda key: canonical(tagged(key)))]]
        raise ValueError("Unsupported runtime descriptor scalar")

    header = canonical({"tree": tagged(value), "arrays": []})
    return hashlib.sha256(b"HEPTA_BRANCH_PREPARATION_1\n" + struct.pack(">Q", len(header)) + header).hexdigest()


def assess_runtime(report, target):
    k.need(report.get("schema") == "hepta.executor-qualification.engineering.1"
           and report.get("science_admission") is False
           and report.get("sample_interval_seconds") == 10
           and report.get("original_thresholds") == {"ram_bytes": 1879048192, "disk_bytes": 2415919104, "samples": 3},
           "Invalid original engineering qualification")
    samples = report.get("capacity_samples")
    k.need(type(samples) is list and len(samples) == 3, "Three original samples required")
    passes = []
    times = []
    for sample in samples:
        original = sample.get("original_root", {})
        available = original.get("effective_available")
        disk = sample.get("disk_available")
        inodes = sample.get("available_inodes")
        k.need(original.get("finite_limit") == 8 * 1024**3 and type(available) is int
               and type(disk) is int and disk >= 0 and type(inodes) is int and inodes >= 0,
               "Original fixed root must be a readable finite 8 GiB cgroup")
        passed = available >= 1879048192 and disk >= 2415919104
        k.need(sample.get("original_joint_pass") is passed, "Capacity pass claim differs from measurements")
        passes.append(passed)
        at = sample.get("at_unix")
        k.need(type(at) in (int, float) and at >= 0, "Missing capacity sample time")
        times.append(at)
    k.need(all(b - a >= 9.9 for a, b in zip(times, times[1:])), "Capacity samples are not separated by ten seconds")
    k.need(report.get("three_original_joint_passes") is all(passes), "Capacity aggregate mismatch")
    runtime = report.get("runtime", {})
    observed = "descriptor" in runtime
    if observed:
        k.need(runtime.get("model_created") is False and runtime.get("scientific_inputs_opened") is False,
               "Qualification imported scientific work")
        k.need(runtime_digest(runtime["descriptor"]) == runtime.get("runtime_sha256"), "Observed runtime digest differs")
    else:
        k.need(runtime.get("not_measured") == "insufficient_or_unknown_visible_headroom",
               "Import failures and unknown runtime evidence cannot authorize reallocation")
    if not all(passes):
        return "ORIGINAL_JOINT_RESOURCE_QUALIFICATION_FAILED"
    k.need(observed, "Successful capacity requires an actual runtime observation")
    expected = target["runtime_expected"]
    k.need(runtime_digest(expected["descriptor"]) == expected["runtime_sha256"], "Target runtime is internally inconsistent")
    same = (runtime["descriptor"] == expected["descriptor"]
            and runtime["runtime_sha256"] == expected["runtime_sha256"]
            and runtime.get("package_versions") == expected["package_versions"])
    k.need(type(runtime.get("package_versions")) is dict, "Missing installed package versions")
    k.need(runtime.get("exact_match") is same, "Runtime flag contradicts literal descriptor")
    if not same:
        return "EXACT_RUNTIME_MISMATCH"
    k.need(report.get("process", {}).get("supported") is True, "Actual child ownership qualification failed")
    k.need(all(report.get("filesystem", {}).get(key) is True
               for key in ("xattr", "fsync", "atomic_rename", "flock", "byte_readback")),
           "Filesystem capability qualification failed")
    return None


def source_and_runtime(binding, directory, command):
    c, _, _ = n.portable()
    k.need(not n.SOURCE.exists() and not Path("/opt/runtime").exists(), "Fresh source and runtime are required")
    commit = binding["provider"]["head_sha"]
    git = executable("git")
    command("source_init", [git, "init", "--quiet", str(n.SOURCE)])
    command("source_remote", [git, "-C", str(n.SOURCE), "remote", "add", "origin",
                              "https://github.com/TrillionniumFoundation/hepta-private-ci.git"])
    token = os.environ.get("GITHUB_TOKEN")
    k.need(bool(token), "GitHub authentication is required for the registered source")
    auth = base64.b64encode(("x-access-token:" + token).encode()).decode()
    command("source_fetch", [git, "-C", str(n.SOURCE), "fetch", "--no-tags", "--depth=1", "origin", commit],
            {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
             "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic " + auth})
    command("source_checkout", [git, "-C", str(n.SOURCE), "checkout", "--quiet", "--detach", "FETCH_HEAD"])
    c.original_source(binding)
    k.need(c.git(n.SOURCE, "rev-parse", "HEAD").decode().strip() == commit
           and not c.git(n.SOURCE, "status", "--porcelain").strip(), "Original source is not pristine at its exact commit")
    input_item = n.descriptor(n.SOURCE / c.OPS_NAMESPACE / "INPUT_CONTRACT.json")
    runtime_item = n.descriptor(n.SOURCE / "tools/parameter_field_executor/runtime_contract.json")
    target = n.read(input_item)
    k.need(target["python"] == "/opt/runtime/venv/bin/python", "Unexpected canonical Python")
    runtime_root = Path("/opt/runtime")
    runtime_root.mkdir()
    archive = runtime_root / "python.tar.gz"
    expected_archive = target["public_python_archive"]
    command("python_download", [executable("curl"), "--fail", "--location", "--silent", "--show-error",
                                "--output", str(archive), expected_archive["url"]])
    actual = n.descriptor(archive)
    k.need(actual["bytes"] == expected_archive["bytes"] and actual["sha256"] == expected_archive["sha256"],
           "Public Python archive differs")
    command("python_extract", [executable("tar"), "-xzf", str(archive), "-C", str(runtime_root)])
    python_files = {}
    for row in target["public_python_files"]:
        item = n.descriptor(runtime_root / row["name"])
        k.need(item["bytes"] == row["size"] and item["sha256"] == row["sha256"], "Extracted public Python differs")
        python_files[row["name"]] = item
    command("venv", ["/opt/runtime/python/bin/python3.12", "-m", "venv", "/opt/runtime/venv"])
    python = target["python"]
    command("packages", [python, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir",
                         "--only-binary=:all:", "-r", str(n.SOURCE / "tools/parameter_field_executor/packages.txt")])
    command("torch", [python, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", "--no-deps",
                      "--require-hashes", "-r", str(n.SOURCE / "tools/parameter_field_executor/torch-wheel.txt")])
    runtime_path = directory / "RUNTIME.json"
    command("qualification", [python, "-B", str(n.SOURCE / "tools/parameter_field_executor/diagnose.py"),
                              "--output", str(runtime_path)])
    runtime = n.descriptor(runtime_path)
    reason = assess_runtime(n.read(runtime), target)
    source = n.write(directory / "SOURCE_IDENTITY.json", {
        "schema": "hepta.visited-counterfactual.original-source-preparation.1", "source_commit": commit,
        "canonical_source": str(n.SOURCE), "input_contract": input_item, "runtime_contract": runtime_item,
        "public_python_files": python_files, "source_pristine": True, "scientific_inputs_downloaded": False,
        "scientific_values_decoded": False, "scientific_workers_started": 0,
    })
    return {"runtime": runtime, "source": source, "input_contract": input_item,
            "runtime_contract": runtime_item, "reason": reason, "python": python}


def sdk(directory, command):
    c, _, gate = n.portable()
    root = Path("/work/transport-sdk")
    root.mkdir(exist_ok=False)
    for name in ("package.json", "package-lock.json"):
        source = n.SOURCE / c.OPS_NAMESPACE / name
        original = n.descriptor(source)
        target = root / name
        with source.open("rb") as stream, target.open("xb") as output:
            shutil.copyfileobj(stream, output)
            output.flush()
            os.fsync(output.fileno())
        item = n.descriptor(target)
        k.need((item["bytes"], item["sha256"]) == (original["bytes"], original["sha256"]), "SDK lock copy differs")
    command("sdk", [executable("npm"), "ci", "--prefix", str(root), "--ignore-scripts", "--no-audit", "--no-fund"])
    return n.write(directory / "SDK.json", {
        "schema": "hepta.visited-counterfactual.sdk-preparation.1", "sdk": gate.sdk_identity(),
        "actual_node_executable": os.environ["HEPTA_ARTIFACT_NODE"], "artifact_runtime_credentials_persisted": False,
    })
