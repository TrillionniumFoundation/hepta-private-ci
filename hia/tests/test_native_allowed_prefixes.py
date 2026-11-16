#!/usr/bin/env python3
"""Compare complete ordered allowed prefixes with the actual original crate.

Build both real owner variants and execute public, allocation and callee-error
probes. Raw ABI checks and production consumer gates are separate.
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

from test_native_execpolicy_caller import TOKEN
from test_native_policy_summary import original_sources as summary_original_sources


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "codex-rs/execpolicy/src"
ORIGINAL_REVISION = "f75abe3e54ac6a37bf348b9237f0b64c4c40e1fc"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def original_sources():
    records = summary_original_sources()
    policy = (SOURCE / "policy.rs").read_text()
    methods = re.findall(r"(?m)^    pub fn get_allowed_prefixes\([\s\S]*?^    }\n", policy)
    helpers = re.findall(r"(?m)^fn render_pattern_token\([\s\S]*?^}\n", policy)
    if len(methods) != 2 or len(helpers) != 1 or "hia_native_allowed_prefixes" not in methods[0]:
        raise RuntimeError("complete original allowed-prefix owner and native delegation are required")
    tokens = [token for token in TOKEN.findall(methods[1] + "\n" + helpers[0])
              if not token.startswith(("//", "/*"))]
    digest = hashlib.sha256(json.dumps(tokens, separators=(",", ":")).encode()).hexdigest()
    if (len(tokens), digest) != (215, "e4c4fc1720c4c14eac86dbb4d73354cbb9549357ea6aab2fe21eb7804a13261f"):
        raise RuntimeError("complete original allowed-prefix source differs from pinned Rust oracle")
    records["allowed_prefixes"] = {"token_count": len(tokens), "token_sha256": digest}
    return records


def source_hashes():
    paths = list((ROOT / "codex-rs/execpolicy").rglob("*.rs"))
    paths += [ROOT / "codex-rs/execpolicy/Cargo.toml", ROOT / "codex-rs/Cargo.toml",
              ROOT / "codex-rs/rust-toolchain.toml", ROOT / "codex-rs/Cargo.lock",
              ROOT / "hia/toolchain.json", ROOT / "hia/cargo_build.rs", ROOT / "hia/build.py",
              ROOT / "hia/tests/test_native_execpolicy_caller.py",
              ROOT / "hia/tests/test_native_policy_summary.py"]
    paths += list((ROOT / "hia").glob("*.hepta"))
    paths += list((ROOT / "hia/tests").glob("*allowed_prefixes*"))
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(set(paths))}


def verify(args, report):
    rustc, cargo = shutil.which(args.rustc), shutil.which(args.cargo)
    if rustc is None or cargo is None:
        raise RuntimeError("real rustc and cargo are required; this gate never skips")
    library = args.library_dir.resolve(strict=True)
    target = args.target_dir.resolve()
    if target == ROOT or ROOT in target.parents:
        raise RuntimeError("Cargo output must be outside the source checkout")
    artifacts = args.report.with_name(args.report.stem + "-artifacts")
    artifacts.mkdir()
    report["oracle"] = {"revision": ORIGINAL_REVISION, "owners": original_sources()}
    captured = source_hashes()
    report["source_sha256"] = captured
    report["native_inputs"] = {name: sha(library / name) for name in [
        "build.json", "libcodex_hia_policy_summary.a", "libcodex_hia_prefix_match.a",
        "libcodex_hia_prefix_admission.a", "libcodex_hia_network_domains.a",
        "libcodex_hia_allowed_prefixes.a"]}

    def run(label, command, environment, timeout=180):
        started = time.monotonic()
        timed_out = False
        try:
            result = subprocess.run(command, cwd=ROOT / "codex-rs", env=environment,
                                    capture_output=True, timeout=timeout)
            streams = {name: getattr(result, name) for name in ("stdout", "stderr")}
            returncode = result.returncode
        except subprocess.TimeoutExpired as error:
            timed_out = True
            streams = {name: getattr(error, name) or b"" for name in ("stdout", "stderr")}
            returncode = None
        logs = {}
        for stream in ("stdout", "stderr"):
            path = artifacts / f"{label}.{stream}"
            path.write_bytes(streams[stream])
            logs[stream] = {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}
        report["commands"].append({"label": label, "command": command, "returncode": returncode,
                                   "timed_out": timed_out,
                                   "elapsed_seconds": time.monotonic() - started, **logs})
        if timed_out or returncode:
            raise RuntimeError(f"{label} exited {returncode}, timed_out={timed_out}: "
                               + streams["stderr"][-6000:].decode(errors="replace"))
        return streams["stdout"].decode()

    environment = os.environ.copy()
    # This execpolicy-only build owns its compiler capture chain; the inherited
    # apply-patch arithmetic-policy wrapper belongs to separate owner gates.
    environment.pop("RUSTC_WRAPPER", None)
    environment.update(RUSTC=rustc, GIT_TERMINAL_PROMPT="0", PYTHONDONTWRITEBYTECODE="1")
    report["rustc"] = run("rustc-version", [rustc, "--version", "--verbose"], environment)
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
        "os.execv(sys.argv[1], sys.argv[1:])\n"
    )
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
        selected = {}
        units = []
        binary = None
        for line in output.splitlines():
            row = json.loads(line)
            if row.get("reason") != "compiler-artifact":
                continue
            units.append(row)
            name = row["target"]["name"]
            rlibs = [Path(path) for path in row["filenames"] if path.endswith(".rlib")]
            if name == "codex_execpolicy" and rlibs:
                if name in selected and selected[name] != rlibs[0]:
                    raise RuntimeError(f"ambiguous dependency artifact: {name}")
                selected[name] = rlibs[0]
            if name == "codex-execpolicy" and row.get("executable"):
                binary = Path(row["executable"])
        if "codex_execpolicy" not in selected or binary is None:
            raise RuntimeError("Cargo did not report the actual owner artifacts")
        captures = {kind: Path(str(capture) + f".{kind}.json") for kind in ("lib", "bin")}
        lib_call, bin_call = [json.loads(captures[kind].read_text()) for kind in ("lib", "bin")]
        if Path(bin_call["externs"]["codex_execpolicy"]) != selected["codex_execpolicy"]:
            raise RuntimeError("the binary compiler did not consume the captured owner library")
        if ('feature="hia-native"' in lib_call["argv"]) != (mode == "native"):
            raise RuntimeError("captured library feature state differs from the intended oracle mode")
        runtime_units = {}
        for name in ("serde", "serde_json", "anyhow", "multimap"):
            metadata, linked = lib_call["externs"][name], bin_call["externs"][name]
            matches = [unit for unit in units if unit["target"]["name"] == name
                       and metadata in unit["filenames"] and linked in unit["filenames"]]
            if len(matches) != 1 or not linked.endswith(".rlib"):
                raise RuntimeError(f"library/binary dependency is not one Cargo artifact unit: {name}")
            selected[name] = Path(linked)
            runtime_units[name] = {key: matches[0][key] for key in ("package_id", "features", "profile", "filenames")}
            runtime_units[name]["metadata_sha256"] = sha(metadata)
        saved_rlib = artifacts / f"lib{mode}_execpolicy.rlib"
        saved_binary = artifacts / f"{mode}-codex-execpolicy"
        shutil.copy2(selected["codex_execpolicy"], saved_rlib)
        shutil.copy2(binary, saved_binary)
        builds[mode] = {"rlib": str(saved_rlib), "rlib_sha256": sha(saved_rlib),
                        "binary": str(saved_binary), "binary_sha256": sha(saved_binary),
                        "compiler_captures": {kind: {"path": str(path), "sha256": sha(path)}
                                              for kind, path in captures.items()},
                        "runtime_units": runtime_units,
                        "dependencies": {name: {"path": str(path), "sha256": sha(path)}
                                         for name, path in selected.items()}}
        if source_hashes() != captured:
            raise RuntimeError("source bytes changed during a real crate build")
    arguments = [rustc, "--edition=2024", "-C", "opt-level=3",
                 "--extern", f"original={builds['reference']['rlib']}",
                 "--extern", f"candidate={builds['native']['rlib']}",
                 "-L", f"native={library}"]
    for mode in builds.values():
        arguments += ["-L", "dependency=" + str(Path(mode["dependencies"]["codex_execpolicy"]["path"]).parent)]
    for name in ("serde", "serde_json", "anyhow", "multimap"):
        native = builds["native"]["dependencies"][name]
        if native != builds["reference"]["dependencies"][name]:
            raise RuntimeError(f"oracle/candidate dependency changed: {name}")
        arguments += ["--extern", f"{name}={native['path']}"]
    for label, filename, marker in [
        ("public", "native_allowed_prefixes.rs", "allowed_prefixes_public="),
        ("allocations", "native_allowed_prefixes_allocations.rs", "allowed_prefixes_allocations="),
        ("failures", "native_allowed_prefixes_failures.rs", "allowed_prefixes_failures="),
    ]:
        binary = artifacts / label
        run(f"compile-{label}", [*arguments, str(ROOT / "hia/tests" / filename), "-o", str(binary)], environment)
        if label != "failures":
            symbols = run(f"symbols-{label}", ["nm", "--defined-only", "--extern-only", str(binary)], environment)
            if not re.search(r"\bT codex_hia_allowed_prefixes$", symbols, re.MULTILINE):
                raise RuntimeError(f"{label}: actual native allowed-prefix symbol is missing")
        output = run(f"run-{label}", [str(binary)], environment)
        found = [line[len(marker):] for line in output.splitlines() if line.startswith(marker)]
        if len(found) != 1:
            raise RuntimeError(f"{label}: missing unique completion evidence")
        report[label] = {**json.loads(found[0]), "binary_sha256": sha(binary)}
        if report[label].get("passed") is not True:
            raise RuntimeError(f"{label}: did not pass")
    if source_hashes() != captured:
        raise RuntimeError("source bytes changed during public differential verification")
    if {name: sha(library / name) for name in report["native_inputs"]} != report["native_inputs"]:
        raise RuntimeError("native archives or build report changed during public verification")
    report.update(passed=True, full_policy_migration=False, performance_qualification=False,
                  profile="real dev crate artifacts; opt-level=3 external harness; diagnostic timings only")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, default=os.environ.get("CARGO_TARGET_DIR"))
    parser.add_argument("--rustc", default=os.environ.get("RUSTC", "rustc"))
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.report = args.report.resolve()
    if args.target_dir is None:
        parser.error("--target-dir or CARGO_TARGET_DIR is required")
    if args.report.exists() or args.report == ROOT or ROOT in args.report.parents:
        parser.error("select a new report path outside the checkout; retain prior evidence")
    report = {"schema": "codex.hia.native-allowed-prefixes.v1", "passed": False, "commands": []}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    try:
        verify(args, report)
    except (OSError, RuntimeError, ValueError, KeyError, IndexError, TypeError, AssertionError,
            subprocess.TimeoutExpired) as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], file=sys.stderr)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"passed": report["passed"], "report": str(args.report), "sha256": sha(args.report)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
