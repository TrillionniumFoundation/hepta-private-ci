"""Freeze only cloud source artifacts; never run Rust or Windows commands."""
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent
PREFIX = "codex-rs/windows-sandbox-rs/src/"
PATHS = [PREFIX + "acl_deny.rs", PREFIX + "acl_tests.rs"]
PRE = ["1f4a78406d71c8fef5e764fa473a48b769a1606c", "2afcc4e189fa8adfbe2a02c80fcc5c7554d1ef67"]


def identity(path):
    body = path.read_bytes()
    return {"path": str(path), "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def invoke(cwd, args):
    completed = subprocess.run(["git", *args], cwd=cwd, capture_output=True)
    row = {"argv": ["git", *args], "returncode": completed.returncode,
           "stdout": completed.stdout.decode(), "stderr": completed.stderr.decode()}
    COMMANDS.append(row)
    assert completed.returncode == 0, row
    return completed.stdout


def patch_roundtrip(label, before, after, paths, output):
    work = Path(tempfile.mkdtemp(prefix=label + "-", dir=ROOT))
    invoke(work, ["init", "--quiet"])
    for path in paths:
        target = work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((before / path).read_bytes())
    invoke(work, ["add", "--", *paths])
    for path in paths:
        (work / path).write_bytes((after / path).read_bytes())
    patch = invoke(work, ["diff", "--binary", "--full-index", "--no-ext-diff", "--", *paths])
    output.write_bytes(patch)
    for path in paths:
        (work / path).write_bytes((before / path).read_bytes())
    invoke(work, ["apply", "--check", str(output)])
    invoke(work, ["apply", str(output)])
    assert all((work / path).read_bytes() == (after / path).read_bytes() for path in paths)
    invoke(work, ["apply", "--reverse", "--check", str(output)])
    invoke(work, ["apply", "--reverse", str(output)])
    assert all((work / path).read_bytes() == (before / path).read_bytes() for path in paths)
    return {"label": label, "patch": identity(output), "postimages_exact": True,
            "reverse_preimages_exact": True, "paths": paths}


# Preserve the initially unformatted draft and its actual earlier Git result.
history = ROOT / "initial-draft"
history.mkdir(exist_ok=True)
for name in ("prepare.py", "full.patch", "roundtrip.json"):
    if (ROOT / name).exists() and not (history / name).exists():
        shutil.copyfile(ROOT / name, history / name)

for path, expected in zip(PATHS, PRE, strict=True):
    assert identity(ROOT / "source" / path)["git_blob"] == expected

prod_pre = (ROOT / "source" / PATHS[0]).read_text()
prod_post = (ROOT / "candidate" / PATHS[0]).read_text()
test_pre = (ROOT / "source" / PATHS[1]).read_text()
test_post = (ROOT / "candidate" / PATHS[1]).read_text()
identity_check = '''    ensure!(
        actual == expected,
        "deny repair path no longer identifies the retained object: {}",
        path.display()
    );'''
assert prod_post.count(identity_check) == 1
negative = ROOT / "negative"
for path in PATHS:
    target = negative / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((ROOT / "candidate" / path).read_bytes())
(negative / PATHS[0]).write_text(prod_post.replace(identity_check, "    let _ = actual == expected;"))

COMMANDS = []
roundtrips = [patch_roundtrip("positive", ROOT / "source", ROOT / "candidate", PATHS, ROOT / "full.patch")]
roundtrips.append(patch_roundtrip("negative", ROOT / "candidate", negative, [PATHS[0]], ROOT / "remove-identity-check.patch"))
roundtrips.append(patch_roundtrip("restore", negative, ROOT / "candidate", [PATHS[0]], ROOT / "restore-identity-check.patch"))
write_json(ROOT / "roundtrip.json", {"scope": "Cloud text/Git checks only; no Rust/Windows execution.", "commands": COMMANDS,
                                    "roundtrips": roundtrips})

# The unchanged matcher, query access, object query/no-op body and setter tail.
segments = {}
for name, start, before_end, after_end in [
    ("object_matcher", "#[derive(Clone, Copy)]", "pub(super) unsafe fn add_deny_ace(", "// Both IDs come from live handles."),
    ("initial_read_control_open", "    let raw = CreateFileW(", "    let object = OwnedHandle::from_raw_handle(raw as _);", "    let object = OwnedHandle::from_raw_handle(raw as _);"),
    ("query_and_complete_early_return", "    let mut info: FILE_STANDARD_INFO", "    // Keep query and update access", "    // Only repairs require WRITE_DAC"),
    ("acl_mutation_tail", "    let entry = EXPLICIT_ACCESS_W", None, None),
]:
    before = prod_pre[prod_pre.index(start):]
    # The initial open in the postimage must be the original query, not repair.
    scope = prod_post[prod_post.index("pub(super) unsafe fn add_deny_ace("):] if name == "initial_read_control_open" else prod_post
    after = scope[scope.index(start):]
    if before_end is not None:
        before = before[:before.index(before_end)]
        after = after[:after.index(after_end)]
    assert before == after, name
    segments[name] = {"byte_equal": True, "bytes": len(before.encode()), "sha256": hashlib.sha256(before.encode()).hexdigest()}

case_start = test_pre.index("#[test]\nfn existing_native_deny_does_not_require_write_dac")
new_start = test_post.index("#[test]\nfn deny_repair_rejects_a_replaced_path_before_mutating_either_object")
current_start = test_post.index("#[test]\nfn existing_native_deny_does_not_require_write_dac")
reconstructed = test_post[:current_start] + test_pre[case_start:]
for line in ("use std::io::Write;\n", "use std::os::windows::io::FromRawHandle;\n", "use std::os::windows::io::OwnedHandle;\n"):
    assert reconstructed.count(line) == 1
    reconstructed = reconstructed.replace(line, "")
assert reconstructed == test_pre
assertions = [
    "assert!(add_deny_write_ace(&path, sid.as_ptr())?);",
    "assert!(add_deny_read_ace(&path, sid.as_ptr())?);",
    '''assert_eq!(
        write_denied,
        Some(ERROR_ACCESS_DENIED as i32),
        "host control must really lack WRITE_DAC"
    );''',
    "assert_eq!(noops, (false, false));",
    "assert_eq!(native_dacl_bytes(&path)?, before);",
    '''assert_eq!(std::fs::read_to_string(&path)?, "retained");''',
]
old_case = test_pre[case_start:]
new_case = test_post[current_start:new_start]
previous = -1
for assertion in assertions:
    assert old_case.count(assertion) == 1
    assert new_case.count(assertion) == 1
    offset = new_case.index(assertion)
    assert offset > previous
    previous = offset
names = lambda text: re.findall(r"#\[test\]\nfn ([a-zA-Z0-9_]+)", text)
old_names, new_names = names(test_pre), names(test_post)
assert new_names == old_names + ["deny_repair_rejects_a_replaced_path_before_mutating_either_object"]
patch = (ROOT / "full.patch").read_text()
counts = {"paths": 2, "additions": sum(l.startswith("+") and not l.startswith("+++") for l in patch.splitlines()),
          "deletions": sum(l.startswith("-") and not l.startswith("---") for l in patch.splitlines())}
assert counts["additions"] < 500
negative_line = next(i for i, line in enumerate(test_post.splitlines(), 1) if '"a replacement object must not receive' in line) - 3
proof = {"production_preserved_segments": segments, "other_original_test_bodies_and_surrounding_text_exact": True,
         "original_six_no_write_dac_assertions_byte_equal_in_order": assertions,
         "original_test_names": old_names, "post_test_names": new_names, "change_counts": counts,
         "negative_semantic_change": "Only enforce(actual==expected) becomes an ignored comparison; both actual ID queries and every other guard/mutation/test stay unchanged.",
         "negative_required_marker": "deny_repair_identity: directory=false returned_ok=true replacement_changed=true original_changed=false",
         "negative_expected_panic_macro_line": negative_line,
         "negative_expected_assertion": "a replacement object must not receive the queried object's deny",
         "negative_scope": "First file row must reach physical replacement and then this assertion. Early FFI errors, general timeout, wrong panic, or missing marker are invalid controls. Directory row is covered by positive execution, not reached after the negative file panic.",
         "rust_compile_run": False, "rustfmt_run": False, "windows_native_run": False}
write_json(ROOT / "static-checks.json", proof)
mapping = [{"repository_path": path, "preimage": identity(ROOT / "source" / path),
            "postimage": identity(ROOT / "candidate" / path)} for path in PATHS]
write_json(ROOT / "source-map.json", {"base_head": "7e0b2303ed0242d83bf56202e8ffb17f5c856186",
                                     "base_tree": "3de59a6aa185b13c8758bff3e8fbc530edcef307",
                                     "paths": mapping, "counts": counts,
                                     "negative_source": identity(negative / PATHS[0])})
print(json.dumps({"counts": counts, "paths": mapping, "negative_line": negative_line,
                  "full_patch": identity(ROOT / "full.patch")}, indent=2))
