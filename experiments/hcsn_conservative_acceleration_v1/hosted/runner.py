"""Hosted-only orchestration around unchanged scientific implementations.

Each subprocess has an exclusive log and wait4 receipt. Outer subprocess costs
include waited descendants; the nested study/native/resume clocks are detail,
not additional charges. Generated HOSTED_PROTOCOL is separate from public design.
"""

import argparse
import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "experiments/hcsn_conservative_acceleration_v1"
MODULE = "experiments.hcsn_conservative_acceleration_v1"
WORKFLOW = ".github/workflows/hcsn-conservative-hosted.yml"
CORE_KEYS = ("analysis", "data_design", "execution", "fidelity", "models",
             "optimization", "primary_seeds", "primary_tasks", "schema",
             "supplementary_seed", "supplementary_tasks", "timing")
SAFE_ENV = ("GITHUB_ACTIONS", "GITHUB_SHA", "GITHUB_REPOSITORY", "GITHUB_RUN_ID",
            "GITHUB_RUN_ATTEMPT", "GITHUB_WORKFLOW", "GITHUB_JOB", "GITHUB_REF",
            "RUNNER_ENVIRONMENT", "RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion")
CONTAINER_IMAGE = "python:3.12.14@sha256:6dc02694c53fde08b0e39de9273a708d2f2a612f77dc173a64835c3f7a40ee35"
CONTAINER_OPTIONS = "--memory=8g --memory-swap=8g --cpus=2 --cgroupns=private"
PACKAGE_VERSIONS = {"torch": "2.8.0+cpu", "numpy": "2.3.5", "scipy": "1.17.0"}
CGROUP_FILES = ("memory.max", "memory.current", "memory.events", "memory.stat",
                "memory.swap.max", "cpu.max", "cpu.stat", "cgroup.controllers")


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_bytes())


def digest(path, git=False):
    path = Path(path)
    value = hashlib.sha1(b"blob " + str(path.stat().st_size).encode() + b"\0") if git else hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def rooted(name, package_only=False):
    part = Path(name)
    if part.is_absolute() or ".." in part.parts:
        raise ValueError("Expected a bounded repository-relative path: " + str(name))
    path = ROOT / part
    scope = PACKAGE if package_only else ROOT
    if path.is_symlink() or not path.resolve().is_relative_to(scope):
        raise ValueError("Path escapes its declared scope: " + str(name))
    return path


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def checked_file(row):
    path = rooted(row["path"])
    if digest(path) != row["sha256"]:
        raise ValueError("Published file SHA256 mismatch: " + row["path"])
    return path


class RunBook:
    def __init__(self, folder, mode):
        self.folder, self.mode = folder, mode
        folder.mkdir(parents=True, exist_ok=True)
        self.records, self.started_cpu, self.started_wall = [], time.process_time(), time.monotonic()
        write_new(folder / ("RUNNER_" + mode.upper() + "_START.json"),
                  dict(utc=utc(), mode=mode, github={k: os.environ.get(k) for k in SAFE_ENV},
                       runner_sha256=digest(__file__)))

    def run(self, name, command, required=True):
        log = self.folder / (name + ".log")
        started = time.monotonic()
        record = dict(name=name, command=[str(x) for x in command], cwd=str(ROOT),
                      started_utc=utc(), log=relative(log), process_created=False)
        env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                   MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
        child = None
        try:
            with log.open("xb") as stream:
                child = subprocess.Popen(record["command"], cwd=ROOT, env=env,
                    stdout=stream, stderr=subprocess.STDOUT)
                record["process_created"] = True
                _, status, usage = os.wait4(child.pid, 0)
                child.returncode = os.waitstatus_to_exitcode(status)
                record.update(exit_code=child.returncode,
                    complete_child_cpu_seconds=usage.ru_utime + usage.ru_stime,
                    user_cpu_seconds=usage.ru_utime, system_cpu_seconds=usage.ru_stime,
                    peak_rss_bytes=usage.ru_maxrss * 1024)
        except BaseException:
            record["runner_exception"] = traceback.format_exc()
            if child is not None and child.returncode is None:
                try:
                    child.terminate()
                except ProcessLookupError:
                    pass
                try:
                    _, status, usage = os.wait4(child.pid, 0)
                    child.returncode = os.waitstatus_to_exitcode(status)
                    record.update(exit_code=child.returncode,
                        complete_child_cpu_seconds=usage.ru_utime + usage.ru_stime,
                        user_cpu_seconds=usage.ru_utime, system_cpu_seconds=usage.ru_stime,
                        peak_rss_bytes=usage.ru_maxrss * 1024)
                except ChildProcessError:
                    record["complete_child_cpu_seconds"] = None
            raise
        finally:
            record.update(wall_seconds=time.monotonic()-started, ended_utc=utc(),
                scope="Whole direct child wait4, including imports and waited descendants; nested costs are not additive")
            self.records.append(record)
            write_new(self.folder / (name + "_EXECUTION.json"), record)
        if required and record["exit_code"] != 0:
            raise RuntimeError("Subprocess failed; original log retained: " + name)
        return record

    def finish(self, result):
        known = [r["complete_child_cpu_seconds"] for r in self.records
                 if r.get("complete_child_cpu_seconds") is not None]
        value = dict(schema="hcsn-hosted-runner-stage.v1", mode=self.mode, utc=utc(),
            result=result, subprocesses=self.records,
            direct_child_cpu_seconds=sum(known), all_child_costs_known=len(known)==len(self.records),
            coordinator_self_cpu_seconds=time.process_time()-self.started_cpu,
            stage_wall_seconds=time.monotonic()-self.started_wall,
            accounting="Direct child receipts are disjoint within this stage. Do not add study worker, optimizer, analysis-body, native or resume subtotals again. Coordinator self CPU excludes children and starts at RunBook creation.",
            disk=shutil.disk_usage(ROOT)._asdict())
        write_new(self.folder / ("RUNNER_" + self.mode.upper() + "_RESULT.json"), value)
        return value


def validate_execution_environment(container, environment):
    expected = dict(image=CONTAINER_IMAGE, options=CONTAINER_OPTIONS,
        platform="linux/amd64", python_version="3.12.14", memory_bytes=8*1024**3,
        cpu_quota_cores=2, swap_bytes=0, private_cgroup_namespace=True)
    if any(container.get(key) != value for key, value in expected.items()):
        raise ValueError("Public execution-container identity or resource contract changed")
    if (environment["python_version"] != expected["python_version"]
            or environment["packages"] != PACKAGE_VERSIONS
            or environment["architecture"] != "x86_64"):
        raise ValueError("Actual Python, package versions or architecture differ from the public plan")
    if not environment["dockerenv_exists"]:
        raise ValueError("Expected the declared Docker job-container environment")
    cgroup = environment["cgroup"]
    required_nonempty = ("memory.max", "memory.current", "memory.events", "memory.stat",
                         "memory.swap.max", "cpu.max")
    if set(cgroup) != set(CGROUP_FILES) or any(not cgroup[name].strip() for name in required_nonempty):
        raise ValueError("Required cgroup v2 resource interfaces are missing or empty")
    if (int(cgroup["memory.max"].strip()) != expected["memory_bytes"]
            or int(cgroup["memory.swap.max"].strip()) != expected["swap_bytes"]
            or int(cgroup["memory.current"].strip()) < 0):
        raise ValueError("Actual cgroup memory or swap limit differs from the public plan")
    quota, period = (int(value) for value in cgroup["cpu.max"].split())
    if period <= 0 or quota != expected["cpu_quota_cores"] * period:
        raise ValueError("Actual cgroup CPU quota differs from the public plan")
    events = dict(row.split() for row in cgroup["memory.events"].splitlines())
    if not {"oom", "oom_kill"}.issubset(events):
        raise ValueError("Required cgroup OOM accounting fields are absent")


def execution_environment(plan):
    container = plan["execution_container"]
    environment = dict(python=sys.version, python_version=".".join(map(str, sys.version_info[:3])),
        executable=sys.executable, platform=" ".join(os.uname()),
        architecture=os.uname().machine, cpu_count=os.cpu_count(),
        packages={name: importlib.metadata.version(name) for name in PACKAGE_VERSIONS},
        disk=shutil.disk_usage(ROOT)._asdict(),
        os_release=Path("/etc/os-release").read_text(), dockerenv_exists=Path("/.dockerenv").is_file(),
        proc_meminfo=Path("/proc/meminfo").read_text(),
        proc_self_cgroup=Path("/proc/self/cgroup").read_text(),
        cgroup_namespace=os.readlink("/proc/self/ns/cgroup"),
        cgroup={name: (Path("/sys/fs/cgroup") / name).read_text() for name in CGROUP_FILES},
        coordinator_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        declared_execution_container=container,
        container_image_digest_independently_attested=False,
        image_identity_scope="Image digest is pinned by the public workflow and plan. Inside-container observations verify versions and resource limits; they do not independently attest the image digest.")
    validate_execution_environment(container, environment)
    return environment


def public_identity(plan, plan_path, book):
    github = {k: os.environ.get(k) for k in SAFE_ENV}
    sha = github["GITHUB_SHA"] or ""
    if (github["GITHUB_ACTIONS"] != "true" or github["RUNNER_ENVIRONMENT"] != "github-hosted"
            or github["RUNNER_OS"] != "Linux" or github["RUNNER_ARCH"] != "X64"
            or (github["GITHUB_REPOSITORY"] or "").lower() != plan["repository"].lower()
            or len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha)):
        raise ValueError("This launcher requires the declared GitHub-hosted Linux x64 execution identity")
    if plan["required_runner"] != "ubuntu-24.04" or github["ImageOS"] not in (None, "ubuntu24"):
        raise ValueError("Hosted runner image differs from the public plan")
    book.run("git_head", ["git", "rev-parse", "HEAD"])
    if (book.folder / "git_head.log").read_text().strip() != sha:
        raise ValueError("Checkout HEAD differs from GITHUB_SHA")
    design_path = checked_file(plan["design"])
    original_path = checked_file(plan["original_protocol"])
    if digest(original_path) != plan["original_protocol_sha256"]:
        raise ValueError("Original seal identity fields disagree")
    binding_path = checked_file(plan["execution_binding_plan"])
    design, original = read(design_path), read(original_path)
    if (plan["schema"] != "hcsn-hosted-execution-plan.v1" or plan["expected_jobs"] != 70
            or design["status"] != "draft_not_registered"
            or set(plan["preserved_design_keys"]) != set(CORE_KEYS)
            or not plan["full_cohort_rerun"] or plan["reuse_original_completed_rows"]):
        raise ValueError("Hosted plan status, scope or job contract changed")
    snapshot = plan["original_design_snapshot"]
    if snapshot["status"] != "draft_not_registered":
        raise ValueError("Original design snapshot is not the original draft")
    for key in CORE_KEYS:
        if design[key] != original[key] or snapshot[key] != original[key]:
            raise ValueError("Frozen scientific design differs: " + key)
    if snapshot["interpretation"] != original["interpretation"]:
        raise ValueError("Original interpretation snapshot changed")
    if design["execution"]["expected_jobs"] != 70:
        raise ValueError("Expected 70 original jobs")
    baseline_path = PACKAGE / "SOURCE_BASELINE.json"
    baseline = read(baseline_path)
    if len(baseline["files"]) != 162 or baseline["remote_parent"] != "63fd568b177c0456ddd8b590e3ac77d35307c0c4":
        raise ValueError("Frozen parent snapshot changed")
    frozen, public_files = {}, {relative(plan_path), relative(design_path), relative(original_path),
                               relative(binding_path), relative(baseline_path)}
    for row in baseline["files"]:
        path = checked_file(row)
        if digest(path, git=True) != row["git_blob"]:
            raise ValueError("Parent Git object changed: " + row["path"])
        public_files.add(row["path"])
        if path.suffix == ".py":
            frozen[row["path"]] = row["sha256"]
    for path in sorted(PACKAGE.glob("*.py")) + [baseline_path]:
        frozen[relative(path)] = digest(path)
    if frozen != original["source_files_sha256"]:
        raise ValueError("Frozen top-level/model/analysis source domain changed")
    public_files.update(frozen)
    extras = {relative(p): digest(p) for p in sorted((PACKAGE / "hosted").glob("*.py"))}
    for path in (plan_path, design_path, binding_path, ROOT / WORKFLOW):
        extras[relative(path)] = digest(path)
    public_files.update(extras)
    native = ROOT / "experiments/hcsn_free_boundary_v1/native_vendor"
    for row in read(native / "MANIFEST.json")["parts"]:
        path = native / row["file"]
        if digest(path) != row["sha256"] or path.stat().st_size != row["bytes"]:
            raise ValueError("Pinned native transport changed")
        public_files.add(relative(path))
    if rooted(plan["original_design"]["path"]).exists():
        original_design_path = checked_file(plan["original_design"])
        if read(original_design_path) != snapshot:
            raise ValueError("Original design file and embedded snapshot disagree")
        public_files.add(relative(original_design_path))
    book.run("git_public_tree", ["git", "ls-tree", "-r", "-z", sha, "--", *sorted(public_files)])
    entries = {}
    for item in (book.folder / "git_public_tree.log").read_bytes().split(b"\0"):
        if item:
            fields, name = item.split(b"\t", 1)
            mode, kind, blob = fields.decode().split()
            if kind != "blob" or mode not in ("100644", "100755"):
                raise ValueError("Expected regular tracked source file")
            entries[name.decode()] = blob
    if set(entries) != public_files or any(digest(rooted(p), git=True) != b for p, b in entries.items()):
        raise ValueError("Worktree differs from public GITHUB_SHA source/plan tree")
    environment = execution_environment(plan)
    result = dict(schema="hcsn-hosted-public-identity.v1", github=github, environment=environment,
        public_commit=sha, public_url="https://github.com/"+plan["repository"]+"/tree/"+sha,
        plan_sha256=digest(plan_path), design_sha256=digest(design_path),
        binding_plan_sha256=digest(binding_path), original_protocol_sha256=digest(original_path),
        original_seal_commit=plan["original_seal_commit"], frozen_source_files_sha256=frozen,
        extra_bootstrap_files_sha256=extras, public_git_blobs=entries,
        bootstrap_is_frozen_scientific_source=False, dynamic_protocol_in_extra_source_hashes=False)
    write_new(book.folder / "PUBLIC_IDENTITY.json", result)
    return result


def unchanged(identity):
    files = dict(identity["frozen_source_files_sha256"], **identity["extra_bootstrap_files_sha256"])
    changed = [name for name, sha in files.items() if digest(rooted(name)) != sha]
    if changed:
        raise ValueError("Source changed during execution: " + repr(changed))


def paths(plan):
    names = ("protocol_path", "output", "preflight", "kernel_proof",
             "prepare_output", "analysis_output", "finalize_output")
    value = {name: rooted(plan[name], package_only=True) for name in names}
    if value["output"] != PACKAGE / "results/comparison002_hosted":
        raise ValueError("Hosted cohort output changed")
    return value


def prepare(plan, place, identity, book):
    if place["protocol_path"].exists() or place["output"].exists():
        raise FileExistsError("Preserve all previous protocol/cohort output")
    book.run("data_bootstrap", [sys.executable, "-m", MODULE+".hosted.restore_data",
        "--repo", ROOT, "--receipt", book.folder/"DATA_BOOTSTRAP.json"])
    if not read(book.folder/"DATA_BOOTSTRAP.json")["passed"]:
        raise ValueError("Data bootstrap did not pass")
    book.run("kernel_validation", [sys.executable, "-m", MODULE+".validation",
        "--output", place["kernel_proof"].parent])
    if not read(place["kernel_proof"])["passed"]:
        raise ValueError("Independent kernel acceptance did not pass")
    book.run("model_runtime_tests", [sys.executable, "-m", "unittest",
        MODULE+".model_tests", MODULE+".runtime_tests", "-v"])
    shutil.copyfile(checked_file(plan["design"]), place["protocol_path"])
    book.run("train_preflight", [sys.executable, "-m", MODULE+".study", "preflight",
        "--protocol", place["protocol_path"], "--output", place["preflight"].parent])
    book.run("register", [sys.executable, "-m", MODULE+".study", "register",
        "--protocol", place["protocol_path"], "--output", place["output"],
        "--preflight", place["preflight"], "--kernel-proof", place["kernel_proof"],
        "--av-cache", ROOT/"experiments/hcsn_real_av_v1/data"])
    protocol = read(place["protocol_path"])
    if (protocol["status"] != "registered" or len(protocol["jobs"]) != 70
            or protocol["source_files_sha256"] != identity["frozen_source_files_sha256"]
            or protocol["jobs"] != read(checked_file(plan["original_protocol"]))["jobs"]
            or protocol["output"] != plan["output"]):
        raise ValueError("Frozen registration produced a different source/job/output contract")
    unchanged(identity)
    receipt = dict(passed=True, public_commit=identity["public_commit"],
        plan_sha256=identity["plan_sha256"], protocol_path=relative(place["protocol_path"]),
        protocol_sha256=digest(place["protocol_path"]), jobs=70,
        source_files_sha256=protocol["source_files_sha256"],
        extra_bootstrap_files_sha256=identity["extra_bootstrap_files_sha256"],
        registration_sha256=digest(place["output"]/"REGISTRATION.json"),
        training_started=False, prior_rows_reused=False)
    write_new(book.folder/"PREPARED.json", receipt)
    return receipt


def prepared(place, identity):
    receipt = read(place["prepare_output"]/"PREPARED.json")
    if (not receipt["passed"] or receipt["public_commit"] != identity["public_commit"]
            or receipt["plan_sha256"] != identity["plan_sha256"]
            or receipt["protocol_sha256"] != digest(place["protocol_path"])
            or receipt["source_files_sha256"] != identity["frozen_source_files_sha256"]
            or receipt["extra_bootstrap_files_sha256"] != identity["extra_bootstrap_files_sha256"]
            or receipt["registration_sha256"] != digest(place["output"]/"REGISTRATION.json")):
        raise ValueError("Prepare artifact/public identity changed")
    return receipt


def train(plan, place, identity, book):
    prepared(place, identity)
    record = book.run("HOSTED_TRAIN", [sys.executable, "-m", MODULE+".study", "run",
        "--protocol", place["protocol_path"], "--output", place["output"],
        "--public-commit", identity["public_commit"]], required=False)
    unchanged(identity)
    return dict(passed=record["exit_code"]==0, train_exit_code=record["exit_code"],
        complete_receipt=(place["output"]/"COMPLETE.json").exists(),
        aborted_receipt=(place["output"]/"ABORTED.json").exists(),
        protocol_sha256=digest(place["protocol_path"]), prior_rows_reused=False)


def complete_gate(place):
    protocol, analysis = read(place["protocol_path"]), read(place["analysis_output"]/"ANALYSIS.json")
    terminal_path = place["output"]/"COMPLETE.json"
    if not terminal_path.exists():
        return False, analysis
    terminal = read(terminal_path)
    records = terminal["records"]
    good = (terminal.get("completed") is True and len(protocol["jobs"])==len(records)==70
        and terminal["protocol_sha256"]==digest(place["protocol_path"])
        and {row["index"] for row in records}==set(range(70))
        and all(row["returncode"]==0 and row["job"]==protocol["jobs"][row["index"]] for row in records)
        and analysis.get("complete") is True and analysis.get("valid_jobs")==70
        and analysis.get("expected_jobs")==70 and analysis.get("errors")==[]
        and analysis["protocol_sha256"]==digest(place["protocol_path"]))
    return bool(good), analysis


def selected_binding(plan, place, book):
    rule_path = checked_file(plan["execution_binding_plan"])
    rule, protocol = read(rule_path), read(place["protocol_path"])
    required = rule["required_job"]
    if required != dict(family="fixed", task="selective_copy", model="hcsn_accelerated", seed=98031):
        raise ValueError("Predeclared runtime job changed")
    matches = [job for job in protocol["jobs"] if all(job[k]==v for k, v in required.items())]
    if len(matches) != 1:
        raise ValueError("Binding job missing or duplicated")
    job = matches[0]
    directory = place["output"]/"runs"/"__".join(str(job[k]) for k in ("family", "task", "model", "seed"))
    selection, summary, candidates = (read(directory/name) for name in ("selection.json", "summary.json", "checkpoints.json"))
    best = min(candidates, key=lambda row: (row["validation"]["cross_entropy"], row["step"]))
    weights = directory/"selected.npz"
    config = rule["model_config"]
    expected_config = dict(name="distribution_free_dual", input_dim=protocol["data"][job["task"]]["input_dim"],
        output_dim=protocol["data"][job["task"]]["output_dim"], width=protocol["optimization"]["width"],
        depth=protocol["optimization"]["depth"], seed=job["seed"])
    if (selection["checkpoint"] != best or selection["completed_candidates"] != 1
            or selection != summary["selection"] or summary["job"] != job
            or summary["status"] != "completed" or digest(weights) != best["sha256"]
            or selection["protocol_sha256"] != digest(place["protocol_path"])
            or config != expected_config or any(summary["config"][k]!=v for k, v in config.items())
            or rule["backend"] != "accelerated" or rule["profile"] != "stable"
            or summary["config"]["operator_backend"] != "accelerated"
            or summary["config"]["probability_profile"] != "stable"):
        raise ValueError("Validation-only selected checkpoint/config binding failed")
    config_path = book.folder/"MODEL_CONFIG.json"
    write_new(config_path, config)
    binding = dict(job=job, checkpoint=relative(weights), checkpoint_sha256=digest(weights),
        selection_sha256=digest(directory/"selection.json"), analysis_sha256=digest(place["analysis_output"]/"ANALYSIS.json"),
        binding_plan_sha256=digest(rule_path), protocol_sha256=digest(place["protocol_path"]),
        selected_validation_step=best["step"], model_config=config, config_sha256=digest(config_path),
        random_weights=False, trained_weights=True, selection_uses_test=False,
        scope="Engineering runtime panels only; no claim that the owner threshold optimizes task utility")
    write_new(book.folder/"CHECKPOINT_BINDING.json", binding)
    return rule, weights, config_path, binding


def finalize(plan, place, identity, book):
    if not (place["prepare_output"]/"PREPARED.json").exists():
        return dict(passed=False, runtime_blocked=True, reason="Prepare did not complete; no trained runtime claim")
    prepared(place, identity)
    record = book.run("analysis", [sys.executable, "-m", MODULE+".analyze",
        "--protocol", place["protocol_path"], "--study", place["output"],
        "--output", place["analysis_output"], "--allow-partial"], required=False)
    if record["exit_code"] or not (place["analysis_output"]/"ANALYSIS.json").exists():
        return dict(passed=False, runtime_blocked=True, reason="Original analyzer failed; log retained")
    complete, analysis = complete_gate(place)
    if not complete:
        return dict(passed=False, runtime_blocked=True, reason="Cohort is not complete and valid 70/70",
            valid_jobs=analysis["valid_jobs"], expected_jobs=analysis["expected_jobs"], errors=analysis["errors"])
    rule, weights, config, binding = selected_binding(plan, place, book)
    temporary = Path(os.environ["RUNNER_TEMP"]).resolve()
    binary = temporary/"hcsn-native/continuous_host"
    book.run("restore_native", [sys.executable, "-m", "experiments.hcsn_free_boundary_v1.restore_native", binary])
    if digest(binary) != rule["native_binary_sha256"]:
        raise ValueError("Actual restored native binary differs from published binding")
    results = []
    for command, folder in (("stream", "trained_stream001"), ("native", "trained_native001"),
                            ("native-causal", "trained_native_causal001")):
        output = PACKAGE/"results"/folder
        argv = [sys.executable, "-m", MODULE+".runtime", command, "--output", output,
                "--backend", rule["backend"], "--profile", rule["profile"],
                "--config", config, "--checkpoint", weights]
        if command != "stream":
            argv += ["--binary", binary]
        record = book.run(folder, argv, required=False)
        result_path = output/"RESULT.json"
        value = read(result_path) if result_path.exists() else None
        passed = (record["exit_code"]==0 and value is not None and value["trained_weights"] is True
                  and value["original_checkpoint_sha256"]==binding["checkpoint_sha256"])
        results.append(dict(command=command, passed=bool(passed), exit_code=record["exit_code"],
            output=relative(output), result_sha256=digest(result_path) if result_path.exists() else None))
    unchanged(identity)
    if digest(weights) != binding["checkpoint_sha256"]:
        raise ValueError("Selected weights changed during runtime audit")
    return dict(passed=all(row["passed"] for row in results), runtime_blocked=False,
        complete_valid_jobs=70, primary_fidelity_passed=analysis["primary_fidelity_passed"],
        engineering_speed_gate_passed=analysis["engineering_speed_gate_passed"],
        checkpoint_binding=binding, runtime=results, native_binary_sha256=digest(binary),
        utility_optimality_claim=False, native_model_kernel_is_python=True, owner_authority="DENY_ALL")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "train", "finalize"))
    parser.add_argument("--plan", default="experiments/hcsn_conservative_acceleration_v1/HOSTED_EXECUTION_PLAN.json")
    args = parser.parse_args()
    plan_path = rooted(args.plan, package_only=True)
    plan = read(plan_path)
    place = paths(plan)
    folder = place["prepare_output"] if args.mode=="prepare" else place["finalize_output"] if args.mode=="finalize" else place["output"]
    book = RunBook(folder, args.mode)
    try:
        identity = public_identity(plan, plan_path, book)
        result = {"prepare": prepare, "train": train, "finalize": finalize}[args.mode](plan, place, identity, book)
        unchanged(identity)
    except BaseException:
        result = dict(passed=False, exception=traceback.format_exc(), runtime_blocked=True)
        book.finish(result)
        raise
    book.finish(result)
    print(json.dumps(dict(mode=args.mode, passed=result["passed"], output=relative(folder))), flush=True)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
