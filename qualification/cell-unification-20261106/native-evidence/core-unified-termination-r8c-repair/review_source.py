import difflib
import hashlib
import json
import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parent


def pin(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest(),
    }


def code_mask(text):
    literal = re.compile(
        r'//[^\n]*|/\*[\s\S]*?\*/|(?:br|r)(?P<hash>#+)"[\s\S]*?"(?P=hash)'
        r'|(?:br|r)"[^"]*"|b?"(?:\\.|[^"\\])*"|b?\'(?:\\.|[^\'\\])\''
    )
    return literal.sub(lambda match: " " * len(match.group()), text)


def balanced_end(mask, start):
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = []
    for index in range(start, len(mask)):
        char = mask[index]
        if char in pairs:
            stack.append(pairs[char])
        elif char in ")]}":
            assert stack and stack.pop() == char
            if not stack:
                return index + 1
    raise AssertionError("unterminated Rust delimiter")


def assertions(text):
    mask = code_mask(text)
    result = []
    for match in re.finditer(r"\b(?:assert|assert_eq|assert_ne)!\s*[([{]", mask):
        start = match.end() - 1
        result.append(text[match.start() : balanced_end(mask, start)])
    return result


def function(text, name):
    start = text.index("async fn " + name + "(")
    mask = code_mask(text)
    brace = mask.index("{", start)
    return text[start : balanced_end(mask, brace)]


caller_map = json.loads((ROOT / "native-caller-map.json").read_text())
files = []
operations = []
all_patch = []
old_assertions = 0
new_tests = []
old_calls = 0
new_calls = 0
for source in caller_map["files"]:
    relative = source["path"]
    before_bytes = (ROOT / "original" / relative).read_bytes()
    after_bytes = (ROOT / "source" / relative).read_bytes()
    assert pin(before_bytes) == {
        key: source[key] for key in ["bytes", "sha256", "git_blob"]
    }
    before = before_bytes.decode()
    after = after_bytes.decode()
    old_lines = before.splitlines(keepends=True)
    new_lines = after.splitlines(keepends=True)
    edits = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        a=old_lines, b=new_lines, autojunk=False
    ).get_opcodes():
        if tag != "equal":
            edits.append(
                {
                    "path": relative,
                    "before_lines": [i1, i2],
                    "after_lines": [j1, j2],
                    "before": "".join(old_lines[i1:i2]),
                    "after": "".join(new_lines[j1:j2]),
                }
            )
    restored = list(new_lines)
    forwarded = list(old_lines)
    for edit in reversed(edits):
        i1, i2 = edit["before_lines"]
        j1, j2 = edit["after_lines"]
        restored[j1:j2] = old_lines[i1:i2]
        forwarded[i1:i2] = new_lines[j1:j2]
    assert "".join(restored).encode() == before_bytes
    assert "".join(forwarded).encode() == after_bytes
    operations.extend(edits)
    all_patch.extend(
        difflib.unified_diff(
            old_lines, new_lines, fromfile="a/" + relative, tofile="b/" + relative
        )
    )
    old_calls += before.count(".terminate_confirmed(")
    new_calls += after.count(".terminate_confirmed(")
    if relative.endswith("_tests.rs"):
        original_assertions = assertions(before)
        candidate_assertions = assertions(after)
        assert candidate_assertions[: len(original_assertions)] == original_assertions
        old_assertions += len(original_assertions)
        old_functions = set(re.findall(r"async fn (\w+)\(", before))
        new_functions = set(re.findall(r"async fn (\w+)\(", after))
        new_tests.extend(
            {"path": relative, "name": name}
            for name in sorted(new_functions - old_functions)
        )
    files.append({"path": relative, "before": pin(before_bytes), "after": pin(after_bytes)})

assert len(files) == 7
assert old_calls == 10 and new_calls == 15
assert len(new_tests) == 6
assert all(".terminate_confirmed()" not in (ROOT / "source" / f["path"]).read_text() for f in files)
original_mod = (ROOT / "original/codex-rs/core/src/unified_exec/mod_tests.rs").read_text()
candidate_mod = (ROOT / "source/codex-rs/core/src/unified_exec/mod_tests.rs").read_text()
assert function(original_mod, "unified_exec_persists_across_requests") == function(
    candidate_mod, "unified_exec_persists_across_requests"
)

original_process = (ROOT / "original/codex-rs/core/src/unified_exec/process.rs").read_text()
candidate_process = (ROOT / "source/codex-rs/core/src/unified_exec/process.rs").read_text()
suffix = "    fn observe_current_exit(&self) -> bool {"
assert original_process[original_process.index(suffix) :] == candidate_process[
    candidate_process.index(suffix) :
]
entry = """        if self.observe_current_exit() {
            self.finish_termination();
            return Ok(());
        }
"""
assert function(original_process, "terminate_confirmed").split(entry, 1)[0].endswith("{\n")
assert function(candidate_process, "terminate_confirmed").split(entry, 1)[0].endswith("{\n")
original_manager = (ROOT / "original/codex-rs/core/src/unified_exec/process_manager.rs").read_text()
candidate_manager = (ROOT / "source/codex-rs/core/src/unified_exec/process_manager.rs").read_text()
for text in [original_manager, candidate_manager]:
    assert "const TERMINATION_CONFIRMATION_BUDGET" in text or text == original_manager
original_tail = function(original_manager, "terminate_process").split("        let entry = {", 1)[1]
candidate_tail = function(candidate_manager, "terminate_process").split("        let entry = {", 1)[1]
assert original_tail == candidate_tail

patch = "".join(all_patch).encode()
(ROOT / "repair.patch").write_bytes(patch)
(ROOT / "edit-operations.json").write_text(json.dumps(operations, indent=2) + "\n")
manifest = {
    "schema": "hepta.core-unified-termination-candidate.v1",
    "status": "FROZEN_ISOLATED_CANDIDATE_NATIVE_VALIDATION_PENDING",
    "baseline_source_commit": "e0eca9e265c4deeb069ec940c9ec3acbe8cf0f81",
    "native_current_source_tree": caller_map["source_tree"],
    "native_callsite_inventory_sha256": hashlib.sha256(
        (ROOT / "native-caller-map.json").read_bytes()
    ).hexdigest(),
    "files": files,
    "patch": pin(patch),
    "mechanical_verification": {
        "all_seven_original_sources_match_native_raw_sha_and_git_blob": True,
        "all_seven_files_forward_and_inverse_exact": True,
        "original_assertion_macros_byte_identical_in_order": old_assertions,
        "original_real_shell_persistence_test_byte_identical": True,
        "original_process_methods_after_changed_entry_byte_identical": True,
        "original_manager_owner_identity_and_removal_tail_byte_identical": True,
        "original_callers_updated": old_calls,
        "new_direct_private_calls": new_calls - old_calls,
        "new_regression_tests": new_tests,
    },
    "validation": {
        "rust_builds_or_tests_run": False,
        "rust_format_not_run": True,
        "source_only_python_inverse_audit": True,
        "native_checkout_modified": False,
        "root_checkout_modified": False,
    },
}
(ROOT / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(
    json.dumps(
        {
            "manifest_sha256": hashlib.sha256((ROOT / "source-manifest.json").read_bytes()).hexdigest(),
            "patch": pin(patch),
            "old_assertions_preserved": old_assertions,
            "new_regression_tests": new_tests,
        },
        indent=2,
    )
)
