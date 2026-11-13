#!/usr/bin/env python3
"""Pure byte, dependency and source-shape review; never loads or executes Rust."""
from pathlib import Path
import difflib
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parent
PACKETS = (
    ("production-v1", "3de167eff0444e7dd8f0f32ade0444c1a8ff5925"),
    ("identity-deadline-increment-v1", "1f9af98ea25445d7ff732cbbd313399883165fb1"),
    ("purpose-enum-increment-v1", "39f9709423e09a445b9221dbdd3767bc9778d6c2"),
    ("test-increment-v1", "00c44402b24c92e344f1bd29a5e578fdfadaf940"),
)
def pins(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}
def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(("not one literal", old[:100], text.count(old)))
    return text.replace(old, new)
def persist(relative, data):
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(("refuse overwrite of different preparation", str(path)))
    else:
        with path.open("xb") as f:
            f.write(data)
    return {"path": relative, **pins(data)}
def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()

state = {}
originals = {}
packets = []
artifacts = []
for directory, expected in PACKETS:
    raw = (ROOT / directory / "SOURCE_PACKET.json").read_bytes()
    assert pins(raw)["git_blob"] == expected
    packet = json.loads(raw)
    assert packet["base_commit"] == "cc57c7198db6293ccca562253c42fffbe2a04633"
    assert len({c["path"] for c in packet["changes"]}) == len(packet["changes"])
    patch = []
    for change in packet["changes"]:
        path = change["path"]
        assert change["mode"] == "100644" and path.startswith("codex-rs/hepta-agentd/src/")
        assert ".." not in Path(path).parts
        for side in ("before", "after"):
            text = change[side + "_text"]
            metadata = change[side]
            if text is None:
                assert metadata is None and side == "before"
            else:
                assert pins(text.encode()) == metadata
        before, after = change["before_text"], change["after_text"]
        if path in state:
            assert state[path] == before
        elif before is not None:
            originals[path] = before
        state[path] = after
        patch.extend(difflib.unified_diff(
            (before or "").splitlines(True), after.splitlines(True),
            fromfile="a/" + path if before is not None else "/dev/null",
            tofile="b/" + path,
        ))
    manifest = {k: v for k, v in packet.items() if k != "changes"}
    manifest["source_packet"] = pins(raw)
    manifest["changes"] = [
        {k: v for k, v in c.items() if k not in ("before_text", "after_text")}
        for c in packet["changes"]
    ]
    manifest["formatted"] = manifest["compiled"] = manifest["tests_executed"] = False
    artifacts.append(persist(directory + "/MANIFEST.json", json_bytes(manifest)))
    artifacts.append(persist(directory + "/EXACT_DELTA.patch", "".join(patch).encode()))
    packets.append(packet)

root_map_raw = (ROOT / "ROOT_76_MAP.original.json").read_bytes()
assert pins(root_map_raw)["git_blob"] == "f4066cf562953650ae7a10129c9a90d496630fca"
root_map = json.loads(root_map_raw)
root_rows = {r["path"]: r for r in root_map["rust_files"]}
test_packet = packets[-1]
for c in test_packet["changes"]:
    if c["before"] is not None:
        assert root_rows[c["path"]]["git_blob"] == c["before"]["git_blob"]
    else:
        assert c["path"] not in root_rows

# This inverse covers the whole original parent, including all eight old tests.
parent = next(c for c in test_packet["changes"] if c["path"].endswith("next_use_readback_tests.rs"))
inverse = parent["after_text"]
inverse = once(inverse, "    dataset_receipt: Option<OriginalCellQ24MaterialCommandReceiptV1>,\n", "")
inverse = once(inverse, "fixture: Some(fixture), task: None, held: None, dataset_receipt: None, peers: None,",
                       "fixture: Some(fixture), task: None, held: None, peers: None,")
inverse = once(inverse, "        self.dataset_receipt = Some(dataset.clone());\n", "")
inverse = once(inverse, '\n#[path = "circuit_evaluated_version_local_readback_tests.rs"]\nmod local_read;\n', "")
assert inverse == parent["before_text"]
old_test_names = re.findall(r"#\[tokio::test[^\n]*\]\s*async fn (\w+)", inverse)
assert len(old_test_names) == 8

# Removing the exact cfg(test) observation additions restores the complete
# production local backend. The temporary response binding has the same value.
local = next(c for c in test_packet["changes"] if c["path"].endswith("/circuit_learning_local_read.rs"))
inverse = local["after_text"]
inverse = once(inverse, "    #[cfg(test)]\n    probe: Mutex<Option<Arc<fixture::OriginalLocalReadProbeState>>>,\n", "")
inverse = once(inverse, "                #[cfg(test)]\n                probe: Mutex::new(None),\n", "")
inverse = once(inverse, "        #[cfg(test)]\n        let terminal = original.fixture_original_read_submitted()?;\n", "")
inverse = once(inverse, "            #[cfg(test)]\n            if let Some(terminal) = &terminal {\n                terminal.mark_original_started();\n            }\n", "")
inverse = once(inverse, "            let response = original.original.respond(", "            original.original.respond(")
inverse = once(inverse,
    "            .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())));\n"
    "            #[cfg(test)]\n"
    "            if response.is_ok() {\n"
    "                if let Some(terminal) = &terminal {\n"
    "                    terminal.pause_after_original_response(deadline)?;\n"
    "                }\n"
    "            }\n"
    "            response\n",
    "            .map_err(|error| Error::Owner(crate::AgentdError::Invalid(error.to_string())))\n")
inverse = once(inverse, '\n#[cfg(test)]\n#[path = "circuit_learning_local_read_support_tests.rs"]\nmod fixture;\n', "")
assert inverse == local["before_text"]

test = next(c for c in test_packet["changes"] if c["path"].endswith("version_local_readback_tests.rs"))
names = re.findall(r"#\[tokio::test[^\n]*\]\s*async fn (\w+)", test["after_text"])
assert len(names) == 7 and len(set(names)) == 7
assert "assert_eq!(" not in test["after_text"]
assert test["after_text"].count("require_equal(") == 23
assert "probe.original_submitted()" in test["after_text"]
assert "probe.wait_original_terminal().await;" in test["after_text"]
assert "std::time::Instant::now() >= fixed_end" in test["after_text"]
assert "tokio::time::sleep" not in test["after_text"]
support = next(c for c in test_packet["changes"] if c["path"].endswith("local_read_support_tests.rs"))["after_text"]
assert "wait_timeout(released, remaining)" in support
assert "slot.next_request_id =" not in support
assert ".respond(" not in support
assert "std::ptr::eq(" in state["codex-rs/hepta-agentd/src/circuit_retained_version_local_read.rs"]
assert "1..=128" in local["after_text"]
assert "LocalReadOperation" in local["after_text"]
for path, text in state.items():
    artifacts.append(persist("final-after/" + path, text.encode()))

result = {
    "format": "hepta-local-read-pure-static-package-review-v1",
    "status": "BYTE_AND_EXACT_SOURCE_SHAPE_CHECKS_COMPLETE_ONLY",
    "packets": [{"directory": d, "git_blob": p} for d, p in PACKETS],
    "root_integrated_production_map": pins(root_map_raw),
    "unique_local_overlay_paths": len(state),
    "old_parent_eight_tests_and_all_other_bytes_preserved_by_exact_inverse": True,
    "non_test_local_backend_preserved_by_explicit_cfg_test_inverse": True,
    "all_test_preimages_match_root_76_map": True,
    "new_test_methods": names,
    "whole_value_result_assertions": 23,
    "git_byte_hashes_and_sequential_preimages_verified": True,
    "new_test_helper_paths_use_original_tests_suffix_rule": True,
    "rust_parsing_or_type_checking_performed": False,
    "rust_formatter_compiler_cargo_native_or_qa_methods_executed": False,
    "full_collector_or_source_gate_executed": False,
    "source_ref_or_active_source_mutated": False,
    "limits": [
        "Source-text and byte checks are not Rust compilation or executed tests.",
        "These seven tests use the existing actual cold same-process T/B/S/C fixture.",
        "They do not qualify Fresh Root, public cross-UID, or a real ordinary task chain.",
        "The exact local 128th/129th request boundary is not runtime-covered by this fixture.",
        "Old original B responder budget and actual T/E limits remain unchanged.",
        "Distinct real T/E Arc with identical signed context rejection is delegated to the independent S/C fixture."
    ],
    "artifacts": artifacts,
}
persist("STATIC_BYTE_REVIEW.json", json_bytes(result))
print(json.dumps({k: result[k] for k in ("status", "unique_local_overlay_paths", "new_test_methods",
    "rust_formatter_compiler_cargo_native_or_qa_methods_executed")}, indent=2))
