#!/usr/bin/env python3
"""Exercise complete network-host normalization through actual production owners.

The original function is pinned without rewriting its algorithm. Public callers,
separate allocation/timing processes and deliberately substituted callee failures
are distinct evidence. This builds binaries; it does not replace just test.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import tomllib

from network_host_predecessor16 import load_predecessor16
from network_host_predecessor16 import predecessor_output_guard
from network_host_predecessor16 import verify_predecessor16_inputs
from test_native_command_dispatch import original_sources as dispatch_original_sources
from test_native_execpolicy_caller import TOKEN
from test_network_host_abi import native_inputs as bind_native_inputs
from test_network_host_abi import recheck_inputs as recheck_native_inputs


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "codex-rs/execpolicy/src"
ORIGINAL_REVISION = "f75abe3e54ac6a37bf348b9237f0b64c4c40e1fc"
DEPENDENCIES = ("serde", "serde_json", "anyhow", "multimap", "codex_utils_absolute_path")
UNMODIFIED_CALLERS = {
    "parser.rs": "58b89a789c394cffa2412189b5acadf2110ab23229c91db5878b72d5aeb9fee8",
    "amend.rs": "e0869236f00e7e96e13c8546c17120b8e7e4438c6e6d676831446707eda2d1eb",
    "error.rs": "7c952283b5c2a75d3a34669427dab79ef0a6ff26d401b8731bba9751822d81dc",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tokens(source):
    return [token for token in TOKEN.findall(source) if not token.startswith(("//", "/*"))]


def pin(source, count, expected):
    values = tokens(source)
    actual = hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()
    if (len(values), actual) != (count, expected):
        raise RuntimeError("complete original network-host source differs from f75")
    return {"token_count": count, "token_sha256": actual}


def original_sources():
    records = dispatch_original_sources()
    source = (SOURCE / "rule.rs").read_text()
    function = r"pub\(crate\) fn normalize_network_rule_host\([\s\S]*?^}\n"
    methods = re.findall(r"(?m)^" + function, source)
    expected = "pub(crate) fn normalize_network_rule_host(raw: &str) -> Result<String> { crate::hia_native_network_host::normalize(raw) }"
    if len(methods) != 2 or tokens(methods[0]) != tokens(expected):
        raise RuntimeError("complete original function and exact native delegation are required")
    records["network_host"] = pin(methods[1], 393, "a2bb25bf0604d951d60f92fef5c827467dc233ad4440de3571e6f9a8eb1ae5a5")
    records["network_host"]["overlap"] = "subregion of the 583-token network types/normalization pin; not additive"
    source, removed = re.subn(r'(?m)^#\[cfg\(feature = "hia-native"\)\]\n' + function, "", source)
    source, attributes = re.subn(
        r'(?m)^#\[cfg\(not\(feature = "hia-native"\)\)\]\n(?=pub\(crate\) fn normalize_network_rule_host\()', "", source)
    if (removed, attributes) != (1, 1):
        raise RuntimeError("native/default normalization feature guards differ")
    start = source.index("#[derive(Clone, Copy, Debug, Eq, PartialEq)]\npub enum NetworkRuleProtocol")
    section = source[start:source.index("pub trait Rule:", start)]
    records["network_types_and_normalization"] = pin(section, 583, "775fddae2313f22890a6d395c67d98b96e273be7b514724ae4fcb0fadde07d70")
    for name, expected_hash in UNMODIFIED_CALLERS.items():
        if sha(SOURCE / name) != expected_hash:
            raise RuntimeError(f"unchanged caller/error source changed: {name}")
    records["unchanged_callers_and_errors"] = UNMODIFIED_CALLERS
    return records, methods[1]


def source_hashes():
    paths = list((ROOT / "codex-rs/execpolicy").rglob("*.rs"))
    paths += [ROOT / path for path in (
        "codex-rs/execpolicy/Cargo.toml", "codex-rs/Cargo.toml", "codex-rs/Cargo.lock",
        "codex-rs/rust-toolchain.toml", "codex-rs/rustfmt.toml", "hia/toolchain.json",
        "hia/cargo_build.rs", "hia/build.py", "hia/tests/test_native_execpolicy_caller.py",
        "hia/tests/test_native_policy_summary.py", "hia/tests/test_native_command_dispatch.py")]
    paths += list((ROOT / "hia").glob("*.hepta"))
    paths += list((ROOT / "hia/tests").glob("*network_host*"))
    paths += list((ROOT / "codex-rs/utils/absolute-path").rglob("*.rs"))
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(set(paths))}


def capture_builds(cargo, rustc, target, library, artifacts, environment, report, run):
    wrapper = artifacts / "capture_rustc.py"
    wrapper.write_text(
        "#!/usr/bin/python3\nimport json, os, sys\nfrom pathlib import Path\n"
        "args = sys.argv[2:]\n"
        "if '--crate-name' in args and args[args.index('--crate-name') + 1] == 'codex_execpolicy':\n"
        "    kind = args[args.index('--crate-type') + 1] if '--crate-type' in args else 'bin'\n"
        "    suffix = 'lib' if kind in ('lib', 'rlib') else 'bin'\n"
        "    externs = dict(args[index + 1].split('=', 1) for index, arg in enumerate(args) if arg == '--extern')\n"
        "    path = Path(os.environ['CODEX_HIA_COMPILER_CAPTURE'] + '.' + suffix + '.json')\n"
        "    with path.open('x') as output:\n"
        "        json.dump({'compiler': sys.argv[1], 'argv': args, 'externs': externs}, output, indent=2)\n"
        "os.execv(sys.argv[1], sys.argv[1:])\n")
    wrapper.chmod(0o755)
    environment["RUSTC_WORKSPACE_WRAPPER"] = str(wrapper)
    report["compiler_wrapper"] = {"path": str(wrapper), "sha256": sha(wrapper),
        "purpose": "capture exact compiler argv, then exec rustc without altering arguments"}
    builds = {}
    report["builds"] = builds
    for mode in ("reference", "native"):
        current = environment.copy()
        capture = artifacts / f"compiler-{mode}"
        current["CODEX_HIA_COMPILER_CAPTURE"] = str(capture)
        command = [cargo, "build", "--locked", "-p", "codex-execpolicy", "--bin", "codex-execpolicy",
                   "--target-dir", str(target), "--message-format=json"]
        if mode == "native":
            current["CODEX_HIA_NATIVE_LIB_DIR"] = str(library)
            command += ["--features", "hia-native"]
        else:
            current.pop("CODEX_HIA_NATIVE_LIB_DIR", None)
        output = run(f"build-{mode}", command, current, timeout=1800)
        units, selected, binary = [], {}, None
        for line in output.splitlines():
            row = json.loads(line)
            if row.get("reason") != "compiler-artifact":
                continue
            units.append(row)
            name = row["target"]["name"]
            rlibs = [Path(path) for path in row["filenames"] if path.endswith(".rlib")]
            if name == "codex_execpolicy" and rlibs:
                if name in selected and selected[name] != rlibs[0]:
                    raise RuntimeError("ambiguous actual owner artifact")
                selected[name] = rlibs[0]
            if name == "codex-execpolicy" and row.get("executable"):
                binary = Path(row["executable"])
        if "codex_execpolicy" not in selected or binary is None:
            raise RuntimeError("Cargo did not report the actual owner artifacts")
        captures = {kind: Path(str(capture) + f".{kind}.json") for kind in ("lib", "bin")}
        lib_call, bin_call = [json.loads(captures[kind].read_text()) for kind in ("lib", "bin")]
        if lib_call["compiler"] != rustc or bin_call["compiler"] != rustc:
            raise RuntimeError("captured compiler is not the requested rustc")
        if Path(bin_call["externs"]["codex_execpolicy"]) != selected["codex_execpolicy"]:
            raise RuntimeError("binary compiler did not consume the captured owner library")
        if ('feature="hia-native"' in lib_call["argv"]) != (mode == "native"):
            raise RuntimeError("captured library feature differs from the intended oracle mode")
        runtime_units = {}
        for name in DEPENDENCIES:
            metadata, linked = lib_call["externs"][name], bin_call["externs"][name]
            matches = [unit for unit in units if unit["target"]["name"] == name
                       and metadata in unit["filenames"] and linked in unit["filenames"]]
            if len(matches) != 1 or not linked.endswith(".rlib"):
                raise RuntimeError(f"library/binary dependency is not one Cargo unit: {name}")
            selected[name] = Path(linked)
            runtime_units[name] = {key: matches[0][key] for key in ("package_id", "features", "profile", "filenames")}
            runtime_units[name]["metadata_sha256"] = sha(metadata)
        saved_rlib, saved_binary = artifacts / f"lib{mode}_execpolicy.rlib", artifacts / f"{mode}-codex-execpolicy"
        shutil.copy2(selected["codex_execpolicy"], saved_rlib)
        shutil.copy2(binary, saved_binary)
        builds[mode] = {"rlib": str(saved_rlib), "rlib_sha256": sha(saved_rlib),
            "binary": str(saved_binary), "binary_sha256": sha(saved_binary), "runtime_units": runtime_units,
            "compiler_captures": {kind: {"path": str(path), "sha256": sha(path)} for kind, path in captures.items()},
            "dependencies": {name: {"path": str(path), "sha256": sha(path)} for name, path in selected.items()}}
        if source_hashes() != report["source_sha256"]:
            raise RuntimeError("source bytes changed during an actual owner build")
    return builds


def rust_arguments(rustc, edition, library, owners):
    command = [rustc, f"--edition={edition}", "-C", "opt-level=3"]
    selected, directories = {}, {("native", str(library))}
    for alias, build in owners.items():
        if sha(build["rlib"]) != build["rlib_sha256"]:
            raise RuntimeError(f"{alias}: owner library changed")
        command += ["--extern", f"{alias}={build['rlib']}"]
        frozen_search = build.get("link_search_paths")
        if frozen_search is not None:
            if len(frozen_search) != 4 or {row["kind"] for row in frozen_search} != {"dependency", "native"}:
                raise RuntimeError("frozen owner16 requires the complete four-directory link plan")
            directories.update((row["kind"], row["path"]) for row in frozen_search)
            if ("native", str(library)) not in {(row["kind"], row["path"]) for row in frozen_search}:
                raise RuntimeError("frozen owner16 native directory differs from its admitted plan")
        for name, row in build["dependencies"].items():
            path = Path(row["path"]).resolve(strict=True)
            if sha(path) != row["sha256"]:
                raise RuntimeError(f"{alias}: dependency changed: {name}")
            if frozen_search is None:
                directories.add(("dependency", str(path.parent)))
            elif ("dependency", str(path.parent)) not in directories:
                raise RuntimeError("frozen owner16 dependency escapes its admitted link directories")
            if name in DEPENDENCIES:
                if name in selected and selected[name] != row:
                    raise RuntimeError(f"simultaneous public owners use different dependencies: {name}")
                selected[name] = row
    for kind, directory in sorted(directories):
        command += ["-L", f"{kind}={directory}"]
    for name, row in selected.items():
        command += ["--extern", f"{name}={row['path']}"]
    return command


def completion(output, marker, label):
    lines = [line[len(marker):] for line in output.splitlines() if line.startswith(marker)]
    if len(lines) != 1:
        raise RuntimeError(f"{label}: missing unique completion record")
    result = json.loads(lines[0])
    if result.get("passed") is not True:
        raise RuntimeError(f"{label}: process did not complete successfully")
    return result


def run_baselines(report, builds, predecessor, library, artifacts, rustc, edition, environment, run):
    native_label = report["requested_build_profile"].removeprefix("full-")
    modes = [("original", builds["reference"], library), (native_label, builds["native"], library)]
    if predecessor is not None:
        modes.insert(1, ("native16", predecessor[0], predecessor[1]))
    for kind in ("allocations", "performance"):
        report[kind] = {}
        for label, build, native_library in modes:
            command = rust_arguments(rustc, edition, native_library, {"owner": build})
            source = ROOT / f"hia/tests/native_network_host_{kind}.rs"
            executable = artifacts / f"{kind}-{label}"
            prior_process = None
            if label == "native16":
                prior_process = {"compiled_now": False, "executed_now": False, "completion_validated": False,
                    "harness_sha256": sha(source), "owner_rlib_sha256": sha(build["rlib"]),
                    "source": str(source), "executable": str(executable), "prior_binary_reused": False}
                report["predecessor"]["new_harness_processes"][kind] = prior_process
            run(f"compile-{kind}-{label}", [*command, str(source), "-o", str(executable)], environment)
            if prior_process is not None:
                prior_process.update(compiled_now=True, binary_sha256=sha(executable))
                report["predecessor"]["compiled_now"] = all(
                    report["predecessor"]["new_harness_processes"].get(name, {}).get("compiled_now", False)
                    for name in ("allocations", "performance"))
            symbols = run(f"symbols-{kind}-{label}", ["nm", "--defined-only", "--extern-only", str(executable)], environment)
            present = bool(re.search(r"\bT codex_hia_network_host$", symbols, re.MULTILINE))
            if present != (label == native_label):
                raise RuntimeError(f"{kind}/{label}: unexpected network-host linkage")
            output = run(f"run-{kind}-{label}", [str(executable), label], environment, timeout=300)
            if prior_process is not None:
                prior_process["executed_now"] = True
                report["predecessor"]["executed_now"] = all(
                    report["predecessor"]["new_harness_processes"].get(name, {}).get("executed_now", False)
                    for name in ("allocations", "performance"))
            result = completion(output, f"network_host_{kind}=", f"{kind}/{label}")
            if result.get("label") != label:
                raise RuntimeError("baseline process returned the wrong owner label")
            if prior_process is not None:
                prior_process["completion_validated"] = True
            report[kind][label] = {**result, "binary_sha256": sha(executable),
                "owner_rlib_sha256": sha(build["rlib"]), "harness_sha256": sha(source),
                "compiled_now": True, "executed_now": True, "prior_binary_reused": False}
        reference = report[kind]["original"]["rows"]
        keys = ("case", "raw_bytes", "result", "rules") + (("iterations",) if kind == "performance" else ())
        expected = [[row[key] for key in keys] for row in reference]
        for label, result in report[kind].items():
            if [[row[key] for key in keys] for row in result["rows"]] != expected:
                raise RuntimeError(f"{kind}/{label}: complete workload/result observations differ")
    report["three_baselines_executed"] = all(set(report[kind]) == {"original", "native16", native_label}
        for kind in ("allocations", "performance"))
    report["performance_qualification"] = False


def verify(args, report):
    rustc, cargo = shutil.which(args.rustc), shutil.which(args.cargo)
    if rustc is None or cargo is None:
        raise RuntimeError("real rustc and cargo are required; this gate never skips")
    library, target = args.library_dir.resolve(strict=True), args.target_dir.resolve()
    if target == ROOT or ROOT in target.parents:
        raise RuntimeError("Cargo output must be outside the source checkout")
    artifacts = args.report.with_name(args.report.stem + "-artifacts")
    artifacts.mkdir()
    owners, original_function = original_sources()
    report["oracle"] = {"revision": ORIGINAL_REVISION, "owners": owners}
    report["source_sha256"] = source_hashes()
    native_admission = report["native_build_admission"] = {}
    bind_native_inputs(library / "network_host.so", ROOT / "hia/network_host.hepta",
                       args.build_profile, native_admission)
    native = json.loads((library / "build.json").read_text())
    if "network_host" not in native["modules"]:
        raise RuntimeError("complete native build does not contain the network-host module")
    report["native_inputs"] = {"build.json": sha(library / "build.json")}
    for name, module in native["modules"].items():
        if sha(ROOT / f"hia/{name}.hepta") != module["source_sha256"]:
            raise RuntimeError(f"native build/source identity mismatch: {name}")
        link = module["codex_link_abi"]
        actual = sha(library / link["archive"])
        if actual != link["archive_sha256"]:
            raise RuntimeError(f"native archive identity mismatch: {name}")
        report["native_inputs"][link["archive"]] = actual
    environment = os.environ.copy()
    environment.pop("RUSTC_WRAPPER", None)
    environment.update(RUSTC=rustc, GIT_TERMINAL_PROMPT="0", PYTHONDONTWRITEBYTECODE="1")

    def run(label, command, child_environment, timeout=180):
        started, timed_out = time.monotonic(), False
        try:
            result = subprocess.run(command, cwd=ROOT / "codex-rs", env=child_environment,
                                    capture_output=True, timeout=timeout)
            streams = {name: getattr(result, name) for name in ("stdout", "stderr")}
            returncode = result.returncode
        except subprocess.TimeoutExpired as error:
            timed_out, returncode = True, None
            streams = {name: getattr(error, name) or b"" for name in ("stdout", "stderr")}
        logs = {}
        for stream, data in streams.items():
            path = artifacts / f"{label}.{stream}"
            path.write_bytes(data)
            logs[stream] = {"path": str(path), "sha256": sha(path), "bytes": len(data)}
        report["commands"].append({"label": label, "command": command, "returncode": returncode,
            "timed_out": timed_out, "elapsed_seconds": time.monotonic() - started, **logs})
        if timed_out or returncode:
            raise RuntimeError(f"{label} exited {returncode}, timed_out={timed_out}: " + streams["stderr"][-6000:].decode(errors="replace"))
        return streams["stdout"].decode()

    report["rustc"] = run("rustc-version", [rustc, "--version", "--verbose"], environment)
    predecessor = load_predecessor16(args, report, target, rustc, report["rustc"])
    if predecessor is not None and report["predecessor"]["rustc"] != report["rustc"]:
        raise RuntimeError("predecessor and current owners use different compiler identities")
    edition = tomllib.loads((ROOT / "codex-rs/Cargo.toml").read_text())["workspace"]["package"]["edition"]
    report["edition"] = edition
    builds = capture_builds(cargo, rustc, target, library, artifacts, environment, report, run)
    arguments = rust_arguments(rustc, edition, library, {"original": builds["reference"], "candidate": builds["native"]})
    wrapper = artifacts / "public_owner.rs"
    adapter = SOURCE / "hia_native_network_host.rs"
    public_source = ROOT / "hia/tests/native_network_host.rs"
    wrapper.write_text("mod error { pub use original::{Error, Result}; }\n"
        + f"#[path={json.dumps(str(adapter))}] mod hia_native_network_host;\n"
        + "mod original_owner { use original::{Error, Result};\n" + original_function + "}\n"
        + f"include!({json.dumps(str(public_source))});\n")
    report["public_wrapper"] = {"path": str(wrapper), "sha256": sha(wrapper),
        "oracle_function_sha256": hashlib.sha256(original_function.encode()).hexdigest()}
    for label, source in (("public", wrapper), ("failures", ROOT / "hia/tests/native_network_host_failures.rs")):
        executable = artifacts / label
        run(f"compile-{label}", [*arguments, str(source), "-o", str(executable)], environment)
        if label == "public":
            symbols = run("symbols-public", ["nm", "--defined-only", "--extern-only", str(executable)], environment)
            if not re.search(r"\bT codex_hia_network_host$", symbols, re.MULTILINE):
                raise RuntimeError("actual public executable has no native network-host symbol")
        directory = artifacts / f"{label}-owned-files"
        directory.mkdir()
        output = run(f"run-{label}", [str(executable), str(directory)], environment, timeout=300)
        result = completion(output, f"network_host_{label}=", label)
        report[label] = {**result, "binary_sha256": sha(executable), "harness_sha256": sha(source)}
    run_baselines(report, builds, predecessor, library, artifacts, rustc, edition, environment, run)
    if args.require_predecessor and not report["three_baselines_executed"]:
        raise RuntimeError("required three-baseline allocation and timing processes did not complete")
    if source_hashes() != report["source_sha256"]:
        raise RuntimeError("source bytes changed during public verification")
    if {name: sha(library / name) for name in report["native_inputs"]} != report["native_inputs"]:
        raise RuntimeError("native artifacts changed during public verification")
    if not recheck_native_inputs(native_admission):
        raise RuntimeError(f"complete {args.build_profile} admitted artifacts changed during public verification")
    verify_predecessor16_inputs(report)
    report.update(passed=True, full_policy_migration=False, performance_qualification=False,
        passed_scope="complete normalization public/effect/error gates and listed allocation/timing observations",
        profile="real dev crate owners; opt-level=3 external harnesses; one diagnostic timing observation per case")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--build-profile", choices=["full-native29", "full-native30", "full-native31", "full-native32", "full-native33", "full-native34", "full-native35", "full-native36"],
                        default="full-native29")
    parser.add_argument("--target-dir", type=Path, default=os.environ.get("CARGO_TARGET_DIR"))
    parser.add_argument("--rustc", default=os.environ.get("RUSTC", "rustc"))
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--predecessor-manifest", type=Path, help="Published owner16 promotion descriptor for the exact immutable link bundle")
    parser.add_argument("--predecessor-manifest-sha256", help="SHA256 of the separately reviewed owner16 promotion descriptor")
    parser.add_argument("--require-predecessor", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.report = args.report.resolve()
    if args.target_dir is None:
        parser.error("--target-dir or CARGO_TARGET_DIR is required")
    if args.report.exists() or args.report == ROOT or ROOT in args.report.parents:
        parser.error("select a new report outside the checkout; retain previous evidence")
    report = {"schema": "codex.hia.native-network-host.v1", "passed": False, "commands": [],
        "requested_build_profile": args.build_profile,
        "three_baselines_required": args.require_predecessor, "three_baselines_executed": False,
        "performance_qualification": False, "full_policy_migration": False}
    try:
        predecessor_output_guard(args, args.target_dir, args.report.with_name(args.report.stem + "-artifacts"))
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    try:
        verify(args, report)
    except (OSError, RuntimeError, ValueError, KeyError, IndexError, TypeError, AssertionError,
            subprocess.TimeoutExpired) as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], file=sys.stderr)
    with args.report.open("x") as output:
        output.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"passed": report["passed"], "report": str(args.report), "sha256": sha(args.report)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
