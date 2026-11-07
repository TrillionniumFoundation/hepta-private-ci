#!/usr/bin/env python3
"""Create the single reviewed editorial revision; never modify v1 or canonical."""
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREP = Path(__file__).resolve().parent
BEFORE = PREP / "final-candidate"
AFTER = PREP / "final-candidate-v2"


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def require(value, message):
    if not value:
        raise ValueError(message)


def main():
    require(not AFTER.exists(), "create-only final editorial candidate already exists")
    handoff_raw = (BEFORE / "HANDOFF-MANIFEST.json").read_bytes()
    require(pin(handoff_raw)["sha256"] == "3dc0baeaefa2f22cc7ffbeb99a7a30a5eb3224d275068599d0baa8b1612dc94b", "v1 handoff changed")
    manifest = json.loads(handoff_raw)
    pending = {}
    for row in manifest["files"]:
        raw = (BEFORE / row["path"]).read_bytes()
        require(pin(raw) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}, "v1 file changed")
        pending[row["path"]] = raw
    originals = dict(pending)
    canonical_before = {str(p): p.read_bytes() for p in
        (ROOT / "hepta-cell/qualification/cell-unification-20261106" / name for name in ("README.md", "STATUS.json", "SOURCE_IDENTITY.json"))}
    changes = []

    def replace(name, before, after, count):
        raw = pending[name]
        old, new = before.encode(), after.encode()
        require(raw.count(old) == count, "editorial anchor count changed: " + name)
        result = raw.replace(old, new)
        require(result.replace(new, old) == raw, "editorial inverse mismatch")
        pending[name] = result
        changes.append({"path": name, "before_literal": before, "after_literal": after,
                        "occurrences": count, "before": pin(raw), "after": pin(result)})

    replace("candidates/README.md", "源码来源与53个登记记录", "源码来源与受测53个登记记录", 1)
    replace("pr-guide-candidates/REVIEW-GUIDE.zh-CN.md",
            "最终 fix/fmt 及最终发布 SHA 验证仍待真实完成。",
            "最终 fix/fmt 已实际完成；最终发布 SHA 的 CI 验证仍待实际结果。", 1)
    replace("pr-guide-candidates/REVIEW-GUIDE.zh-CN.md", "固定 source53 链接",
            "固定 source54 链接并保留 tested source53 pins", 1)
    old_url = "https://github.com/TrillionniumFoundation/hepta-private-ci/blob/1e0910becc37383e6d17ecf861ea844fd07d8862/"
    new_url = "https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b5209cfdf509e990f10922197b32540bf8c353a7/"
    for name in ("PR-BODY.md", "PR-PARAGRAPHS.zh-CN.md"):
        replace("pr-guide-candidates/" + name, old_url, new_url, 4)
    changed = sorted(name for name in originals if pending[name] != originals[name])
    expected = ["candidates/README.md", "pr-guide-candidates/PR-BODY.md", "pr-guide-candidates/PR-PARAGRAPHS.zh-CN.md", "pr-guide-candidates/REVIEW-GUIDE.zh-CN.md"]
    require(changed == expected, "unexpected substantive file change")
    normalized = pending["candidates/README.md"].replace("源码来源与受测53个登记记录".encode(), "源码来源与53个登记记录".encode())
    require(normalized == originals["candidates/README.md"], "README change exceeded authorized historical label")
    for name in ("STATUS.json", "SOURCE_IDENTITY.json"):
        require(pending["candidates/" + name] == originals["candidates/" + name], "engineering/science values changed")
    pending["base/pre-editorial-correction/HANDOFF-MANIFEST.json"] = handoff_raw
    for name in [*changed, "GENERATION-READBACK.json", "INPUT-PINS.json",
                 "diffs/r30-closed-v2-to-final.patch", "diffs/checkpoint6-canonical-to-final.patch"]:
        pending["base/pre-editorial-correction/" + name] = originals[name]
    patch = "".join("".join(difflib.unified_diff(originals[name].decode().splitlines(keepends=True),
                    pending[name].decode().splitlines(keepends=True), fromfile="final-candidate/" + name,
                    tofile="final-candidate-v2/" + name)) for name in changed)
    pending["EDITORIAL-CORRECTION.patch"] = patch.encode()
    for label, directory in (("r30-closed-v2", "base/r30-closed-candidate-v2"),
                             ("checkpoint6-canonical", "base/checkpoint6-canonical")):
        full = "".join("".join(difflib.unified_diff(originals[directory + "/" + name].decode().splitlines(keepends=True),
                    pending["candidates/" + name].decode().splitlines(keepends=True), fromfile=label + "/" + name,
                    tofile="final-candidate/" + name)) for name in ("README.md", "STATUS.json", "SOURCE_IDENTITY.json"))
        pending["diffs/" + label + "-to-final.patch"] = full.encode()
    correction = {"schema": "hepta.final-report-editorial-correction.v1", "state": "FOUR_FILES_LITERAL_CORRECTION_ONLY",
        "parent_handoff": {"path": str((BEFORE / "HANDOFF-MANIFEST.json").relative_to(ROOT)), **pin(handoff_raw)},
        "authorizing_context": "Root accepted one historical count link-label clarification; independent review identified two GUIDE labels and current-code URLs in both short PR texts.",
        "changes": changes, "substantive_changed_paths": changed,
        "STATUS_and_SOURCE_IDENTITY_bytes_unchanged": True,
        "README_section2_full_bytes_exact_after_reversing_one_authorized_label": True,
        "science_taxonomy_Q24_content_and_historical_source52_README_links_unchanged": True,
        "all_gate_results_source_pins_path_groups_and_warning_values_unchanged": True,
        "original_v1_preserved": True, "canonical_modified": False, "native_or_Git_commands_executed": False}
    pending["EDITORIAL-CORRECTION.json"] = encode(correction)
    readback = json.loads(pending["GENERATION-READBACK.json"])
    readback["editorial_correction"] = {"path": "EDITORIAL-CORRECTION.json", **pin(pending["EDITORIAL-CORRECTION.json"])}
    readback["README_implementation_section_historical_label_only_correction"] = True
    readback["original_generation_proof"] = {"path": "base/pre-editorial-correction/GENERATION-READBACK.json", **pin(originals["GENERATION-READBACK.json"])}
    pending["GENERATION-READBACK.json"] = encode(readback)
    inputs = json.loads(pending["INPUT-PINS.json"])
    for path in [BEFORE / "HANDOFF-MANIFEST.json", Path(__file__).resolve(),
                 ROOT / "source54-final-report-independent-review/review-v1-complete-refs/INDEPENDENT-REVIEW.json"]:
        raw = path.read_bytes()
        inputs["files"].append({"path": str(path.relative_to(ROOT)), **pin(raw)})
    pending["INPUT-PINS.json"] = encode(inputs)
    pending["GENERATOR-EDITORIAL-CORRECTION.py"] = Path(__file__).read_bytes()
    for path, raw in canonical_before.items():
        require(Path(path).read_bytes() == raw, "canonical mutated")
    for name, raw in originals.items():
        require((BEFORE / name).read_bytes() == raw, "v1 mutated")
    files = [{"path": name, **pin(raw)} for name, raw in sorted(pending.items())]
    pending["HANDOFF-MANIFEST.json"] = encode({"schema": "hepta.final-report-candidate-handoff.v1", "files": files,
        "file_count_excluding_manifest": len(files), "candidate_only": True, "canonical_written": False,
        "science": "HOLD", "authority": "DENY_ALL", "editorial_revision": 2,
        "parent_handoff_sha256": pin(handoff_raw)["sha256"]})
    AFTER.mkdir()
    for name, raw in pending.items():
        path = AFTER / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    print(json.dumps({"candidate_directory": str(AFTER.relative_to(ROOT)), "files": len(pending),
                      "handoff": pin(pending["HANDOFF-MANIFEST.json"]), "correction": pin(pending["EDITORIAL-CORRECTION.json"]),
                      "substantive_changed_paths": changed, "canonical_adopted": False}, indent=2))


if __name__ == "__main__":
    main()
