"""Small Linux reproduction with fresh public Cargo archives and native audits.

From the repository root:
    python -m tools.hcsn.calibrated_operator_r11_20261031.ci --work /tmp/hcsn-r11-ci-new

Requires Rust 1.95.0, just 1.59.0, cargo-nextest 0.9.150, numpy 2.3.5,
scipy 1.17.0 and mpmath 1.3.0. The work directory and Cargo cache must be new.
This entry does not train models or rerun the heldout confirmation experiment.
"""
import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import tomllib

from . import build


HERE = Path(__file__).resolve().parent
RUST_VERSION = "1.95.0"
TOOL_VERSIONS = {"just": "1.59.0", "cargo-nextest": "0.9.150"}
PYTHON_VERSIONS = {"numpy": "2.3.5", "scipy": "1.17.0", "mpmath": "1.3.0"}
FREEZE_SHA256 = "179037fca15a4f1ff5f08a50fd7c306b6ef5fdca82c6e951caa4091e293cbb20"
DEVELOPMENT_SHA256 = "67d7770236de8879d1b0bd1985a8f015b90591acfb3a947571f7ff99fbbb3f4a"
FIXTURE_ID = "train_seed81031_0000"


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def registry_packages(path):
    packages = {(p["name"], p["version"]): (p["source"], p["checksum"])
                for p in tomllib.loads(Path(path).read_text())["package"] if "source" in p}
    if any(source != "registry+https://github.com/rust-lang/crates.io-index"
           for source, _ in packages.values()):
        raise ValueError("CI requires public crates.io registry dependencies")
    return packages


def make_fixture(folder):
    """Copy only the pinned development session; never use heldout material."""
    archive_path = HERE / "evidence/training_01/data/development_seed81031.tar.gz"
    freeze_path = HERE / "evidence/training_02/FREEZE.json"
    policy_path = HERE / "evidence/training_02/models/seed81031_analytic_value.json"
    if file_sha(archive_path) != DEVELOPMENT_SHA256 or file_sha(freeze_path) != FREEZE_SHA256:
        raise ValueError("pinned development archive or training freeze changed")
    freeze = json.loads(freeze_path.read_text())
    policy_sha = freeze["models"]["models/seed81031_analytic_value.json"]["sha256"]
    if file_sha(policy_path) != policy_sha:
        raise ValueError("CI policy differs from the frozen training artifact")
    policy = json.loads(policy_path.read_text())
    folder.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive_path, "r:gz") as archive:
        def member_bytes(name):
            if Path(name).name != name:
                raise ValueError("fixture members must have a single path component")
            member = archive.getmember(FIXTURE_ID + "/" + name)
            if not member.isfile() or member.size > 128000:
                raise ValueError("fixture member must be a bounded regular file")
            return archive.extractfile(member).read()
        public_bytes = member_bytes("public.json")
        public = json.loads(public_bytes)
        if public["id"] != FIXTURE_ID:
            raise ValueError("unexpected development fixture identity")
        names = ["public.json", "evaluator_labels.json"] + [name for row in public["packets"] for name in row]
        for name in names:
            with (folder / name).open("xb") as stream:
                stream.write(public_bytes if name == "public.json" else member_bytes(name))
    public["multiplier"] = policy["multiplier"]
    public["latency_price"] = policy["latency_price"]
    public["packet_sha256"] = [[file_sha(folder / name) for name in row] for row in public["packets"]]
    save(folder / "native_public.json", public)
    provenance = dict(development_fixture=True, fixture_id=FIXTURE_ID, heldout_material_used=False,
        efficacy_evidence=False, archive_sha256=DEVELOPMENT_SHA256,
        training_freeze_sha256=FREEZE_SHA256, policy_sha256=policy_sha,
        original_file_sha256={name: file_sha(folder / name) for name in names},
        native_public_sha256=file_sha(folder / "native_public.json"))
    save(folder / "PROVENANCE.json", provenance)
    return dict(public=folder / "native_public.json", policy=policy_path, freeze=freeze_path,
                archive=archive_path, provenance=provenance)


def audit_command(binary, build_report, fixture, output):
    return [sys.executable, "-m", "tools.hcsn.calibrated_operator_r11_20261031.audit.causal",
        "--binary", str(binary), "--build-report", str(build_report),
        "--freeze", str(fixture["freeze"]), "--freeze-sha256", FREEZE_SHA256,
        "--policy", str(fixture["policy"]),
        "--content", str(build.REPO / "tools/hcsn/round9_20261031/native/fixtures/fullhx.json"),
        "--public", str(fixture["public"]), "--fixture-archive", str(fixture["archive"]),
        "--output", str(output)]


def run(args):
    work = args.work.resolve() if args.work else Path(tempfile.mkdtemp(prefix="hcsn-r11-ci-"))
    if work.is_relative_to(build.REPO):
        raise ValueError("--work must be outside the repository to isolate Cargo configuration")
    if args.work:
        work.mkdir(parents=True, exist_ok=False)
    report = dict(schema="hcsn.calibrated-operator.ci.r11.v1", success=False,
        execution_context="github_actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local",
        work=str(work), stages=[], cached_source_fallback=False,
        fresh_public_dependency_build_attempted=False, heldout_confirmation_rerun=False,
        scientific_efficacy_proved=False, production_activation=False,
        ci_source_sha256=file_sha(__file__))

    def stage(name, command, cwd, env):
        result = build.execute(command, cwd, env)
        save(work / (name + ".json"), result)
        report["stages"].append(dict(name=name, returncode=result["returncode"],
            wall_seconds=result["wall_seconds"], child_cpu_seconds=result["child_cpu_seconds"]))
        if result["returncode"]:
            raise RuntimeError(name + " failed:\n" + (result["stderr"] or result["stdout"])[-12000:])
        return result

    try:
        observed = {name: version(name) for name in PYTHON_VERSIONS}
        report["python_dependencies"] = observed
        if observed != PYTHON_VERSIONS:
            raise ValueError(("install pinned Python dependencies", PYTHON_VERSIONS, observed))
        env = os.environ.copy()
        env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
        overrides = [name for name in env if name.startswith(("CARGO_SOURCE_", "CARGO_REGISTRIES_"))]
        if overrides:
            raise ValueError(("public-registry CI disallows Cargo registry/source overrides", overrides))
        if args.toolchain:
            toolchain = args.toolchain.resolve()
        else:
            located = stage("locate_toolchain", ["rustup", "run", RUST_VERSION, "rustc", "--print", "sysroot"], work, env)
            toolchain = Path(located["stdout"].strip()).resolve()
        located_just = shutil.which("just")
        tools = args.tools.resolve() if args.tools else Path(located_just).parent if located_just else None
        if tools is None:
            raise ValueError("install the pinned just/cargo-nextest tools or supply --tools")
        env["PATH"] = os.pathsep.join((str(toolchain / "bin"), str(tools), env["PATH"]))
        rust = stage("rust_version", [str(toolchain / "bin/rustc"), "--version"], work, env)
        if not rust["stdout"].startswith("rustc " + RUST_VERSION + " "):
            raise ValueError("CI requires Rust " + RUST_VERSION)
        for name, expected in TOOL_VERSIONS.items():
            observed_tool = stage(name + "_version", [name, "--version"], work, env)
            if observed_tool["stdout"].split()[:2] != [name, expected]:
                raise ValueError(("tool version differs", name, expected, observed_tool["stdout"]))
        cache = args.cargo_cache.resolve() if args.cargo_cache else work / "cargo-cache"
        if cache.exists() and any(cache.iterdir()):
            raise ValueError("Cargo cache must be empty; existing sources are not a CI fallback")
        for part in ("src", "cache", "index"):
            (cache / "registry" / part).mkdir(parents=True, exist_ok=True)
        options = argparse.Namespace(build=work / "build", toolchain=toolchain, tools=tools,
            cargo_cache=cache, cached_source_fallback=False, tests=True, report=work / "BUILD_REPORT.json")
        target, _, _, _, env, _, manifest = build.prepare(options)
        env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
        if "[patch.crates-io]" in manifest:
            raise AssertionError("fresh CI cannot use local Cargo dependency patches")
        original_pins = registry_packages(target / "Cargo.lock")
        report["lock_before_fetch_sha256"] = file_sha(target / "Cargo.lock")
        report["fresh_public_dependency_build_attempted"] = True
        # Root package metadata may resolve; every registry version and checksum
        # must remain pinned, and the second prepare requires real .crate bytes.
        stage("public_cargo_fetch", ["cargo", "fetch", "--manifest-path", str(target / "Cargo.toml")], target, env)
        if registry_packages(target / "Cargo.lock") != original_pins:
            raise ValueError("public fetch changed a pinned registry version/checksum")
        report["lock_after_fetch_sha256"] = file_sha(target / "Cargo.lock")
        build_status = build.main(options)
        built = json.loads(options.report.read_text())
        if build_status or not built["success"] or not built["all_dependency_archives_verified"]:
            raise RuntimeError("fresh archive-verified native build/just test failed; see BUILD_REPORT.json")
        if registry_packages(target / "Cargo.lock") != original_pins:
            raise ValueError("offline build changed a pinned registry version/checksum")
        tests = [row for row in built["commands"] if row["command"][:2] == ["just", "test"]]
        if len(tests) != 1 or tests[0]["returncode"]:
            raise AssertionError("native grid tests did not pass through just test")
        report["build"] = dict(source_digest=built["source_digest"], binary_sha256=built["binary_sha256"],
            build_report_sha256=file_sha(options.report), all_dependency_archives_verified=True,
            native_just_test_executed=True, native_test_log=(tests[0]["stdout"] + tests[0]["stderr"])[-8000:],
            dependency_archives={name: item["archive_sha256"] for name, item in built["dependency_sources"].items()},
            lock_after_build_sha256=file_sha(target / "Cargo.lock"))
        stage("python_value_tests", [sys.executable, "-m", "unittest", "tools.hcsn.calibrated_operator_r11_20261031.value_tests"], build.REPO, env)
        # These independent high-precision tests intentionally import kernel and
        # reference as local modules, so their working directory is significant.
        stage("python_numerics_tests", [sys.executable, "-m", "unittest", "test_kernel"], HERE / "numerics", env)
        fixture = make_fixture(work / "fixture")
        report["fixture"] = fixture["provenance"]
        stage("native_causal_audit", audit_command(built["binary"], options.report, fixture, work / "audit"), build.REPO, env)
        audited = json.loads((work / "audit/SUMMARY.json").read_text())
        required = ("recovery", "labels", "future_packet", "never_read_packet", "identity")
        if not audited["success"] or not all(audited["findings"][key]["passed"] for key in required):
            raise AssertionError("native causal/recovery/identity audit did not pass")
        if not audited["inputs"]["all_dependency_archives_verified"]:
            raise AssertionError("native audit did not bind the fresh archive-verified build")
        report.update(success=True, audit_summary_sha256=file_sha(work / "audit/SUMMARY.json"),
            native_audit_processes=audited["native_processes"],
            audit_native_child_cpu_seconds=audited["native_child_cpu_seconds"],
            audit_native_child_wall_seconds=audited["native_child_wall_seconds"])
    except Exception as error:
        report["error"] = dict(type=type(error).__name__, message=str(error))
    save(work / "CI_REPORT.json", report)
    print(json.dumps(report, indent=2))
    return 0 if report["success"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work", type=Path, help="new external scratch directory; defaults to a new /tmp directory")
    parser.add_argument("--toolchain", type=Path, help="Rust sysroot; otherwise locate rustup's pinned toolchain")
    parser.add_argument("--tools", type=Path, help="directory containing pinned just and cargo-nextest")
    parser.add_argument("--cargo-cache", type=Path, help="new empty Cargo cache; defaults to WORK/cargo-cache")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
