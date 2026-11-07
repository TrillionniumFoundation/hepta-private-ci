from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
BASE = "b44d4ca4aa0ef9f894eff29e9975938e066a82f5"
TREE = "d3d2313b838422818bf9448ce5a1b86d89abdf69"
EXPECTED_PATCHES = {
    "core-token-budget-r14-repair": "2d8fdd192a0c336acc999895109867bad26e386faa18f9d6636a43dceda5261d",
    "core-turn-state-r14-fixture": "bc8867f4515ab8f02fb02ed803dbe84f4b4c9b349b76ed73d2f2c03775bb158a",
}


def identity(data: bytes) -> dict:
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def apply_patch_exact(base: dict[str, bytes], patch: bytes, reverse: bool = False) -> dict[str, bytes]:
    lines = patch.decode().splitlines(keepends=True)
    out = dict(base)
    i = 0
    while i < len(lines):
        assert lines[i].startswith("--- a/")
        path = lines[i][6:].rstrip("\n")
        i += 1
        assert lines[i] == "+++ b/" + path + "\n"
        i += 1
        original_lines = base[path].decode().splitlines(keepends=True)
        new_lines = []
        cursor = 0
        while i < len(lines) and lines[i].startswith("@@ "):
            match = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*\n", lines[i])
            assert match
            old_start, old_len, new_start, new_len = (int(x or 1) for x in match.groups())
            i += 1
            old_chunk, new_chunk = [], []
            while i < len(lines) and not lines[i].startswith(("@@ ", "--- a/")):
                line = lines[i]
                assert line and line[0] in " +-", line
                if line[0] in " -":
                    old_chunk.append(line[1:])
                if line[0] in " +":
                    new_chunk.append(line[1:])
                i += 1
            assert len(old_chunk) == old_len and len(new_chunk) == new_len
            if reverse:
                old_start, new_start = new_start, old_start
                old_chunk, new_chunk = new_chunk, old_chunk
            start = old_start - 1
            assert start >= cursor
            assert original_lines[start : start + len(old_chunk)] == old_chunk
            new_lines.extend(original_lines[cursor:start])
            new_lines.extend(new_chunk)
            cursor = start + len(old_chunk)
        new_lines.extend(original_lines[cursor:])
        out[path] = "".join(new_lines).encode()
    return out


TOKEN = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\s+|[A-Za-z_][A-Za-z_0-9]*|[0-9]+|::|->|=>|\S')


def tokens(text: str) -> list[str]:
    return [m.group() for m in TOKEN.finditer(text) if not m.group().isspace() and not m.group().startswith(("//", "/*"))]


def code_mask(text: str) -> str:
    return TOKEN.sub(lambda m: " " * len(m.group()) if m.group().startswith(('"', "//", "/*")) else m.group(), text)


def matching(mask: str, start: int) -> int:
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = []
    for i in range(start, len(mask)):
        char = mask[i]
        if char in pairs:
            stack.append(pairs[char])
        elif char in pairs.values():
            assert stack and stack.pop() == char
            if not stack:
                return i
    raise AssertionError("unclosed expression")


def function(text: str, name: str) -> tuple[str, tuple[int, int]]:
    match = re.search(r"async fn " + re.escape(name) + r"\b", text)
    assert match
    mask = code_mask(text)
    start = mask.index("{", match.end())
    end = matching(mask, start) + 1
    return text[match.start():end], (match.start(), end)


def assertions(text: str) -> list[list[str]]:
    mask = code_mask(text)
    found = []
    for match in re.finditer(r"\bassert(?:_eq|_ne)?!\s*([({\[])", mask):
        end = matching(mask, match.end() - 1) + 1
        found.append(tokens(text[match.start():end]))
    return found


def batches(fn: str) -> list[list[list[str]]]:
    mask = code_mask(fn)
    result = []
    for match in re.finditer(r"requests:\s*vec!\s*\[", mask):
        start = match.end() - 1
        end = matching(mask, start)
        chunks = []
        cursor = start + 1
        while cursor < end:
            while cursor < end and (mask[cursor].isspace() or mask[cursor] == ","):
                cursor += 1
            if cursor == end:
                break
            assert re.match(r"vec!\s*\[", mask[cursor:])
            opening = mask.index("[", cursor)
            closing = matching(mask, opening)
            chunks.append(tokens(fn[cursor:closing + 1]))
            cursor = closing + 1
        result.append(chunks)
    return result


api_pins = {p["path"]: p for p in json.loads((ROOT / "primary-source-pins.json").read_bytes())}
verified = []
contents = {}
for directory, expected in EXPECTED_PATCHES.items():
    folder = WORKSPACE / directory
    manifest = json.loads((folder / "source-manifest.json").read_bytes())
    patch = (folder / "repair.patch").read_bytes()
    assert identity(patch)["sha256"] == expected
    originals, candidates = {}, {}
    for item in manifest["files"]:
        path = item["path"]
        originals[path] = (folder / "original" / path).read_bytes()
        candidates[path] = (folder / "source" / path).read_bytes()
        before, after = identity(originals[path]), identity(candidates[path])
        assert before["sha256"] == item["before_sha256"]
        assert after["sha256"] == item["after_sha256"]
        assert before["git_blob"] == item["before_blob"] == api_pins[path]["git_blob"]
        assert after["git_blob"] == item["after_blob"]
        verified.append({"path": path, "before": before, "after": after})
    assert apply_patch_exact(originals, patch) == candidates
    assert apply_patch_exact(candidates, patch, reverse=True) == originals
    contents[directory] = (originals, candidates)

support_paths = {
    "codex-rs/core/src/responses_metadata.rs": "core-code-mode-r8c-audit/original",
    "codex-rs/core/src/client.rs": "native-validation-results/checkpoint-through-r8d/source",
    "codex-rs/core/tests/common/responses.rs": "native-validation-results/core-fixture-metadata-audit/original",
    "codex-rs/codex-mcp/src/runtime.rs": "core-hooks-r14-audit/original",
    "codex-rs/rmcp-client/src/bin/test_stdio_server.rs": "core-hooks-r14-audit/original",
    "codex-rs/core/src/tasks/mod.rs": "core-recovery-epoch-r14-fixture/original",
    "codex-rs/core/src/codex_thread.rs": "core-recovery-epoch-r14-fixture/original",
    "codex-rs/core/tests/common/test_codex.rs": "core-hooks-r14-audit/original",
}
supports = []
for path, prefix in support_paths.items():
    data = (WORKSPACE / prefix / path).read_bytes()
    pin = identity(data)
    assert pin["git_blob"] == api_pins[path]["git_blob"], path
    supports.append({"path": path, "local_path": prefix + "/" + path, **pin})

token_original, token_candidate = contents["core-token-budget-r14-repair"]
token_path = "codex-rs/core/tests/suite/token_budget.rs"
assert assertions(token_original[token_path].decode()) == assertions(token_candidate[token_path].decode())
old_helper, old_range = function(token_original[token_path].decode(), "assert_context_compaction_item_lifecycle")
new_helper, new_range = function(token_candidate[token_path].decode(), "assert_context_compaction_item_lifecycle")
assert token_original[token_path].decode()[:old_range[0]] == token_candidate[token_path].decode()[:new_range[0]]
assert token_original[token_path].decode()[old_range[1]:] == token_candidate[token_path].decode()[new_range[1]:]
assert "pending_normal_turn_finish_completion(&completed.turn_id)" in new_helper
assert "completion.await;" in new_helper

state_original, state_candidate = contents["core-turn-state-r14-fixture"]
state_path = "codex-rs/core/tests/suite/turn_state.rs"
before_state, after_state = state_original[state_path].decode(), state_candidate[state_path].decode()
names = ["websocket_turn_state_persists_within_turn_and_resets_after", "websocket_turn_state_is_stable_within_turn"]
state_results = []
old_spans, new_spans = [], []
for number, name in enumerate(names):
    old_fn, old_span = function(before_state, name)
    new_fn, new_span = function(after_state, name)
    old_spans.append(old_span)
    new_spans.append(new_span)
    old_batches, new_batches = batches(old_fn), batches(new_fn)
    assert len(old_batches) == 1
    assert [len(x) for x in new_batches] == [1, 3]
    flattened = [batch for connection in new_batches for batch in connection]
    assert old_batches[0] == (flattened if number == 0 else new_batches[1])
    assert new_batches[0][0] == tokens('vec![ev_response_created("warm-1"), ev_completed("warm-1")]')
    assert re.findall(r"close_after_requests:\s*(true|false)", old_fn) == ["false"]
    assert re.findall(r"close_after_requests:\s*(true|false)", new_fn) == ["true", "false"]
    old_assertions, new_assertions = assertions(old_fn), assertions(new_fn)
    handshake_before = tokens("assert_eq!(server.handshakes().len(), 1)")
    handshake_after = tokens("assert_eq!(server.handshakes().len(), 2)")
    assert old_assertions.count(handshake_before) == new_assertions.count(handshake_after) == 1
    kept = [a for a in old_assertions if a != handshake_before]
    cursor = 0
    for assertion in kept:
        while cursor < len(new_assertions) and new_assertions[cursor] != assertion:
            cursor += 1
        assert cursor < len(new_assertions), (name, assertion)
        cursor += 1
    state_results.append({
        "function": name,
        "original_batch_counts": [len(x) for x in old_batches],
        "candidate_batch_counts": [len(x) for x in new_batches],
        "original_payload_token_sequences_preserved": True,
        "new_warm_batch_only": number == 1,
        "old_assertion_count": len(old_assertions),
        "new_assertion_count": len(new_assertions),
        "original_assertions_preserved_except_total_handshakes": True,
        "sampling_connection_close_after_requests": False,
    })

def without_spans(text: str, spans: list[tuple[int, int]]) -> str:
    for start, end in reversed(spans):
        text = text[:start] + text[end:]
    return text

assert without_spans(before_state, old_spans) == without_spans(after_state, new_spans)
closed_path = WORKSPACE / "native-validation-results/r14-blockers/native-core-r14-result-review.json"
closed_bytes = closed_path.read_bytes()
assert identity(closed_bytes)["sha256"] == "9b5b3a81d4901d8c6769908e2021235e3ef82e3257d5b0c21bf1c086899f0732"
closed = json.loads(closed_bytes)
failure_names = ["suite::token_budget::token_budget_context_injects_plain_thread_hint_text", "suite::token_budget::token_budget_context_uses_new_window_after_compaction::test_case_1_token_budget_only", "suite::token_budget::token_budget_context_uses_new_window_after_compaction::test_case_2_with_client_developer_retention"] + ["suite::turn_state::" + name for name in names]
failure_blocks = [b for b in closed["blocks"] if b["name"] in failure_names]
assert len(failure_blocks) == 5 and all(b["status"] == "FAIL" for b in failure_blocks)

report = {
    "schema": "hepta.independent-source-review.v1",
    "reviewer": "/root/differentiation_study",
    "status": "STATIC_REVIEW_PASS_NATIVE_TESTS_PENDING",
    "base_commit": BASE,
    "base_tree": TREE,
    "reviewed_patches": EXPECTED_PATCHES,
    "files": verified,
    "support_sources_verified_against_exact_base_github_blob": supports,
    "mechanical_checks": {
        "all_candidate_original_sha256_and_git_blobs_match": True,
        "all_original_blobs_match_exact_base_github": True,
        "full_patch_forward_exact": True,
        "full_patch_inverse_exact": True,
        "token_budget_all_original_assertion_macros_unchanged": True,
        "token_budget_test_change_confined_to_private_completion_helper": True,
        "turn_state_change_confined_to_two_named_test_bodies": True,
        "websocket_records": state_results,
    },
    "token_budget_review": {
        "decision": "PASS",
        "metadata": "runtime.latest_call_tool forwards its fourth and fifth arguments as arguments and meta to latest_connections.call_tool. The stdio thread_hint schema is an empty object with additionalProperties=false and its handler reads context.meta['threadId']. Passing {} plus canonical threadId metadata corrects the observed missing-hint path.",
        "guard_retention": "The HeptaGovernance and active-tool-policy no-call guards, token-budget/context-window gates, environment=None, no-wait/default-timeout arguments, latest connection route, .ok() error handling, content extraction and context rendering remain byte-identical outside the three-line argument move/comment.",
        "finish_owner": "The private helper waits only after TurnComplete, passes that completed.turn_id to the existing observer and awaits its returned future after all registry locks are released. The observer filters TaskTerminalizationKind::Finish plus exact owner turn ID; it neither claims nor retires owners. The task publishes TurnComplete before persistence, marker release, pending work and finish completion. Both parameterized cases use this helper immediately before the next submit_turn.",
        "coverage_retained": "All existing compaction lifecycle, request count, window lineage, hidden-tool exposure, developer context and regex assertions remain unchanged. No deadline, feature, policy, production terminalizer, or retry changes.",
        "limits": "The closed compaction failures contain the generic ten-second event timeout, not a per-owner scheduling trace. The omitted finish observation is a source-proven reachable interleaving; native success remains unmeasured.",
    },
    "turn_state_review": {
        "decision": "PASS",
        "identity": "The original test's metadata assertions distinguish read-only prewarm from danger-full-access sampling; unchanged submit_turn explicitly selects PermissionProfile::Disabled. The exact source compatibility projection removes the prewarm phase and volatile turn lineage but retains sandbox and sandbox_mode, and WebsocketConnectionIdentity compares the serialized projection. The fixture must admit the resulting new connection.",
        "fixture_liveness": "The original server serially consumes one scripted connection before accepting another. Leaving the prewarm connection waiting for later sampling requests prevents accepting the identity-changing socket. Closing only the one-request prewarm script permits acceptance; the actual three-request sampling script remains open until explicit shutdown.",
        "within_turn": "The second test's original three response batches remain byte-token identical and all execute on connection index 1. Exact [1,3] plus unchanged [null,ts-1,ts-1] assertions still reject sampling reconnections and later metadata overriding the first state. The added first batch supplies only the otherwise missing generate=false prewarm response.",
        "across_turns": "The first test retains all four original response batches. Exact [1,3] proves first sampling, tool follow-up and next logical turn share the second physical connection. The original turn-state sequence, request_kind, generate, sandbox_mode and same/different turn-ID assertions remain unchanged after flattening the two connection logs.",
        "limits": "Closing the prewarm script can itself force reconnection, so [1,3] alone does not prove that production compatibility identity requires it. That requirement is separately supported by the unchanged projection and permission-selection source. These tests retain same-turn and cross-turn sampling connection coverage; they do not independently qualify prewarm reuse under identical permissions.",
    },
    "closed_failures": [{k: b[k] for k in ("name", "status", "elapsed", "log_byte_range")} for b in failure_blocks],
    "closed_review_sha256": identity(closed_bytes)["sha256"],
    "raw_log_sha256": closed["log_sha256"],
    "blockers": [],
    "execution": {"rust_build": "NOT_RUN", "rust_tests": "NOT_RUN", "rustfmt": "NOT_RUN", "native_source_modified": False, "candidate_sources_modified": False},
}
out = ROOT / "INDEPENDENT-REVIEW.json"
out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"report": str(out.relative_to(WORKSPACE)), **identity(out.read_bytes()), "decision": report["status"], "websocket_records": state_results}, indent=2))
