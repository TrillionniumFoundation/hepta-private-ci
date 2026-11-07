#!/usr/bin/env python3
# Read-only source52 proof after the preserved apply-attempt1 input-path failure.
from pathlib import Path, PurePosixPath
import hashlib,json,os,re,stat,subprocess,time


CANDIDATE_PINS = {'codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs': {'before': {'mode': '100644', 'bytes': 5606, 'sha256': 'af9ceab5047c7ee06bba84d47684748b38bfbb32e287db4a6fca84b2b45fa6fa', 'git_blob': '9e7cb31856c2b938c6a8ba73f8affb36bd4b5e3d'}, 'after': {'mode': '100644', 'bytes': 7325, 'sha256': '9d5107471e8d49b49271dda43cec319776c5f05d6ea66bca7e7167a1f345d4b4', 'git_blob': '747ae860d47bc33dfa48c7dcfb944dd6e4dd2865'}}, 'codex-rs/app-server/tests/suite/v2/bedrock_setup.rs': {'before': {'mode': '100644', 'bytes': 11612, 'sha256': '25c5036f352b673af21adfd37930f3f1762359b7422084c6e4eaaa9c1f513d55', 'git_blob': '87cfaf3ae45eafbc54dad94a96226f4a807209a5'}, 'after': {'mode': '100644', 'bytes': 11817, 'sha256': 'f3974a77783e82514a5828e055fdb9baf5bbbfad6dc3c7a10427e16b5c8d6710', 'git_blob': 'daaddd66a0b02a044263da26be6302b2d4ee4584'}}}

T = Path("/home/alex/work/hepta-cell-unified-20261106-a")

S = T / "source"

E = T / "evidence"

FRAMEWORK_PARENT = "bef6fa7645df9df12b69fda499e97eed25de6c75"

SOURCE52_COMMIT = '1e0910becc37383e6d17ecf861ea844fd07d8862'

SOURCE52_TREE = '211f15baff19095e8c98bcea2b0ed99ca2270ade'

SOURCE52_COUNT = 195

SOURCE52_MANIFEST_NAME = 'native-candidate-r28-source.json'

SOURCE52_MANIFEST_PIN = {'bytes': 55209, 'sha256': '3ff99b41bab572666b424fdbf9a508b33be13e6487d9effa7dd6a0e14b4ec898', 'git_blob': 'f057b526bf2ba492d6bb5810222f69ac0cc3bdd2'}

CARGO_LOCK_SHA256 = "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c"

BAZEL_LOCK_SHA256 = "e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb"

LOCKS = ("codex-rs/Cargo.lock", "MODULE.bazel.lock")

ALLOWED_PATHS = ('codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs', 'codex-rs/app-server/tests/suite/v2/bedrock_setup.rs')

FILE_KEYS = ("path", "mode", "bytes", "sha256", "git_blob")

EXISTING_BASELINE_LEAF_PINS = {'codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs': {'bytes': 5606, 'sha256': 'af9ceab5047c7ee06bba84d47684748b38bfbb32e287db4a6fca84b2b45fa6fa', 'git_blob': '9e7cb31856c2b938c6a8ba73f8affb36bd4b5e3d'}, 'codex-rs/app-server/tests/suite/v2/bedrock_setup.rs': {'bytes': 11612, 'sha256': '25c5036f352b673af21adfd37930f3f1762359b7422084c6e4eaaa9c1f513d55', 'git_blob': '87cfaf3ae45eafbc54dad94a96226f4a807209a5'}}

def require(value, message):
    if not value:
        raise RuntimeError(message)

def pin(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }

def safe_relative(value):
    require(isinstance(value, str) and bool(value), "relative path missing")
    p = PurePosixPath(value)
    require(not p.is_absolute() and str(p) == value, "noncanonical relative path")
    require(all(part not in ("", ".", "..") for part in p.parts), "unsafe relative path")
    require("\0" not in value and "\\" not in value, "unsafe path characters")
    return p

def digest(value, width):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{" + str(width) + r"}", value) is not None

def validate_pin(value):
    require(isinstance(value, dict) and set(value) == {"bytes", "sha256", "git_blob"}, "missing complete pin")
    require(type(value["bytes"]) is int and value["bytes"] >= 0, "invalid byte size")
    require(digest(value["sha256"], 64) and digest(value["git_blob"], 40), "invalid digest")

def git(*args):
    result = subprocess.run(["git", *args], cwd=S, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    require(result.returncode == 0, "git read failed: " + repr(args) + ": " + result.stderr.decode(errors="replace"))
    return result.stdout

def git_paths(*args):
    raw = git(*args)
    require(not raw or raw.endswith(b"\0"), "unterminated Git path list")
    paths = [part.decode("utf-8") for part in raw.split(b"\0") if part]
    for path in paths:
        safe_relative(path)
    require(len(paths) == len(set(paths)), "duplicate Git path")
    return paths

def normalized_files(entries):
    require(isinstance(entries, list), "source list missing")
    result = {}
    for entry in entries:
        row = {key: entry[key] for key in FILE_KEYS}
        safe_relative(row["path"])
        require(row["mode"] in ("100644", "100755"), "source mode unsupported")
        validate_pin({key: row[key] for key in ("bytes", "sha256", "git_blob")})
        require(row["path"] not in result, "duplicate manifest source")
        result[row["path"]] = row
    return result

def source_raw(path):
    p = S.joinpath(*safe_relative(path).parts)
    current = p
    while current != S:
        require(not current.is_symlink(), "symlink in source path: " + path)
        current = current.parent
    mode = p.stat().st_mode
    require(stat.S_ISREG(mode), "not a regular source: " + path)
    return p.read_bytes(), "100755" if mode & 0o111 else "100644"

def source_guard(files, expected_tree, expected_commit, expected_count):
    report = {"expected_tree": expected_tree, "source_commit": expected_commit, "expected_count": expected_count, "pass": False}
    try:
        report["actual_tree"] = git("write-tree").decode().strip()
        report["native_head"] = git("rev-parse", "HEAD").decode().strip()
        report["unstaged_paths"] = git_paths("diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z")
        report["untracked_paths"] = git_paths("ls-files", "--others", "--exclude-standard", "-z")
        paths = git_paths("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", FRAMEWORK_PARENT, report["actual_tree"])
        report["changed_paths"] = paths
        report["actual_changed_file_count"] = len(paths)
        report["changed_path_set_matches"] = set(paths) == set(files) and len(paths) == len(files)
        mismatches = []
        for path, expected in files.items():
            try:
                raw, actual_mode = source_raw(path)
                actual = {"path": path, "mode": actual_mode, **pin(raw)}
                record = git("ls-tree", "-z", report["actual_tree"], "--", path)
                require(record.endswith(b"\0") and record.count(b"\0") == 1, "tree path missing/ambiguous")
                header, name = record[:-1].split(b"\t", 1)
                mode, kind, blob = header.decode().split()
                require(name.decode() == path and kind == "blob", "tree path/type mismatch")
                require(actual == expected and mode == actual_mode and blob == actual["git_blob"], "raw/Git/mode mismatch")
            except Exception as error:
                mismatches.append({"path": path, "error": repr(error)})
        report["file_mismatches"] = mismatches
        report["cargo_lock_sha256"] = pin((S / LOCKS[0]).read_bytes())["sha256"]
        report["bazel_lock_sha256"] = pin((S / LOCKS[1]).read_bytes())["sha256"]
        report["pass"] = (
            report["actual_tree"] == expected_tree
            and report["native_head"] == FRAMEWORK_PARENT
            and len(files) == expected_count == len(paths)
            and report["changed_path_set_matches"]
            and not report["unstaged_paths"] and not report["untracked_paths"] and not mismatches
            and report["cargo_lock_sha256"] == CARGO_LOCK_SHA256
            and report["bazel_lock_sha256"] == BAZEL_LOCK_SHA256
        )
        if expected_tree == SOURCE52_TREE:
            report["existing_repo_leaves_outside_prior_changed_manifest"] = existing_baseline_leaves_guard()
    except Exception as error:
        report["error"] = repr(error)
        report["pass"] = False
    return report

def existing_baseline_leaves_guard():
    leaves = []
    for path in ALLOWED_PATHS:
        expected = EXISTING_BASELINE_LEAF_PINS[path]
        record = git("ls-tree", "-z", SOURCE52_TREE, "--", path)
        require(record.endswith(b"\0") and record.count(b"\0") == 1, "existing baseline Git leaf absent or ambiguous")
        header, name = record[:-1].split(b"\t", 1)
        mode, kind, blob = header.decode().split()
        require(name.decode() == path and kind == "blob" and mode == "100644"
                and blob == expected["git_blob"], "existing source52 leaf Git identity differs")
        committed = git("cat-file", "blob", blob)
        require(pin(committed) == expected, "existing baseline Git blob bytes differ")
        raw, actual_mode = source_raw(path)
        require(actual_mode == mode and pin(raw) == expected, "existing baseline leaf working bytes/mode differ")
        require(CANDIDATE_PINS[path]["before"] == {"mode": mode, **expected},
                "candidate before pin is not the independently reviewed existing leaf")
        leaves.append({"path": path, "mode": mode, **pin(raw), "source_tree": SOURCE52_TREE,
                       "actual_working_bytes_equal_existing_Git_leaf": True})
    return {"before_existing_repo_leaves_not_in_prior_changed_manifest": True, "leaves": leaves}

raw = (E / SOURCE52_MANIFEST_NAME).read_bytes()
require(pin(raw) == SOURCE52_MANIFEST_PIN, "actual source52 manifest pin")
source = json.loads(raw)
files = normalized_files(source["changed_files"])
report = source_guard(files, SOURCE52_TREE, SOURCE52_COMMIT, SOURCE52_COUNT)
report.update({"schema": "hepta.source53-attempt1-unchanged52-readback.v1", "source_manifest": {"path": SOURCE52_MANIFEST_NAME, **pin(raw)}, "failed_apply_job": "1a1b24b6516-fc05-7d5f", "read_only_source_inspection": True, "source_mutation_executed": False, "rust_executed": False, "apply_evidence_directory_exists": (E / "native-source53-apply").exists(), "source53_output_manifest_exists": (E / "native-candidate-r30-source.json").exists(), "original_read_only_helpers_reused_byte_exact": True, "created_unix": time.time()})
report["pass"] = report["pass"] and not report["apply_evidence_directory_exists"] and not report["source53_output_manifest_exists"]
out = E / "native-source53-attempt1-unchanged52.json"
data = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
with out.open("xb") as stream:
    stream.write(data)
    stream.flush()
    os.fsync(stream.fileno())
print(json.dumps({"path": str(out), **pin(data), "pass": report["pass"], "actual_tree": report["actual_tree"], "native_head": report["native_head"], "count": report["actual_changed_file_count"]}), flush=True)
require(report["pass"], "unchanged source52 guard failed")
