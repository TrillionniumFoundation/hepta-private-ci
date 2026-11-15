"""Build and execute the entire locked Similar crate with its exact observer."""
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tarfile

from .admission import binding, require, sha256, validate_binding

HERE = Path(__file__).resolve().parent
RUSTC_SHA = "4a84e05991ad6f2a84c1361c29b52b38c390365bd1fc269b1936c88d482a8928"
ARCHIVE_SHA = "bbbb5d9659141646ae647b42fe094daf6c6192d1620870b449d9557f748b2daa"
OBSERVER_SHA = "84c198694f35f3103ad24d7bcf9b437abda5a7b6bb55bd7ab3dd7d600fd65e5e"
CORPORA = {
    "adversarial": (3732, "132d95e8eeb009d1d3c8ea5f728be0a4991c4c2cd03da59f13b4aba195ce963f"),
    "baseline": (3026, "f993c7725a604e42fd46423a0e36e0a4be5e064f4de32f769398298a5de671cc"),
}
POLICIES = {0: ("checked", "checked"), 1: ("wrapping", "wrapping"),
            2: ("checked", "wrapping"), 3: ("wrapping", "checked")}


def create(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def inventory(snapshot, expected):
    rows = []
    for row in expected:
        path = snapshot / row["relative_path"]
        require(path.is_file() and path.stat().st_size == row["bytes"] and
                sha256(path) == row["sha256"], "the complete original source differs")
        rows.append(row)
    actual = {str(path.relative_to(snapshot)) for path in snapshot.rglob("*") if path.is_file()}
    require(actual == {row["relative_path"] for row in expected},
            "the original source file set differs")
    return rows


def wire(cases):
    return b"".join(
        struct.pack("<4Q", c["id"], c["context"], len(c["old"].encode()), len(c["new"].encode()))
        + c["old"].encode() + c["new"].encode() for c in cases
    )


def load_cases(name):
    count, digest = CORPORA[name]
    data = gzip.decompress((HERE / (name + ".json.gz")).read_bytes())
    require(hashlib.sha256(data).hexdigest() == digest, "the reviewed case corpus changed")
    cases = json.loads(data)
    require(len(cases) == count and [row["id"] for row in cases] == list(range(count)),
            "the complete case inventory changed")
    return data, cases


def command(work, commands, label, argv, *, cwd, stdin=None):
    stdout, stderr = work / (label + ".stdout"), work / (label + ".stderr")
    with stdout.open("xb") as out, stderr.open("xb") as err:
        source = Path(stdin).open("rb") if stdin is not None else None
        try:
            result = subprocess.run([str(value) for value in argv], cwd=cwd,
                                    stdin=source, stdout=out, stderr=err, timeout=120)
        finally:
            if source is not None:
                source.close()
    row = {"name": label, "argv": [str(value) for value in argv], "cwd": str(cwd),
           "returncode": result.returncode, "stdout": binding(stdout), "stderr": binding(stderr)}
    if stdin is not None:
        row["stdin"] = binding(stdin)
    commands.append(row)
    (work / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
    require(result.returncode == 0, "original command failed: " + label)
    return row



def library_argv(rustc, snapshot, mode, library):
    flag = "on" if mode == "checked" else "off"
    return [str(value) for value in (
        rustc, "--crate-name", "similar", "--edition=2018", "--crate-type", "rlib",
        snapshot / "src/lib.rs", "--cfg", 'feature="default"', "--cfg", 'feature="text"',
        "-C", "opt-level=2", "-C", "codegen-units=1", "-C", "overflow-checks=" + flag,
        "-C", "debug-assertions=" + flag, "-C", "panic=unwind", "-o", library,
    )]


def observer_argv(rustc, observer, policy, owner, library, binary):
    flag = "on" if owner == "checked" else "off"
    name = "similar_oracle" if policy < 2 else "oracle"
    return [str(value) for value in (
        rustc, "--edition=2024", "--crate-name", name, observer,
        "--extern", "similar=" + str(library), "-C", "opt-level=2", "-C", "codegen-units=1",
        "-C", "overflow-checks=" + flag, "-C", "debug-assertions=" + flag,
        "-C", "panic=unwind", "-o", binary,
    )]


def prepare(work, rustc, report):
    work.mkdir()
    require(sha256(rustc) == RUSTC_SHA, "the original reference requires the fixed Rust compiler")
    archive, observer = HERE / "similar-2.7.0.crate", HERE / "original_observer.rs"
    source_manifest = HERE / "similar_source.json"
    locked = json.loads(source_manifest.read_text())
    require(sha256(archive) == ARCHIVE_SHA and sha256(observer) == OBSERVER_SHA,
            "the complete original archive or observer changed")
    require(locked["archive_sha256"] == ARCHIVE_SHA and
            locked["crate"] == "similar" and locked["version"] == "2.7.0" and
            len(locked["files"]) == 73, "the locked full original inventory differs")
    snapshot = work / "similar-2.7.0"
    snapshot.mkdir()
    entries = {row["relative_path"]: row for row in locked["files"]}
    with tarfile.open(archive, "r:gz") as package:
        seen = set()
        for member in package.getmembers():
            parts = Path(member.name).parts
            require(parts and parts[0] == "similar-2.7.0" and ".." not in parts,
                    "unexpected archive path")
            if member.isdir():
                continue
            require(member.isfile() and len(parts) > 1, "nonregular original archive member")
            relative = str(Path(*parts[1:]))
            require(relative in entries and relative not in seen, "original archive member set differs")
            data = package.extractfile(member).read()
            expected = entries[relative]
            require(len(data) == expected["bytes"] and
                    hashlib.sha256(data).hexdigest() == expected["sha256"],
                    "original archive bytes differ: " + relative)
            target = snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(data)
            seen.add(relative)
        require(seen == set(entries), "the complete original archive was not extracted")
    files = inventory(snapshot, locked["files"])
    identity = {"schema": "codex.hia.unified-diff-complete-original-source.v1",
                "archive": binding(archive), "snapshot": str(snapshot), "files": files,
                "source_manifest": binding(source_manifest), "all_archive_members_exact": True}
    identity_path = work / "source-identity.json"
    create(identity_path, identity)
    commands = []
    report.update(compiler=binding(rustc), observer_source=binding(observer),
                  source_identity=binding(identity_path), complete_original_files=73,
                  reference_build_commands_file=str(work / "commands.json"))
    version = command(work, commands, "rustc-version", [rustc, "-vV"], cwd=work)
    require("release: 1.96.1\n" in Path(version["stdout"]["path"]).read_text() and
            "host: x86_64-unknown-linux-gnu\n" in Path(version["stdout"]["path"]).read_text(),
            "the actual reference compiler release/host differs")
    libdir = command(work, commands, "target-libdir", [rustc, "--print", "target-libdir"], cwd=work)
    target_libdir = Path(Path(libdir["stdout"]["path"]).read_text().strip())
    stdlib = [binding(path) for path in sorted(target_libdir.iterdir())
              if path.is_file() and path.suffix in (".rlib", ".so")]
    require(stdlib, "the actual Rust standard-library artifacts are missing")
    report["standard_library"] = stdlib
    libraries, binaries, builds = {}, {}, {}
    for mode in ("checked", "wrapping"):
        flag = "on" if mode == "checked" else "off"
        library = work / ("libsimilar-" + mode + ".rlib")
        argv = [rustc, "--crate-name", "similar", "--edition=2018", "--crate-type", "rlib",
                snapshot / "src/lib.rs", "--cfg", 'feature="default"', "--cfg", 'feature="text"',
                "-C", "opt-level=2", "-C", "codegen-units=1", "-C", "overflow-checks=" + flag,
                "-C", "debug-assertions=" + flag, "-C", "panic=unwind", "-o", library]
        row = command(work, commands, "compile-" + mode, argv, cwd=snapshot)
        row["library"] = binding(library)
        libraries[mode], builds[mode] = library, row
    observer_builds = {}
    for policy, (dependency, owner) in POLICIES.items():
        flag = "on" if owner == "checked" else "off"
        binary = work / ("oracle-policy-" + str(policy))
        crate_name = "similar_oracle" if policy < 2 else "oracle"
        argv = [rustc, "--edition=2024", "--crate-name", crate_name, observer,
                "--extern", "similar=" + str(libraries[dependency]),
                "-C", "opt-level=2", "-C", "codegen-units=1",
                "-C", "overflow-checks=" + flag, "-C", "debug-assertions=" + flag,
                "-C", "panic=unwind", "-o", binary]
        row = command(work, commands, "compile-observer-" + str(policy), argv, cwd=work)
        row.update(binary=binding(binary), rlib=binding(libraries[dependency]), policy=policy)
        observer_builds[policy], binaries[policy] = row, binary
    build_receipt = {
        "schema": "codex.hia.unified-diff-original-compilation.v1", "passed": True,
        "compiler": binding(rustc), "source_identity": binding(identity_path),
        "observer_source": binding(observer), "library_builds": builds,
        "observer_builds": observer_builds, "standard_library": stdlib,
        "features": ["default", "text"], "cargo_executed": False,
        "complete_original_files": 73,
    }
    build_path = work / "original-build.json"
    create(build_path, build_receipt)
    reports = {}
    for name, (count, digest) in CORPORA.items():
        data, cases = load_cases(name)
        case_path, input_path = work / (name + ".json"), work / (name + ".bin")
        case_path.write_bytes(data)
        input_path.write_bytes(wire(cases))
        observed = []
        for policy, (dependency, owner) in POLICIES.items():
            row = command(work, commands, name + "-policy-" + str(policy),
                          [binaries[policy]], cwd=work, stdin=input_path)
            require(Path(row["stderr"]["path"]).stat().st_size == 0,
                    "the original observer wrote unexpected stderr")
            row.update(policy=policy, binary=binding(binaries[policy]),
                       rlib=binding(libraries[dependency]))
            observed.append(row)
        value = {
            "schema": "codex.hia.unified-diff-canonical-original.v1", "passed": True,
            "case_count": count, "cases": binding(case_path), "input": binding(input_path),
            "corpus_name": name, "source_identity": binding(identity_path),
            "observer_source": binding(observer), "compiler": binding(rustc),
            "original_build": binding(build_path), "commands": observed,
            "policy_meaning": POLICIES, "tests_skipped": 0,
            "scope": "Fresh execution of the complete locked Similar 2.7.0 crate; all four explicit original compilation policies, no reconstructed reference algorithm.",
        }
        path = work / (name + "-report.json")
        create(path, value)
        validate_original_corpus(path)
        reports[name] = path
    inventory(snapshot, locked["files"])
    for row in stdlib:
        validate_binding(row)
    report.update(passed=True, original_build=binding(build_path),
                  corpus_reports={key: binding(path) for key, path in reports.items()},
                  sources_unchanged=True, commands=commands,
                  mixed_codex_production_configuration_qualified=False)
    return reports


def validate_original_corpus(report_path):
    report_path = Path(report_path)
    report = json.loads(report_path.read_text())
    require(report["schema"] == "codex.hia.unified-diff-canonical-original.v1" and
            report["passed"] is True, "the reference is not a fresh canonical original report")
    name = report["corpus_name"]
    count, digest = CORPORA[name]
    manifest_path = validate_binding(report["source_identity"])
    manifest = json.loads(manifest_path.read_text())
    locked_path = validate_binding(manifest["source_manifest"])
    require(locked_path == HERE / "similar_source.json", "mixed original source manifest")
    expected = json.loads(locked_path.read_text())["files"]
    archive = validate_binding(manifest["archive"])
    require(sha256(archive) == ARCHIVE_SHA and len(expected) == 73 and
            manifest["files"] == expected, "the full original source inventory differs")
    inventory(Path(manifest["snapshot"]), expected)
    build_path = validate_binding(report["original_build"])
    build = json.loads(build_path.read_text())
    require(build["schema"] == "codex.hia.unified-diff-original-compilation.v1" and
            build["passed"] is True and build["source_identity"] == report["source_identity"] and
            build["compiler"] == report["compiler"] and
            build["observer_source"] == report["observer_source"],
            "the executed original build provenance differs")
    require(sha256(validate_binding(report["compiler"])) == RUSTC_SHA and
            sha256(validate_binding(report["observer_source"])) == OBSERVER_SHA,
            "the original compiler or observer differs")
    for record in build["standard_library"]:
        validate_binding(record)
    for mode in ("checked", "wrapping"):
        row = build["library_builds"][mode]
        flag = "on" if mode == "checked" else "off"
        require(row["returncode"] == 0 and row["argv"] == library_argv(
                report["compiler"]["path"], Path(manifest["snapshot"]), mode, row["library"]["path"]),
                "the original library flags/source differ")
        for key in ("library", "stdout", "stderr"):
            validate_binding(row[key])
    cases_path, input_path = validate_binding(report["cases"]), validate_binding(report["input"])
    cases = json.loads(cases_path.read_text())
    require(sha256(cases_path) == digest and len(cases) == count == report["case_count"] and
            [row["id"] for row in cases] == list(range(count)) and
            input_path.read_bytes() == wire(cases), "the original reference corpus differs")
    references = {}
    inputs = [binding(path) for path in (report_path, manifest_path, archive, locked_path,
                                         build_path, cases_path, input_path)]
    require(len(report["commands"]) == 4, "all four original policies are required")
    for policy, (dependency, owner) in POLICIES.items():
        command_row = report["commands"][policy]
        observer_build = build["observer_builds"][str(policy)]
        flag = "on" if owner == "checked" else "off"
        require(command_row["policy"] == policy and command_row["returncode"] == 0 and
                command_row["binary"] == observer_build["binary"] and
                command_row["rlib"] == build["library_builds"][dependency]["library"] and
                observer_build["rlib"] == command_row["rlib"] and
                observer_build["returncode"] == 0 and
                observer_build["argv"] == observer_argv(
                    report["compiler"]["path"], report["observer_source"]["path"],
                    policy, owner, command_row["rlib"]["path"], command_row["binary"]["path"]),
                "the actual four-policy original compilation mapping differs")
        binary, library = validate_binding(command_row["binary"]), validate_binding(command_row["rlib"])
        require(command_row["argv"] == [str(binary)] and
                command_row["stdin"] == report["input"], "the original invocation differs")
        output, stderr = validate_binding(command_row["stdout"]), validate_binding(command_row["stderr"])
        require(stderr.stat().st_size == 0, "unexpected original observer stderr")
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        require(len(rows) == len(cases) and [row["id"] for row in rows] == list(range(count)),
                "the complete original transcript is truncated")
        for case, row in zip(cases, rows):
            require("construction_panic_hex" not in row and row["context"] == case["context"] and
                    row["algorithm"] == "Myers" and row["newline_terminated"] is True,
                    "unexpected complete-original construction result")
            require(b"".join(bytes.fromhex(token) for token in row["old_tokens"]) == case["old"].encode() and
                    b"".join(bytes.fromhex(token) for token in row["new_tokens"]) == case["new"].encode(),
                    "original token observations do not reconstruct the inputs")
        references[policy] = rows
        inputs.extend(binding(path) for path in (binary, library, output, stderr))
    return {"cases": cases, "references": references, "bindings": inputs,
            "commands": report["commands"], "complete_original_files": 73,
            "reference_transcripts_reused": True,
            "scope": "Fresh complete-source reference transcripts generated earlier in this same qualification invocation."}
