"""Small Linux CI reproduction: fresh public dependencies, native tests and audits.

Run from the repository root with Python 3.11+:
    python -m tools.hcsn.task_native_loop_20261031.ci --work /tmp/hcsn-ci-new

Install Rust 1.95.0, just 1.59.0, cargo-nextest 0.9.150, numpy 2.3.5 and
scipy 1.17.0 first. The work directory and Cargo cache must be new. This entry
does not train models or rerun the 1,200-episode confirmation experiment.
"""
import argparse
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import random
import shutil
import sys
import tempfile
import tomllib

from . import build


HERE = Path(__file__).resolve().parent
RUST_VERSION = "1.95.0"
TOOL_VERSIONS = {"just": "1.59.0", "cargo-nextest": "0.9.150"}
PYTHON_VERSIONS = {"numpy": "2.3.5", "scipy": "1.17.0"}


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def registry_packages(path):
    return {(p["name"], p["version"]): (p["source"], p["checksum"])
            for p in tomllib.loads(Path(path).read_text())["package"] if "source" in p}


def make_fixture(folder):
    """Generate public synthetic packets, without labels or held-out material."""
    folder.mkdir()
    rng = random.Random(71031)
    packets, hashes = [], []
    for job in range(2):
        packet_row, hash_row = [], []
        for tick in range(8):
            name = f"job{job}_tick{tick}.json"
            packet = dict(schema="hcsn.memory.packet.v1",
                          symbols=[job]+[rng.randrange(4) for _ in range(22)]+[-1], dt=[1.]*24)
            save(folder/name, packet)
            packet_row.append(name)
            hash_row.append(file_sha(folder/name))
        packets.append(packet_row)
        hashes.append(hash_row)
    public = dict(id="ci_synthetic_seed71031", deadline=8, budget=4,
                  reliability=[[.75]*8, [.75]*8], price=[[.015]*8, [.015]*8],
                  duration=[.4, .4, .4, .4, 1., 1.6, 1.6, 1.],
                  multiplier=1.5, latency_price=.015, packets=packets, packet_sha256=hashes)
    save(folder/"public.json", public)
    save(folder/"PROVENANCE.json", dict(synthetic=True, efficacy_evidence=False,
         heldout_material_used=False, generator_source_sha256=file_sha(__file__),
         public_sha256=file_sha(folder/"public.json"), seed=71031))
    return folder/"public.json"


def run(args):
    work = args.work.resolve() if args.work else Path(tempfile.mkdtemp(prefix="hcsn-ci-"))
    if args.work:
        work.mkdir(parents=True, exist_ok=False)
    if work.is_relative_to(build.REPO):
        raise ValueError("--work must be outside the repository to isolate Cargo configuration")
    report = dict(schema="hcsn.task-native-loop.ci.v1", success=False,
                  execution_context="github_actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local",
                  heldout_confirmation_rerun=False, cached_source_fallback=False,
                  work=str(work), stages=[], production_activation=False)

    def stage(name, command, cwd, env):
        result = build.execute(command, cwd, env)
        save(work/(name+".json"), result)
        report["stages"].append(dict(name=name, returncode=result["returncode"],
                                    wall_seconds=result["wall_seconds"],
                                    child_cpu_seconds=result["child_cpu_seconds"]))
        if result["returncode"]:
            raise RuntimeError(name+" failed:\n"+(result["stderr"] or result["stdout"])[-12000:])
        return result

    try:
        observed = {name: version(name) for name in PYTHON_VERSIONS}
        report["python_dependencies"] = observed
        if observed != PYTHON_VERSIONS:
            raise ValueError(("install the pinned Python dependencies", PYTHON_VERSIONS, observed))
        if args.toolchain:
            toolchain = args.toolchain.resolve()
        else:
            located = stage("locate_toolchain", ["rustup", "run", RUST_VERSION, "rustc", "--print", "sysroot"], work, os.environ.copy())
            toolchain = Path(located["stdout"].strip()).resolve()
        located_just = shutil.which("just")
        tools = args.tools.resolve() if args.tools else None
        if tools is None and located_just:
            tools = Path(located_just).parent
        if tools is None:
            raise ValueError("just is missing; install the pinned tools or pass --tools")
        env = os.environ.copy()
        env["PATH"] = os.pathsep.join((str(toolchain/"bin"), str(tools), env["PATH"]))
        rust = stage("rust_version", [str(toolchain/"bin/rustc"), "--version"], work, env)
        if not rust["stdout"].startswith("rustc "+RUST_VERSION+" "):
            raise ValueError("the reproduction requires Rust "+RUST_VERSION)
        for name, expected in TOOL_VERSIONS.items():
            result = stage(name+"_version", [name, "--version"], work, env)
            if result["stdout"].split()[:2] != [name, expected]:
                raise ValueError(("tool version differs", name, expected, result["stdout"]))
        cache = args.cargo_cache.resolve() if args.cargo_cache else work/"cargo-cache"
        if cache.exists() and any(cache.iterdir()):
            raise ValueError("--cargo-cache must be empty; existing local sources are not a CI fallback")
        for part in ("src", "cache", "index"):
            (cache/"registry"/part).mkdir(parents=True, exist_ok=True)
        options = argparse.Namespace(build=work/"build", toolchain=toolchain, tools=tools,
                                     cargo_cache=cache, cached_source_fallback=False,
                                     tests=True, report=work/"BUILD_REPORT.json")
        target, _, _, _, env, _, _ = build.prepare(options)
        initial = registry_packages(target/"Cargo.lock")
        report["lock_before_fetch_sha256"] = file_sha(target/"Cargo.lock")
        # The inherited lock's root entry predates this binary's dev dependency.
        # Allow that entry to resolve, then require every registry pin/checksum
        # to remain identical. No local source patch or offline first fetch.
        stage("public_cargo_fetch", ["cargo", "fetch", "--manifest-path", str(target/"Cargo.toml")], target, env)
        if registry_packages(target/"Cargo.lock") != initial:
            raise ValueError("online fetch changed a pinned registry version/checksum")
        report["lock_after_fetch_sha256"] = file_sha(target/"Cargo.lock")
        result = build.main(options)
        built = json.loads(options.report.read_text())
        if result or not built["success"] or not built["all_dependency_archives_verified"]:
            raise RuntimeError("fresh archive-verified build/native just test failed; see BUILD_REPORT.json")
        if registry_packages(target/"Cargo.lock") != initial:
            raise ValueError("offline build changed a pinned registry version/checksum")
        if not any(row["command"][:2] == ["just", "test"] for row in built["commands"]):
            raise AssertionError("the native just test stage was not executed")
        report["build"] = dict(source_digest=built["source_digest"], binary_sha256=built["binary_sha256"],
                               all_dependency_archives_verified=True, native_just_test_executed=True,
                               lock_after_build_sha256=file_sha(target/"Cargo.lock"))
        stage("python_oracle_tests", [sys.executable, "-m", "unittest", "tools.hcsn.task_native_loop_20261031.audit_tests"], build.REPO, env)
        public = make_fixture(work/"fixture")
        policy = HERE/"evidence/confirmation_training/models/seed71031_analytic_value.json"
        content = build.REPO/"tools/hcsn/round9_20261031/native/fixtures/fullhx.json"
        report["policy_sha256"], report["content_model_sha256"] = file_sha(policy), file_sha(content)
        stage("causal_audit", [sys.executable, "-m", "tools.hcsn.task_native_loop_20261031.audit",
              "--binary", built["binary"], "--content-model", str(content),
              "--public", str(public), "--policy", str(policy), "--output", str(work/"audit")], build.REPO, env)
        audited = json.loads((work/"audit/REPORT.json").read_text())
        if not audited["audit_integrity_passed"] or audited["native_invocations"] != 50:
            raise AssertionError("the expected 50-call independent audit did not pass")
        report.update(success=True, native_invocations=50,
                      scientific_efficacy_proved=False, continuous_diffusion_qualified=False,
                      audit_process_costs=audited["complete_audit_process_costs"])
    except Exception as error:
        report["error"] = dict(type=type(error).__name__, message=str(error))
    save(work/"CI_REPORT.json", report)
    print(json.dumps(report, indent=2))
    return 0 if report["success"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work", type=Path, help="new external scratch directory; otherwise create one under /tmp")
    parser.add_argument("--toolchain", type=Path, help="Rust sysroot; otherwise discover rustup's pinned toolchain")
    parser.add_argument("--tools", type=Path, help="directory containing just/cargo-nextest; otherwise use PATH")
    parser.add_argument("--cargo-cache", type=Path, help="new empty Cargo cache; defaults to WORK/cargo-cache")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
