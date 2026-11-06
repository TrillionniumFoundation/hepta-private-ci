import base64
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT.parent / "ci-audit/recovered-20261105/app-epoch2-compressed-archive"
OUT = ROOT / "inputs/app-epoch2-complete-root-decoded"
OUT.mkdir(exist_ok=False)


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "blob": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()}


def verify(data, expected):
    rec = identity(data)
    for key in ("bytes", "sha256"):
        assert rec[key] == expected[key], (key, rec, expected)
    if "git_blob" in expected:
        assert rec["blob"] == expected["git_blob"]
    return rec


def write_reopen(name, data):
    assert Path(name).name == name
    path = OUT / name
    with path.open("xb") as stream:
        for offset in range(0, len(data), 1_048_576):
            part = data[offset:offset + 1_048_576]
            assert stream.write(part) == len(part)
    assert path.read_bytes() == data


index_bytes = (ARCHIVE / "archive.json").read_bytes()
assert identity(index_bytes)["blob"] == "777b62b813b3dfe366c551b9f6c42b4f82e311ba"
index = json.loads(index_bytes)
assets = []
all_originals = {}
parts = []
for asset in index["assets"]:
    chunks = []
    offset = 0
    for entry in asset["github_chunks"]:
        assert entry["offset"] == offset
        data = Path(entry["local_transport_file"]).read_bytes()
        assert entry["local_transport_added_final_newline"] and data.endswith(b"\n")
        data = data[:-1]
        info = verify(data, entry)
        chunks.append(data)
        parts.append({"asset": asset["name"], "offset": offset, **info})
        offset += len(data)
    transport = b"".join(chunks)
    verify(transport, {"bytes": asset["base64_bytes"], "sha256": asset["base64_sha256"]})
    compressed = base64.b64decode(transport, validate=True)
    verify(compressed, asset["gzip"])
    decoded = gzip.decompress(compressed)
    info = verify(decoded, asset["original"])
    write_reopen(asset["name"], decoded)
    assets.append({"name": asset["name"], "original": info,
                   "gzip": identity(compressed), "chunks": len(chunks)})
    if asset["name"] == "complete-small-originals.json":
        wrapper = json.loads(decoded)
        for entry in wrapper["files"]:
            data = entry["content"].encode()
            rec = verify(data, entry)
            write_reopen(entry["name"], data)
            assert entry["name"] not in all_originals
            all_originals[entry["name"]] = rec
    else:
        assert asset["name"] not in all_originals
        all_originals[asset["name"]] = info
assert len(all_originals) == index["original_unique_files_count"] == 38


def read(name):
    return json.loads((OUT / name).read_bytes())


terminal = read("terminal.json")
for name in all_originals:
    short = ROOT / "inputs/app-epoch2-decoded" / name
    if short.exists():
        assert short.read_bytes() == (OUT / name).read_bytes()
source = "f8251e1d14fa8524ab469281296cd4cf708f173c"
assert terminal["source"] == source
assert terminal["cases"][0]["result"] == "FAIL"
assert terminal["cases"][0]["seconds"] == "5.491"
assert terminal["original_just_exit"] == 100 and terminal["retries"] == 0
assert terminal["programs_before"] == terminal["programs_after"]
assert terminal["helpers_before"] == terminal["helpers_after"]
assert len(terminal["helpers_before"]) == 33
selection = read("selection.json")
catalog = read("app-disconnect-full-context-catalog.stdout")
selected, ignored, unmatched = [], [], []
for suite_id, suite in catalog["rust-suites"].items():
    for name, item in suite["testcases"].items():
        entry = {"classname": suite_id, "name": name, "package": suite["package-name"],
                 "ignored": item["ignored"], "filter_match": item["filter-match"]}
        if item["filter-match"]["status"] == "matches" and not item["ignored"]:
            selected.append(entry)
        elif item["ignored"]:
            ignored.append(entry)
        else:
            unmatched.append(entry)
assert selected == selection["selected"]
assert ignored == selection["original_ignored"]
assert unmatched == selection["filter_unmatched"]
assert (len(selected), len(ignored), len(unmatched)) == (1, 56, 19502)
assert selection["test_programs_after_catalog_before_just"] == terminal["programs_before"]
assert selection["helpers_after_catalog_before_just"] == terminal["helpers_before"]
metadata = read("workspace-metadata.stdout")
old_metadata_path = ROOT / "inputs/f825-root-decoded/full-workspace-metadata-stdout.original"
old_metadata_bytes = old_metadata_path.read_bytes()
assert identity(old_metadata_bytes)["sha256"] == "959b827393fc6830e8fd6c55a83a519217ab0debb7c033b42e64306bc373fece"


def graph(value):
    return {"workspace_members": sorted(value["workspace_members"]),
            "nodes": sorted(({"id": n["id"], "features": sorted(n["features"]),
                              "deps": n.get("deps", [])} for n in value["resolve"]["nodes"]),
                            key=lambda n: n["id"])}


assert graph(metadata) == graph(json.loads(old_metadata_bytes))
assert len(metadata["workspace_members"]) == 193 and len(metadata["resolve"]["nodes"]) == 1501
compiler = [json.loads(line) for line in (OUT / "normal-six-helper-build-epoch2.stdout").read_bytes().splitlines() if line.strip()]
assert len(compiler) == 1313
assert [x for x in compiler if x.get("reason") == "build-finished"] == [{"reason": "build-finished", "success": True}]
helper_receipt = read("normal-six-helper-build-epoch2-receipt.json")
assert len(helper_receipt["artifacts"]) == 6
for artifact in helper_receipt["artifacts"]:
    matches = [x for x in compiler if x.get("reason") == "compiler-artifact" and x.get("executable") == artifact["path"]]
    assert len(matches) == 1
    for key in ("package_id", "target", "profile", "features", "fresh"):
        assert matches[0][key] == artifact[key]
phases = []
for phase in ("normal-six-helper-build-epoch2", "workspace-metadata", "app-disconnect-full-context-catalog", "app-disconnect-original-diagnostic"):
    status = read(phase + "-status.json")
    command = read(phase + "-command.json")
    assert status["source_before"] == status["source_after"] == command["source"] == source
    assert status["argv"] == command["argv"] and command["attempt"] == 1
    expected_exit = 100 if phase == "app-disconnect-original-diagnostic" else 0
    assert status["exit_code"] == expected_exit
    phases.append({"phase": phase, "argv": status["argv"], "exit_code": status["exit_code"],
                   "started_at": status["started_at"], "completed_at": status["completed_at"],
                   "duration_seconds": status["duration_seconds"]})
guards = []
for name in all_originals:
    if name.endswith("-untracked-source-paths.json"):
        guard = read(name)
        assert guard["paths"] == [] and guard["allowed_paths"] == []
        guards.append(name)
assert len(guards) == 10
report = {
    "schema": "hepta.root.app-epoch2-complete-provenance-review.v1",
    "observed_at_utc": datetime.now(timezone.utc).isoformat(),
    "status": "ALL_38_ORIGINALS_STRICTLY_DECODED_REOPENED_ORIGINAL_CASE_FAILED",
    "archive_index": identity(index_bytes), "native_job": index["native_original_job"],
    "source_tree": source, "transport_chunks": parts, "assets": assets,
    "complete_unique_originals": [{"name": name, **info} for name, info in sorted(all_originals.items())],
    "complete_unique_original_count": len(all_originals),
    "complete_unique_original_bytes": sum(x["bytes"] for x in all_originals.values()),
    "small_bundle_overlap_all_nine_byteequal": True,
    "full_metadata": {"workspace_members": 193, "resolved_nodes": 1501,
                      "every_node_feature_and_dependency_equals_original_full": True,
                      "original": identity(old_metadata_bytes), "current": all_originals["workspace-metadata.stdout"]},
    "fresh_catalog_selection": {"selected": 1, "original_ignored": 56, "filter_unmatched": 19502,
                                "all_original_names_reconstructed_exactly": True,
                                "selected_programs": 1, "helper_roster": 33},
    "compiler_json_messages": 1313, "normal_helper_artifacts": 6,
    "all_helper_artifact_package_target_profile_features_fresh_fields_match_original_compiler": True,
    "all_program_and_helper_identities_stable": True, "all_ten_untracked_guards_empty": guards,
    "phases": phases, "original_case": terminal["cases"][0],
    "prior_root_terminal_review": "8193af8734c08219fc9bb5b70fdd8c1c3ce2a3de",
    "interpretation_zh": "完整编译/graph/catalog/selection/source guard 原件现已独立复核，补足前一份9文件回执的运输限制。原App断连仍FAIL，未产生修复PASS；本完整包不含之后临时观测源码epoch的结果。",
    "all_original_blockers_closed": False,
}
destination = ROOT / "deliverables/fourth-app-epoch2-complete-root-review.json"
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"path": str(destination), **identity(destination.read_bytes()),
                  "original_count": len(all_originals), "original_bytes": report["complete_unique_original_bytes"],
                  "catalog_counts": [len(selected), len(ignored), len(unmatched)], "chunks": len(parts)}))
