#!/usr/bin/env python3
"""Compare the complete continuation dispatcher with the actual original crate.

Build both real owner variants and execute public, allocation and callee-error
probes. Raw ABI checks and the real Core consumer gate are separate.
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
    methods = re.findall(r"(?m)^    pub fn matches_for_command_with_options\([\s\S]*?^    }\n", policy)
    if len(methods) != 2 or "hia_native_command_dispatch" not in methods[0]:
        raise RuntimeError("both complete dispatch owners are required")
    blocks = [methods[1]]
    for name in ("match_exact_rules", "match_host_executable_rules"):
        matches = re.findall(rf"(?m)^    fn {name}\([\s\S]*?^    }}\n", policy)
        if len(matches) != 1:
            raise RuntimeError(f"complete original helper missing: {name}")
        blocks.append(matches[0])
    source = "\n".join(blocks)
    tokens = [token for token in TOKEN.findall(source) if not token.startswith(("//", "/*"))]
    digest = hashlib.sha256(json.dumps(tokens, separators=(",", ":")).encode()).hexdigest()
    if (len(tokens), digest) != (459, "10c23ef41a88326d5ea451cf5a81a3f695063d64fedbb32879bfe2a282edd2e9"):
        raise RuntimeError("complete original dispatcher differs from f75 oracle")
    records["dispatcher"] = {"token_count": len(tokens), "token_sha256": digest,
                             "overlap": "subregion of the complete 2372-token Policy pin; not additive"}
    services = {
        "codex-rs/execpolicy/src/executable_name.rs": "85414e488db0dba6a0b077cc038cc8f7ad0aa5695f927fc1fb05886f4d8adf7b",
        "codex-rs/utils/absolute-path/src/lib.rs": "a6f3553c4aefe49082b6bd8fb671eaaf14cf81cb134940bbd6b769024af01b70",
        "codex-rs/utils/absolute-path/src/absolutize.rs": "7a2c95d410b8503c2a26e37715bc403bd31496fcead7cdc4d95dc8e96ced77a7",
    }
    for path, expected in services.items():
        if sha(ROOT / path) != expected:
            raise RuntimeError(f"original path service changed: {path}")
    records["original_path_services"] = services
    return records


def source_hashes():
    paths = list((ROOT / "codex-rs/execpolicy").rglob("*.rs"))
    paths += [ROOT / "codex-rs/execpolicy/Cargo.toml", ROOT / "codex-rs/Cargo.toml",
              ROOT / "codex-rs/rust-toolchain.toml", ROOT / "codex-rs/Cargo.lock",
              ROOT / "hia/toolchain.json", ROOT / "hia/cargo_build.rs", ROOT / "hia/build.py",
              ROOT / "hia/tests/test_native_execpolicy_caller.py",
              ROOT / "hia/tests/test_native_policy_summary.py"]
    paths += list((ROOT / "hia").glob("*.hepta"))
    paths += list((ROOT / "codex-rs/utils/absolute-path").rglob("*.rs"))
    paths += list((ROOT / "hia/tests").glob("*command_dispatch*"))
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
        "libcodex_hia_allowed_prefixes.a", "libcodex_hia_command_dispatch.a"]}
    if args.predecessor_manifest is not None and args.prelinked_consumer_manifest is not None:
        raise RuntimeError("strict and prelinked predecessor descriptors are mutually exclusive")
    predecessor = (load_prelinked_consumer(args, report, target)
                   if args.prelinked_consumer_manifest is not None else load_predecessor(args, report, target))

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
    if predecessor is not None and report['predecessor']['rustc'] != report['rustc']:
        raise RuntimeError('current and predecessor performance owners use different rustc identities')
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
        for name in ("serde", "serde_json", "anyhow", "multimap", "codex_utils_absolute_path"):
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
    for name in ("serde", "serde_json", "anyhow", "multimap", "codex_utils_absolute_path"):
        native = builds["native"]["dependencies"][name]
        if native != builds["reference"]["dependencies"][name]:
            raise RuntimeError(f"oracle/candidate dependency changed: {name}")
        arguments += ["--extern", f"{name}={native['path']}"]
    for label, filename, marker in [
        ("public", "native_command_dispatch.rs", "command_dispatch_public="),
        ("effects", "native_command_dispatch_effects.rs", "command_dispatch_effects="),
        ("allocations", "native_command_dispatch_allocations.rs", "command_dispatch_allocations="),
        ("failures", "native_command_dispatch_failures.rs", "command_dispatch_failures="),
    ]:
        binary = artifacts / label
        run(f"compile-{label}", [*arguments, str(ROOT / "hia/tests" / filename), "-o", str(binary)], environment)
        if label != "failures":
            symbols = run(f"symbols-{label}", ["nm", "--defined-only", "--extern-only", str(binary)], environment)
            if not re.search(r"\bT codex_hia_command_dispatch$", symbols, re.MULTILINE):
                raise RuntimeError(f"{label}: actual native command-dispatch symbol is missing")
        child_environment = environment.copy()
        child_arguments = [str(binary)]
        if label == "effects":
            directory = artifacts / "path-effects"
            directory.mkdir()
            child_environment["HOME"] = str(directory / "home")
            child_arguments.append(str(directory))
        output = run(f"run-{label}", child_arguments, child_environment, timeout=300)
        found = [line[len(marker):] for line in output.splitlines() if line.startswith(marker)]
        if len(found) != 1:
            raise RuntimeError(f"{label}: missing unique completion evidence")
        report[label] = {**json.loads(found[0]), "binary_sha256": sha(binary)}
        if report[label].get("passed") is not True:
            raise RuntimeError(f"{label}: did not pass")
    run_performance(report, builds, predecessor, library, artifacts, rustc, environment, run)
    if args.require_predecessor and not report['three_baseline_performance_executed']:
        raise RuntimeError('required three-baseline performance processes did not all complete')
    if source_hashes() != captured:
        raise RuntimeError("source bytes changed during public differential verification")
    if {name: sha(library / name) for name in report["native_inputs"]} != report["native_inputs"]:
        raise RuntimeError("native archives or build report changed during public verification")
    for path, expected in report.get("predecessor_inputs", {}).items():
        if sha(path) != expected:
            raise RuntimeError(f"predecessor evidence or artifact changed during verification: {path}")
    report.update(passed=True, full_policy_migration=False, performance_qualification=False,
                  passed_scope="requested public/effect/allocation/error gates and listed diagnostic timing processes only",
                  profile="real dev crate artifacts; opt-level=3 external harness; diagnostic timings only")


def load_predecessor(args, report, target):
    """Bind a frozen source-only tree and exact captured dependencies before Cargo."""
    if args.predecessor_manifest is None:
        report['predecessor'] = {'status': 'not_requested_no_descriptor', 'executed': False,
                                'published_revision': None, 'code_only_tree': None}
        if args.require_predecessor:
            raise RuntimeError('three-baseline qualification requires a real frozen15 artifact descriptor')
        return None
    inputs = {}

    def verified(path, expected):
        path = Path(path).resolve(strict=True)
        actual = sha(path)
        if actual != expected:
            raise RuntimeError(f'predecessor evidence/artifact changed: {path}')
        inputs[str(path)] = actual
        return path

    descriptor_path = args.predecessor_manifest.resolve(strict=True)
    inputs[str(descriptor_path)] = sha(descriptor_path)
    descriptor = json.loads(descriptor_path.read_text())
    source_path = verified(descriptor['source_manifest'], descriptor['source_manifest_sha256'])
    source = json.loads(source_path.read_text())
    base, tree = source['base_revision'], source['candidate_tree_without_new_canonical_docs']
    if not all(re.fullmatch('[0-9a-f]{40}', value) for value in (base, tree)):
        raise RuntimeError('predecessor lacks an actual base/code-only tree identity')
    published = descriptor.get('published_revision')
    if published is not None and not re.fullmatch('[0-9a-f]{40}', published):
        raise RuntimeError('invalid optional published predecessor revision')
    prior_path = verified(descriptor['public_report'], descriptor['public_report_sha256'])
    prior = json.loads(prior_path.read_text())
    if prior.get('passed') is not True or 'hia/allowed_prefixes.hepta' not in prior['source_sha256']:
        raise RuntimeError('predecessor is not a passed actual owner15 public report')
    if 'hia/command_dispatch.hepta' in prior['source_sha256']:
        raise RuntimeError('predecessor already contains the new dispatcher')
    if prior['oracle']['revision'] != ORIGINAL_REVISION or any(
            prior['oracle']['owners'][name] != report['oracle']['owners'][name]
            for name in ('policy', 'decision', 'execpolicycheck', 'rule')):
        raise RuntimeError('predecessor and current original-owner pins disagree')
    source_rows = {row['path']: row['sha256'] for row in source['files']}
    bound = set(source_rows) & set(prior['source_sha256'])
    required = {'hia/allowed_prefixes.hepta', 'codex-rs/execpolicy/src/policy.rs',
                'codex-rs/execpolicy/src/hia_native_allowed_prefixes.rs', 'hia/toolchain.json'}
    if not required <= bound or any(source_rows[path] != prior['source_sha256'][path] for path in bound):
        raise RuntimeError('predecessor final source and actual public report disagree')
    previous = json.loads(json.dumps(prior['builds']['native']))
    verified(previous['rlib'], previous['rlib_sha256'])
    captures = {kind: json.loads(verified(row['path'], row['sha256']).read_text())
                for kind, row in previous['compiler_captures'].items()}
    if 'feature="hia-native"' not in captures['lib']['argv']:
        raise RuntimeError('predecessor compiler capture did not enable the native feature')
    if captures['bin']['externs']['codex_execpolicy'] != previous['dependencies']['codex_execpolicy']['path']:
        raise RuntimeError('predecessor binary did not consume its reported owner library')
    commands = [row for row in prior['commands'] if row['label'] == 'build-native']
    if len(commands) != 1 or commands[0]['returncode'] != 0 or commands[0].get('timed_out'):
        raise RuntimeError('missing unique successful predecessor Cargo artifact stream')
    stdout = commands[0]['stdout']
    units = [json.loads(line) for line in verified(stdout['path'], stdout['sha256']).read_text().splitlines()]
    exact_units = {}
    for name in ('serde', 'serde_json', 'anyhow', 'multimap', 'codex_utils_absolute_path'):
        metadata, linked = captures['lib']['externs'][name], captures['bin']['externs'][name]
        matches = [unit for unit in units if unit.get('reason') == 'compiler-artifact'
                   and unit['target']['name'] == name and metadata in unit['filenames'] and linked in unit['filenames']]
        if len(matches) != 1 or not linked.endswith('.rlib'):
            raise RuntimeError(f'predecessor dependency lacks one exact Cargo/capture unit: {name}')
        dependency_dir = Path(linked).resolve(strict=True).parent
        if target == dependency_dir or target in dependency_dir.parents or dependency_dir in target.parents:
            raise RuntimeError('owner16 Cargo target overlaps the frozen predecessor dependency directory')
        recorded = previous['dependencies'].get(name)
        if recorded is not None and (recorded['path'] != linked or recorded['sha256'] != sha(linked)):
            raise RuntimeError(f'predecessor recorded dependency changed: {name}')
        for path in (metadata, linked):
            inputs[str(Path(path).resolve(strict=True))] = sha(path)
        previous['dependencies'][name] = {'path': linked, 'sha256': sha(linked)}
        exact_units[name] = {'cargo_unit': {key: matches[0][key] for key in ('package_id', 'features', 'profile', 'filenames')},
                             'metadata_sha256': sha(metadata), 'linked_sha256': sha(linked),
                             'hash_already_in_original_report': recorded is not None}
    for row in previous['dependencies'].values():
        verified(row['path'], row['sha256'])
    prior_library = Path(descriptor['library_dir']).resolve(strict=True)
    for name, expected in prior['native_inputs'].items():
        verified(prior_library / name, expected)
    report['predecessor_inputs'] = inputs
    report['predecessor'] = {'status': 'validated_frozen_source_only_artifacts', 'base_revision': base,
        'code_only_tree': tree, 'published_revision': published, 'descriptor': str(descriptor_path),
        'descriptor_sha256': sha(descriptor_path), 'source_manifest': str(source_path),
        'source_manifest_sha256': sha(source_path), 'public_report': str(prior_path),
        'public_report_sha256': sha(prior_path), 'runtime_bound_final_source_paths': sorted(bound),
        'manifest_only_paths': sorted(set(source_rows) - bound), 'exact_dependency_units': exact_units,
        'rustc': prior['rustc'],
        'supplemental_hash_scope': 'missing direct hashes are measured now from exact original capture/Cargo-unit paths; they are not claimed to have appeared in the prior report'}
    return previous, prior_library


def performance_completion(output, label):
    prefix = 'command_dispatch_performance='
    lines = [line[len(prefix):] for line in output.splitlines() if line.startswith(prefix)]
    if len(lines) != 1:
        raise RuntimeError(f'{label}: missing unique performance completion evidence')
    result = json.loads(lines[0])
    if (result.get('passed') is not True or result.get('label') != label
            or type(result.get('skipped')) is not int or result['skipped'] != 0
            or len(result.get('rows', [])) != 16):
        raise RuntimeError(f'{label}: completion label/count/skip contract failed')
    fields = ('iterations', 'checksum', 'rules', 'paths', 'command_bytes', 'nanoseconds')
    if len({row['case'] for row in result['rows']}) != 16 or any(
            not isinstance(row['case'], str) or any(type(row[key]) is not int or row[key] < 0 for key in fields)
            for row in result['rows']):
        raise RuntimeError(f'{label}: malformed performance workload or timing')
    return result


def load_prelinked_consumer(args, report, target):
    """Verify a previously linked native15 consumer without relinking lost inputs."""
    inputs = {}

    def checked(path, expected, size=None):
        path = Path(path).resolve(strict=True)
        actual = sha(path)
        if actual != expected or (size is not None and path.stat().st_size != size):
            raise RuntimeError(f'prelinked input changed: {path}')
        inputs[str(path)] = actual
        return path

    descriptor_path = args.prelinked_consumer_manifest.resolve(strict=True)
    inputs[str(descriptor_path)] = sha(descriptor_path)
    descriptor = json.loads(descriptor_path.read_text())
    if descriptor.get('schema') != 'codex.hia.command-dispatch.verified-prelinked-consumer.v1' or descriptor.get('label') != 'native15':
        raise RuntimeError('prelinked descriptor schema/label is invalid')
    history_row = descriptor['historical_report']
    history_path = checked(history_row['path'], history_row['sha256'], history_row['bytes'])
    history = json.loads(history_path.read_text())
    if (history.get('passed') is not True or history.get('three_baseline_performance_executed') is not True
            or history.get('three_baseline_performance_required') is not True
            or set(history['performance']) != {'original', 'native15', 'native16'}):
        raise RuntimeError('prelinked provenance lacks actual completed three-baseline qualification')
    if history['oracle'] != report['oracle']:
        raise RuntimeError('prelinked historical and current original-owner oracle disagree')
    closure = ('hia/tests/native_command_dispatch_performance.rs', 'hia/tests/command_dispatch_fixtures.rs')
    for name in closure:
        if sha(ROOT / name) != history['source_sha256'][name]:
            raise RuntimeError(f'prelinked harness closure changed: {name}')
    prior_row = descriptor['predecessor_descriptor']
    prior_descriptor_path = checked(prior_row['path'], prior_row['sha256'], prior_row['bytes'])
    prior_descriptor = json.loads(prior_descriptor_path.read_text())
    if str(prior_descriptor_path) != history['predecessor']['descriptor'] or prior_row['sha256'] != history['predecessor']['descriptor_sha256']:
        raise RuntimeError('prelinked original predecessor descriptor differs from historical binding')
    source_path = checked(prior_descriptor['source_manifest'], prior_descriptor['source_manifest_sha256'])
    source = json.loads(source_path.read_text())
    prior_path = checked(prior_descriptor['public_report'], prior_descriptor['public_report_sha256'])
    prior = json.loads(prior_path.read_text())
    if (prior.get('passed') is not True or prior['oracle']['revision'] != ORIGINAL_REVISION
            or prior['rustc'] != history['rustc'] or history['predecessor']['rustc'] != history['rustc']
            or any(prior['oracle']['owners'][name] != report['oracle']['owners'][name]
                   for name in ('policy', 'decision', 'execpolicycheck', 'rule'))):
        raise RuntimeError('prelinked original15 oracle/compiler provenance disagrees')
    if (source['base_revision'] != history['predecessor']['base_revision']
            or source['candidate_tree_without_new_canonical_docs'] != history['predecessor']['code_only_tree']
            or prior_descriptor.get('published_revision') != history['predecessor']['published_revision']):
        raise RuntimeError('prelinked original15 source/publication identity disagrees')
    source_root = Path(descriptor['predecessor_source_root']).resolve(strict=True)
    for row in source['files']:
        checked(source_root / row['path'], row['sha256'], row['bytes'])
        if row['path'] in prior['source_sha256'] and row['sha256'] != prior['source_sha256'][row['path']]:
            raise RuntimeError('prelinked original15 final source and runtime report disagree')
    previous = prior['builds']['native']
    owner = checked(previous['rlib'], previous['rlib_sha256'])
    captures = {kind: json.loads(checked(row['path'], row['sha256']).read_text())
                for kind, row in previous['compiler_captures'].items()}
    if ('feature="hia-native"' not in captures['lib']['argv']
            or captures['bin']['externs']['codex_execpolicy'] != previous['dependencies']['codex_execpolicy']['path']):
        raise RuntimeError('prelinked saved15 owner is not bound to its actual native Cargo unit')
    for capture in captures.values():
        actual_externs = [capture['argv'][index + 1].split('=', 1)
                          for index, word in enumerate(capture['argv']) if word == '--extern']
        if len(actual_externs) != len(dict(actual_externs)) or dict(actual_externs) != capture['externs']:
            raise RuntimeError('prelinked original15 capture extern map differs from actual compiler argv')
    if captures['lib']['compiler'] != captures['bin']['compiler']:
        raise RuntimeError('prelinked original15 library/binary compiler identities differ')
    cargo_rows = [row for row in prior['commands'] if row['label'] == 'build-native']
    if len(cargo_rows) != 1 or cargo_rows[0]['returncode'] != 0 or cargo_rows[0].get('timed_out') is not False:
        raise RuntimeError('prelinked original15 lacks a unique successful Cargo artifact stream')
    cargo_streams = {kind: checked(cargo_rows[0][kind]['path'], cargo_rows[0][kind]['sha256'],
                                   cargo_rows[0][kind]['bytes']).read_text() for kind in ('stdout', 'stderr')}
    units = [json.loads(line) for line in cargo_streams['stdout'].splitlines()]
    owner_unit = [unit for unit in units if unit.get('reason') == 'compiler-artifact'
                  and unit['target']['name'] == 'codex_execpolicy'
                  and previous['dependencies']['codex_execpolicy']['path'] in unit['filenames']]
    if (len(owner_unit) != 1 or 'hia-native' not in owner_unit[0]['features']
            or previous['dependencies']['codex_execpolicy']['sha256'] != previous['rlib_sha256']):
        raise RuntimeError('prelinked saved15 owner lacks one exact original Cargo artifact unit')
    exact_units = history['predecessor']['exact_dependency_units']
    dependency_paths = {}
    for name in ('serde', 'serde_json', 'anyhow', 'multimap', 'codex_utils_absolute_path'):
        metadata, linked = captures['lib']['externs'][name], captures['bin']['externs'][name]
        matches = [unit for unit in units if unit.get('reason') == 'compiler-artifact'
                   and unit['target']['name'] == name and metadata in unit['filenames'] and linked in unit['filenames']]
        exact = exact_units[name]
        if (len(matches) != 1 or not linked.endswith('.rlib')
                or {key: matches[0][key] for key in ('package_id', 'features', 'profile', 'filenames')} != exact['cargo_unit']
                or history['predecessor_inputs'][metadata] != exact['metadata_sha256']
                or history['predecessor_inputs'][linked] != exact['linked_sha256']):
            raise RuntimeError(f'prelinked original15 dependency lacks one exact Cargo/capture/history unit: {name}')
        recorded = previous['dependencies'].get(name)
        if recorded is not None and recorded != {'path': linked, 'sha256': exact['linked_sha256']}:
            raise RuntimeError(f'prelinked original15 reported dependency differs from historical binding: {name}')
        if name in previous['runtime_units'] and previous['runtime_units'][name] != {
                **exact['cargo_unit'], 'metadata_sha256': exact['metadata_sha256']}:
            raise RuntimeError(f'prelinked original15 recorded Cargo unit differs from actual stream: {name}')
        dependency_paths[name] = linked
        dependency_dir = Path(linked).resolve().parent
        if target == dependency_dir or target in dependency_dir.parents or dependency_dir in target.parents:
            raise RuntimeError('current Cargo target overlaps the original predecessor dependency directory')
    library = Path(prior_descriptor['library_dir']).resolve(strict=True)
    for name, expected in prior['native_inputs'].items():
        checked(library / name, expected)
    result = history['performance']['native15']
    binary_row = descriptor['binary']
    binary = checked(binary_row['path'], binary_row['sha256'], binary_row['bytes'])
    if binary == target or target in binary.parents:
        raise RuntimeError('prelinked binary must be outside the current Cargo target')
    if (binary_row['sha256'] != result['binary_sha256'] or previous['rlib_sha256'] != result['owner_rlib_sha256']
            or result['harness_sha256'] != history['source_sha256'][closure[0]]):
        raise RuntimeError('prelinked binary/owner/harness identities disagree')
    command_records = {}
    for label in ('compile-performance-native15', 'symbols-performance-native15', 'run-performance-native15'):
        rows = [row for row in history['commands'] if row['label'] == label]
        if len(rows) != 1 or rows[0]['returncode'] != 0 or rows[0].get('timed_out') is not False:
            raise RuntimeError(f'prelinked historical command did not succeed uniquely: {label}')
        row = rows[0]
        streams = {kind: checked(row[kind]['path'], row[kind]['sha256'], row[kind]['bytes']).read_text()
                   for kind in ('stdout', 'stderr')}
        command_records[label] = (row, streams)
    compile_argv = command_records['compile-performance-native15'][0]['command']
    symbols_argv = command_records['symbols-performance-native15'][0]['command']
    run_argv = command_records['run-performance-native15'][0]['command']
    historical_binary = compile_argv[compile_argv.index('-o') + 1]
    if (compile_argv[0] != captures['lib']['compiler'] or f'owner={owner}' not in compile_argv
            or f'native={library}' not in compile_argv or run_argv != [historical_binary, 'native15']
            or symbols_argv != ['nm', '--defined-only', '--extern-only', historical_binary]):
        raise RuntimeError('prelinked original compile/nm/run arguments do not bind the saved owner')
    harness = Path(compile_argv[-3])
    if str(harness).endswith('/' + closure[0]) is not True or compile_argv[-2] != '-o':
        raise RuntimeError('prelinked original compile lacks the exact performance harness')
    expected_compile = [captures['lib']['compiler'], '--edition=2024', '-C', 'opt-level=3',
                        '--extern', f'owner={owner}', '-L', f'native={library}']
    for name, linked in dependency_paths.items():
        expected_compile += ['--extern', f'{name}={linked}']
    dependency_dirs = {Path(path).parent for path in [
        previous['dependencies']['codex_execpolicy']['path'], *dependency_paths.values()]}
    for directory in sorted(dependency_dirs):
        expected_compile += ['-L', f'dependency={directory}']
    expected_compile += [str(harness), '-o', historical_binary]
    if compile_argv != expected_compile:
        raise RuntimeError('prelinked historical compile externs/dependency directories differ from original15 Cargo captures')
    for name in closure:
        checked(harness.parents[2] / name, history['source_sha256'][name])
    if re.search(r'\bT codex_hia_command_dispatch$', command_records['symbols-performance-native15'][1]['stdout'], re.MULTILINE):
        raise RuntimeError('prelinked historical consumer contains the new dispatcher')
    completed = performance_completion(command_records['run-performance-native15'][1]['stdout'], 'native15')
    expected_result = {**completed, 'binary_sha256': binary_row['sha256'],
                       'owner_rlib_sha256': previous['rlib_sha256'], 'harness_sha256': sha(ROOT / closure[0])}
    if expected_result != result:
        raise RuntimeError('prelinked original completion differs from its historical report')
    loss_row = descriptor['target_loss_report']
    loss_path = checked(loss_row['path'], loss_row['sha256'], loss_row['bytes'])
    loss = json.loads(loss_path.read_text())
    if len(loss['missing']) != 11 or loss['changed']:
        raise RuntimeError('prelinked mode requires the explicit reviewed original target-loss evidence')
    availability = []
    for name, expected in history['predecessor_inputs'].items():
        path = Path(name)
        row = {'path': name, 'expected_sha256': expected, 'exists': path.is_file()}
        if row['exists']:
            row['sha256'] = sha(path)
            row['bytes'] = path.stat().st_size
        availability.append(row)
    if availability != loss['all_inputs']:
        raise RuntimeError('prelinked historical input availability changed since the reviewed target-loss audit')
    report['predecessor_inputs'] = inputs
    report['predecessor'] = {'status': 'verified_prelinked_consumer', 'mode': 'verified-prelinked-consumer',
        'rustc': history['rustc'], 'published_revision': prior_descriptor.get('published_revision'),
        'historical_report': str(history_path), 'historical_report_sha256': sha(history_path),
        'descriptor': str(descriptor_path), 'descriptor_sha256': sha(descriptor_path),
        'binary': str(binary), 'binary_sha256': sha(binary), 'saved_owner_rlib': str(owner),
        'saved_owner_rlib_sha256': sha(owner), 'dual_harness_sha256': {name: sha(ROOT / name) for name in closure},
        'historical_command_streams': {name: row for name, (row, _) in command_records.items()},
        'original15_cargo_command': cargo_rows[0], 'exact_dependency_units': exact_units,
        'original_target_unchanged': False, 'target_loss_report': str(loss_path),
        'current_original_input_availability': availability, 'compiled_now': False, 'executed_now': False}
    return {'rlib': str(owner), 'rlib_sha256': sha(owner), 'prelinked_consumer': str(binary),
            'prelinked_sha256': sha(binary), 'historical_workload': [
                {key: row[key] for key in ('case', 'iterations', 'checksum', 'rules', 'paths', 'command_bytes')}
                for row in completed['rows']]}, library


def run_performance(report, builds, predecessor, library, artifacts, rustc, environment, run):
    """Compile one actual owner per executable, including an optional frozen15."""
    modes = [("original", builds['reference'], library), ("native16", builds['native'], library)]
    if predecessor is not None:
        modes.insert(1, ('native15', predecessor[0], predecessor[1]))
    report['performance'] = {}
    for label, build, native_library in modes:
        rlib = Path(build['rlib']).resolve(strict=True)
        if sha(rlib) != build['rlib_sha256']:
            raise RuntimeError(f'{label}: actual owner artifact changed')
        executable = artifacts / f'performance-{label}'
        source = ROOT / 'hia/tests/native_command_dispatch_performance.rs'
        prelinked = build.get('prelinked_consumer')
        if prelinked is not None:
            executable = Path(prelinked)
            if label != 'native15' or sha(executable) != build['prelinked_sha256']:
                raise RuntimeError('prelinked native15 consumer changed before execution')
        else:
            command = [rustc, '--edition=2024', '-C', 'opt-level=3', '--extern', f'owner={rlib}',
                       '-L', f'native={native_library}']
            dependency_dirs = set()
            for name, record in build['dependencies'].items():
                dependency = Path(record['path']).resolve(strict=True)
                if sha(dependency) != record['sha256']:
                    raise RuntimeError(f'{label}: actual dependency changed: {name}')
                dependency_dirs.add(dependency.parent)
                if name in ('serde', 'serde_json', 'anyhow', 'multimap', 'codex_utils_absolute_path'):
                    command += ['--extern', f'{name}={dependency}']
            for directory in sorted(dependency_dirs):
                command += ['-L', f'dependency={directory}']
            run(f'compile-performance-{label}', [*command, str(source), '-o', str(executable)], environment)
        symbols = run(f'symbols-performance-{label}', ['nm', '--defined-only', '--extern-only', str(executable)], environment)
        has_dispatcher = bool(re.search(r'\bT codex_hia_command_dispatch$', symbols, re.MULTILINE))
        if has_dispatcher != (label == 'native16'):
            raise RuntimeError(f'{label}: performance executable has the wrong dispatcher linkage')
        output = run(f'run-performance-{label}', [str(executable), label], environment, timeout=300)
        result = performance_completion(output, label)
        if prelinked is not None and [{key: row[key] for key in (
                'case', 'iterations', 'checksum', 'rules', 'paths', 'command_bytes')}
                for row in result['rows']] != build['historical_workload']:
            raise RuntimeError('native15: current performance workload differs from the verified historical consumer')
        report['performance'][label] = {**result, 'binary_sha256': sha(executable),
            'owner_rlib_sha256': sha(rlib), 'harness_sha256': sha(source),
            'fixture_sha256': sha(ROOT / 'hia/tests/command_dispatch_fixtures.rs'),
            'compiled_now': prelinked is None, 'executed_now': True,
            'build_method': 'verified_prelinked_consumer' if prelinked else 'current_rustc_compile'}
        if prelinked is not None:
            report['predecessor']['executed_now'] = True
    reference = report['performance']['original']['rows']
    for label, result in report['performance'].items():
        fields = ('case', 'iterations', 'checksum', 'rules', 'paths', 'command_bytes')
        if [tuple(row[key] for key in fields) for row in result['rows']] != [
                tuple(row[key] for key in fields) for row in reference]:
            raise RuntimeError(f'{label}: performance workload/observable checksum changed')
    report['three_baseline_performance_executed'] = set(report['performance']) == {'original', 'native15', 'native16'}
    report['performance_qualification'] = False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, default=os.environ.get("CARGO_TARGET_DIR"))
    parser.add_argument("--rustc", default=os.environ.get("RUSTC", "rustc"))
    parser.add_argument("--cargo", default="cargo")
    predecessor_group = parser.add_mutually_exclusive_group()
    predecessor_group.add_argument("--predecessor-manifest", type=Path, help="Optional immutable frozen-15 artifact descriptor; never synthesize a future base")
    predecessor_group.add_argument("--prelinked-consumer-manifest", type=Path, help="Explicit verified prior consumer; never relink missing predecessor inputs")
    parser.add_argument("--require-predecessor", action="store_true", help="Fail before Cargo unless all three actual performance baselines are bound")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.report = args.report.resolve()
    if args.target_dir is None:
        parser.error("--target-dir or CARGO_TARGET_DIR is required")
    if args.report.exists() or args.report == ROOT or ROOT in args.report.parents:
        parser.error("select a new report path outside the checkout; retain prior evidence")
    report = {"schema": "codex.hia.native-command-dispatch.v1", "passed": False, "commands": [],
              "three_baseline_performance_required": args.require_predecessor,
              "three_baseline_performance_executed": False}
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
