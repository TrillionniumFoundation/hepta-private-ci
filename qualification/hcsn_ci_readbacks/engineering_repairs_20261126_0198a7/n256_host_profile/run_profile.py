"""One isolated host-metadata observation; never enter an N256 numerical path."""
import copy
import hashlib
import importlib.abc
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import resource
import signal
import subprocess
import sys
import tarfile
import time
import traceback
from types import ModuleType

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
PREFIX = "qualification/hcsn_ci_readbacks/engineering_repairs_20261126_0198a7/n256_host_profile/"
WORKFLOW = ".github/workflows/hepta-hcsn-n256-host-metadata-20261126.yml"
LEGACY = "qualification/hcsn_currentstate_n256_hosted_runtime_snapshot/"
OBSERVER = "qualification/hcsn_currentstate_n256_firststep_resource_snapshot/snapshot_source.py"
FORBIDDEN = {"numpy", "scipy", "torch", "qualification"}
SOURCE_NAMES = {PREFIX + name for name in ("run_profile.py", "PROFILE.json", "requirements.txt", "LEGACY_SOURCE.tar.xz", "LEGACY_SOURCE.index.json")} | {WORKFLOW}
LEGACY_NAMES = {
    "capture_sha256": LEGACY + "capture.py",
    "request_sha256": LEGACY + "REQUEST_V2.json",
    "request_v1_sha256": LEGACY + "REQUEST.json",
    "requirements_sha256": LEGACY + "requirements.txt",
    "source_freeze_v1_sha256": LEGACY + "SOURCE_FREEZE.json",
    "tests_sha256": LEGACY + "test_source.py",
    "verifier_sha256": LEGACY + "verify_source.py",
    "workflow_sha256": ".github/workflows/hcsn-currentstate-n256-hosted-runtime-snapshot.yml",
    "snapshot_source_sha256": OBSERVER,
    "attempt001_job_log_b64_sha256": LEGACY + "evidence/attempt001/JOB_LOG.txt.b64",
    "attempt001_terminal_sha256": LEGACY + "evidence/attempt001/TERMINAL.json",
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, maximum=1_048_576):
    require(path.is_file() and not path.is_symlink(), "nonregular input")
    require(path.stat().st_size <= maximum, "input size limit")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    require(len(raw) <= maximum, "input grew beyond limit")
    return raw


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("nonfinite JSON constant: " + value)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def write(path, value):
    raw = (json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    require(len(raw) <= 65_536, "receipt size limit")
    with path.open("xb") as stream:
        stream.write(raw)


def verify_sources():
    freeze_raw = read(ROOT / "SOURCE_FREEZE.json")
    freeze = strict_json(freeze_raw)
    require(set(freeze["files"]) == SOURCE_NAMES, "new source denominator")
    for name, identity in freeze["files"].items():
        raw = read(REPO / name)
        require(len(raw) == identity["bytes"] and sha(raw) == identity["sha256"], "new source changed: " + name)
    return sha(freeze_raw)


def materialize(output):
    index = strict_json(read(ROOT / "LEGACY_SOURCE.index.json"))
    raw = read(ROOT / "LEGACY_SOURCE.tar.xz")
    require(len(raw) == index["archive_bytes"] and sha(raw) == index["archive_sha256"], "legacy archive identity")
    with tarfile.open(ROOT / "LEGACY_SOURCE.tar.xz", "r:xz") as archive:
        entries = archive.getmembers()
        require(len(entries) == 14 and len({x.name for x in entries}) == 14, "legacy member denominator")
        require(all(x.isfile() and x.size <= 65_536 for x in entries), "legacy member type or size")
        require(sum(x.size for x in entries) <= 262_144, "legacy total size")
        manifest_raw = archive.extractfile("MANIFEST.json").read()
        require(sha(manifest_raw) == index["manifest_sha256"], "legacy manifest identity")
        manifest = strict_json(manifest_raw)
        require(set(manifest["files"]) | {"MANIFEST.json"} == {x.name for x in entries}, "legacy file set")
        for name, identity in manifest["files"].items():
            relative = PurePosixPath(name)
            require(not relative.is_absolute() and ".." not in relative.parts, "unsafe legacy path")
            content = archive.extractfile(name).read()
            require(len(content) == identity["bytes"] and sha(content) == identity["sha256"], "legacy payload identity")
            path = output / "legacy" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(content)


def verify_legacy(output, profile):
    base = output / "legacy"
    raw = read(base / (LEGACY + "SOURCE_FREEZE_V2.json"))
    require(sha(raw) == profile["legacy_source_freeze_v2_sha256"], "original V2 freeze changed")
    freeze = strict_json(raw)
    for key, name in LEGACY_NAMES.items():
        require(sha(read(base / name)) == freeze[key], "original V2 source mismatch: " + key)
    require(sha(read(base / OBSERVER)) == profile["original_observer_sha256"], "original observer changed")
    require(sha(read(base / (LEGACY + "evidence/attempt002/HOSTED_OBSERVATION.json"))) == profile["original_observation_sha256"], "original successful observation changed")


def verify_event(profile):
    require(os.environ.get("GITHUB_EVENT_NAME") == "push", "only ordinary push")
    require(os.environ.get("GITHUB_RUN_ATTEMPT") == "1", "consumed attempt")
    require(os.environ.get("GITHUB_REPOSITORY") == "TrillionniumFoundation/hepta-private-ci", "repository identity")
    ref = "refs/heads/" + profile["branch"]
    require(os.environ.get("GITHUB_REF") == ref, "branch identity")
    workflow_ref = "TrillionniumFoundation/hepta-private-ci/" + WORKFLOW + "@" + ref
    require(os.environ.get("GITHUB_WORKFLOW_REF") == workflow_ref, "workflow path identity")
    event = strict_json(read(Path(os.environ["GITHUB_EVENT_PATH"])))
    require(event.get("created") is True and event.get("deleted") is False and event.get("forced") is False, "only first nonforced branch creation")
    require(event.get("before") == "0" * 40 and event.get("ref") == ref, "branch creation payload")
    commit = os.environ.get("GITHUB_SHA", "")
    require(len(commit) == 40 and all(c in "0123456789abcdef" for c in commit), "commit identity")
    require(event.get("after") == commit and os.environ.get("GITHUB_WORKFLOW_SHA") == commit, "workflow/source commit mismatch")
    return {name: os.environ.get(name) for name in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_REF", "GITHUB_EVENT_NAME", "GITHUB_WORKFLOW_REF", "GITHUB_WORKFLOW_SHA")}


class MetadataImportsOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in FORBIDDEN:
            raise RuntimeError("forbidden numerical/project import: " + fullname)
        return None


def check_host(actual, expected):
    require(actual == expected, "host identity differs")


def child(output, profile):
    started, cpu = time.monotonic(), time.process_time()
    require(output.is_dir() and (output / "STARTED.json").is_file(), "launcher intent missing")
    write(output / "CHILD_STARTED.json", {"profile_identity": profile["identity"], "status": "STARTED"})
    counts = {name: 0 for name in profile["child_exact_counts"]}
    result = {"status": "FAILED", "counts": counts, "runtime_admitted": False, "resource_admitted": False, "all_closed": False}
    try:
        result["source_freeze_sha256"] = verify_sources()
        counts["source_checks"] += 1
        verify_legacy(output, profile)
        counts["legacy_source_checks"] += 1
        result["github"] = verify_event(profile)
        require(not any(name.split(".")[0] in FORBIDDEN for name in sys.modules), "forbidden module already loaded")
        sys.meta_path.insert(0, MetadataImportsOnly())
        def audit(event, args):
            if event in {"subprocess.Popen", "os.system", "os.fork", "os.forkpty", "socket.__new__"}:
                raise RuntimeError("metadata child may not spawn or use network")
        sys.addaudithook(audit)
        observer = ModuleType("_frozen_n256_host_metadata")
        source = read(output / "legacy" / OBSERVER)
        exec(compile(source, str(output / "legacy" / OBSERVER), "exec"), observer.__dict__)
        counts["frozen_observer_module_loads"] += 1
        distributions, init_hashes = {}, {}
        for name in ("numpy", "scipy"):
            distributions[name] = observer._distribution(name)
            counts["original_distribution_calls"] += 1
            path = importlib.metadata.distribution(name).locate_file(name + "/__init__.py")
            init_hashes[name] = observer._sha256(path)
            counts["original_sha256_calls"] += 1
        executable_hash = observer._sha256(sys.executable)
        counts["original_sha256_calls"] += 1
        os_release = platform.freedesktop_os_release()
        host = {
            "os_id": os_release.get("ID"), "os_version": os_release.get("VERSION_ID"),
            "python_implementation": platform.python_implementation(), "python_version": platform.python_version(),
            "machine": platform.machine(), "numpy_version": distributions["numpy"]["version"],
            "scipy_version": distributions["scipy"]["version"],
            "thread_environment": {name: os.environ.get(name) for name in profile["host"]["thread_environment"]},
        }
        result["host"] = host
        check_host(host, profile["host"])
        counts["host_validation_calls"] += 1
        controls = []
        for field, value in (("os_version", "26.04"), ("python_version", "3.12.16"), ("numpy_version", "2.2.6"), ("scipy_version", "1.16.0"), ("thread_environment", {**host["thread_environment"], "OMP_NUM_THREADS": "2"})):
            bad = copy.deepcopy(host)
            bad[field] = value
            try:
                counts["host_validation_calls"] += 1
                check_host(bad, profile["host"])
            except ValueError:
                controls.append({"field": field, "rejected": True})
                counts["host_negative_controls"] += 1
            else:
                raise ValueError("host negative accepted: " + field)
        meminfo = observer._meminfo()
        counts["original_meminfo_calls"] += 1
        unified, chain = observer._cgroup_chain()
        counts["original_cgroup_chain_calls"] += 1
        boot = observer._read("/proc/sys/kernel/random/boot_id")
        counts["original_read_calls"] += 1
        result["metadata"] = {"distributions": distributions, "package_init_sha256": init_hashes, "python_executable": str(Path(sys.executable).resolve()), "python_executable_sha256": executable_hash, "meminfo_kib": meminfo, "self_cgroup": unified, "ancestor_cgroup_chain": chain, "boot_id": boot}
        counts["host_metadata_observations"] += 1
        result["negative_controls"] = controls
        require(not any(name.split(".")[0] in FORBIDDEN for name in sys.modules), "forbidden import observed")
        require(verify_sources() == result["source_freeze_sha256"], "source freeze changed")
        counts["source_checks"] += 1
        verify_legacy(output, profile)
        counts["legacy_source_checks"] += 1
        require(counts == profile["child_exact_counts"] and all(type(x) is int for x in counts.values()), "child count denominator")
        result["status"] = "PASS_METADATA_ONLY_HOLD_ADMISSION"
    except Exception as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)}
        traceback.print_exc()
    result.update({"wall_s": time.monotonic() - started, "process_cpu_s": time.process_time() - cpu, "forbidden_imports_observed": sorted({name.split(".")[0] for name in sys.modules} & FORBIDDEN), "profile_identity": profile["identity"]})
    write(output / "RESULT.json", result)
    return 0 if result["status"] == "PASS_METADATA_ONLY_HOLD_ADMISSION" else 1


def child_limits():
    resource.setrlimit(resource.RLIMIT_CPU, (20, 21))
    resource.setrlimit(resource.RLIMIT_AS, (268_435_456, 268_435_456))
    resource.setrlimit(resource.RLIMIT_FSIZE, (65_536, 65_536))


def launch(output, profile):
    output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    process = None
    receipt = {"status": "FAILED", "child_processes": 0, "automatic_retry": False, "hard_wall_s": 30, "hard_cpu_soft_hard_s": [20, 21], "hard_address_space_bytes": 268_435_456, "per_stream_and_receipt_bytes": 65_536}
    def deadline(signum, frame):
        raise TimeoutError("45-second launcher ceiling")
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(45)
    try:
        github = verify_event(profile)
        freeze = verify_sources()
        write(output / "STARTED.json", {"status": "STARTED", "profile_identity": profile["identity"], "source_freeze_sha256": freeze, "github": github})
        materialize(output)
        verify_legacy(output, profile)
        with (output / "contract.stdout").open("xb") as stdout, (output / "contract.stderr").open("xb") as stderr:
            process = subprocess.Popen([sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--child", str(output)], stdout=stdout, stderr=stderr, start_new_session=True, preexec_fn=child_limits)
            receipt["child_processes"] = 1
            try:
                receipt["exit_code"] = process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                receipt["exit_code"] = process.wait()
                receipt["timeout"] = True
        raw = read(output / "RESULT.json", 65_536)
        result = strict_json(raw)
        receipt["result_sha256"] = sha(raw)
        receipt["observed_counts"] = result["counts"]
        require(receipt["exit_code"] == 0 and result["status"] == "PASS_METADATA_ONLY_HOLD_ADMISSION", "metadata child failed")
        require(result["source_freeze_sha256"] == freeze and result["counts"] == profile["child_exact_counts"], "child binding or denominator")
        receipt["source_freeze_sha256"] = freeze
        receipt["status"] = "PASS_METADATA_ONLY_HOLD_ADMISSION"
    except Exception as error:
        receipt["error"] = {"type": type(error).__name__, "message": str(error)}
        traceback.print_exc()
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        signal.alarm(0)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt.update({"wall_s": time.monotonic() - start, "child_cpu_s": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime, "child_maxrss_kib": after.ru_maxrss, "runtime_admitted": False, "resource_admitted": False, "all_closed": False})
    write(output / "LAUNCH_RESULT.json", receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "PASS_METADATA_ONLY_HOLD_ADMISSION" else 1


def main():
    require(len(sys.argv) == 3 and sys.argv[1] in {"--output", "--child"}, "expected one output mode")
    profile = strict_json(read(ROOT / "PROFILE.json"))
    output = Path(sys.argv[2]).resolve()
    return child(output, profile) if sys.argv[1] == "--child" else launch(output, profile)


if __name__ == "__main__":
    raise SystemExit(main())
