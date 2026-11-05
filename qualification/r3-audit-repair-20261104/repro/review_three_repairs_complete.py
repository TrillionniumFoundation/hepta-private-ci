import base64
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CI = ROOT.parent / "ci-audit/recovered-20261105"


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "blob": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()}


def verify(data, expected):
    actual = identity(data)
    for key in ("bytes", "sha256"):
        assert actual[key] == expected[key], (key, actual, expected)
    if "git_blob" in expected:
        assert actual["blob"] == expected["git_blob"]
    return actual


def decode(directory, index_blob, expected_count):
    archive = CI / directory
    index_data = (archive / "archive.json").read_bytes()
    assert identity(index_data)["blob"] == index_blob
    index = json.loads(index_data)
    out = ROOT / "inputs" / (directory + "-root-decoded")
    out.mkdir(exist_ok=True)
    originals, assets, chunks_verified = {}, [], []

    def save(name, data):
        assert Path(name).name == name and name not in originals
        path = out / name
        if path.exists():
            assert path.read_bytes() == data
            return
        with path.open("xb") as f:
            for offset in range(0, len(data), 1_048_576):
                part = data[offset:offset + 1_048_576]
                assert f.write(part) == len(part)
        assert path.read_bytes() == data

    for asset in index["assets"]:
        chunks, offset = [], 0
        for chunk in asset["github_chunks"]:
            assert chunk["offset"] == offset
            data = Path(chunk["local_transport_file"]).read_bytes()
            if chunk.get("local_transport_added_final_newline"):
                assert data.endswith(b"\n")
                data = data[:-1]
            actual = verify(data, chunk)
            chunks_verified.append({"asset": asset["name"], "offset": offset, **actual})
            chunks.append(data)
            offset += len(data)
        transport = b"".join(chunks)
        verify(transport, {"bytes": asset["base64_bytes"], "sha256": asset["base64_sha256"]})
        compressed = base64.b64decode(transport, validate=True)
        verify(compressed, asset["gzip"])
        decoded = gzip.decompress(compressed)
        actual = verify(decoded, asset["original"])
        save(asset["name"], decoded)
        assets.append({"name": asset["name"], **actual})
        if asset["name"] == "complete-small-originals.json":
            for entry in json.loads(decoded)["files"]:
                data = entry["content"].encode()
                actual = verify(data, entry)
                save(entry["name"], data)
                originals[entry["name"]] = actual
        else:
            originals[asset["name"]] = actual
    assert len(originals) == index["original_unique_files_count"] == expected_count
    return index, out, {"index": identity(index_data), "assets": assets, "transport_chunks": chunks_verified,
                        "originals": [{"name": n, **v} for n, v in sorted(originals.items())],
                        "original_count": len(originals), "original_bytes": sum(v["bytes"] for v in originals.values())}


invalid, old, old_report = decode("skills-invalid-negative-compressed-archive", "90befbfd7def648605f5dda067939c9844457115", 36)
index, out, report = decode("three-repairs-v3-compressed-archive", "4a43c4f6422d4611e9c0abd55f91e51544f189a0", 171)


def read(name):
    return json.loads((out / name).read_bytes())


overlaps = []
for name in ["skills-v2-causal-original-nine-phase.json", "migration-causal-original166-phase.json",
             "v8-default-real-bazel-lock-phase.json", "v8-runtime-original76-terminal-phase.json"]:
    bundle = json.loads((CI / name).read_bytes())
    for entry in bundle["files"]:
        data = entry["content"].encode()
        assert (out / entry["name"]).read_bytes() == data
        overlaps.append({"bundle": name, "name": entry["name"]})
for entry in json.loads((CI / "skills-invalid-negative-original.json").read_bytes())["files"]:
    assert (old / entry["name"]).read_bytes() == entry["content"].encode()
assert not json.loads((old / "skills-causal-negative.json").read_bytes())["qualified"]
assert json.loads((old / "skills-negative-finally-restore.json").read_bytes())["restored_exact_positive"]
assert identity((out / "runner.py").read_bytes())["blob"] == index["runner"]
assert identity((out / "root-guard.json").read_bytes())["blob"] == index["manifest"]
execution_guard = (CI / "full18-three-repairs-v3-execution-guard.json").read_bytes()
assert identity(execution_guard)["blob"] == index["execution_guard"]
assert json.loads(execution_guard)["manifest"]["sha"] == index["manifest"]
assert identity((out / "terminal.json").read_bytes())["blob"] == index["complete_native_terminal"]
manifest = json.loads((CI / "full18-three-repairs-manifest-v3.json").read_bytes())
scopes, graphs, guarded = [], [], []
for scope in manifest["scopes"]:
    label = scope["label"]
    review = read(label + "-review.json")
    selection = read(label + "-selection.json")
    catalog = read(label + "-catalog.stdout")
    selected, ignored, unmatched = [], [], []
    for binary, suite in catalog["rust-suites"].items():
        for name, item in suite["testcases"].items():
            pair = (binary, name)
            if item["filter-match"]["status"] == "matches" and not item["ignored"]:
                selected.append(pair)
            elif item["ignored"]:
                ignored.append(pair)
            else:
                unmatched.append(pair)
    assert sorted(selected) == sorted((x["classname"], x["name"]) for x in scope["expected_cases"])
    assert sorted(selected) == sorted((x["classname"], x["name"]) for x in selection["selected"])
    assert len(ignored) == review["original_ignored_count"] == 0
    assert len(unmatched) == review["filter_unmatched_count"]
    assert selection["programs_after_catalog_before_just"] == review["programs_before"]
    assert selection["catalog_helpers_after_catalog_before_just"] == review["helpers_before"] == []
    metadata = read(label + "-metadata.stdout")
    graph = {"members": sorted(metadata["workspace_members"]),
             "nodes": sorted(metadata["resolve"]["nodes"], key=lambda x: x["id"])}
    assert len(graph["members"]) == 193 and len(graph["nodes"]) == 1501
    graphs.append((label, graph))
    phases = []
    for suffix in ["-metadata", "-catalog", ""]:
        command = read(label + suffix + "-command.json")
        status = read(label + suffix + "-status.json")
        assert command["attempt"] == 1 and command["argv"] == status["argv"]
        assert command["source"] == status["source_before"] == status["source_after"] == review["source"]
        assert status["exit_code"] == (review["exit_code"] if not suffix else 0)
        if not suffix:
            assert command["argv"][:2] == ["just", "test"]
            assert "--locked" in command["argv"] and "--no-tests" in command["argv"]
            assert command["argv"][command["argv"].index("--retries") + 1] == "0"
        phases.append({"name": label + suffix, "argv": command["argv"], "source": command["source"],
                       "exit_code": status["exit_code"], "seconds": status["duration_seconds"]})
    scopes.append({"name": label, "selected": len(selected), "ignored": len(ignored),
                   "unmatched": len(unmatched), "programs": len(review["programs_before"]), "phases": phases})
assert all(g == graphs[0][1] for _, g in graphs[1:4])
first_nodes = {n["id"]: n for n in graphs[0][1]["nodes"]}
last_nodes = {n["id"]: n for n in graphs[-1][1]["nodes"]}
assert first_nodes.keys() == last_nodes.keys() and graphs[0][1]["members"] == graphs[-1][1]["members"]
graph_changes = [{"id": k, "before": first_nodes[k], "after": last_nodes[k]} for k in first_nodes if first_nodes[k] != last_nodes[k]]
assert len(graph_changes) == 1 and "codex-v8-poc" in graph_changes[0]["id"]
for key in set(graph_changes[0]["before"]) | set(graph_changes[0]["after"]):
    if key != "features":
        assert graph_changes[0]["before"][key] == graph_changes[0]["after"][key]
assert set(graph_changes[0]["after"]["features"]) - set(graph_changes[0]["before"]["features"]) == {"default", "sandbox"}
for path in out.glob("*-source-guard.json"):
    guard = json.loads(path.read_bytes())
    assert guard["expected_source"] == guard["actual_source"]
    assert guard["head"] == "cabcb40d36e116beaa65750e1f674c52035da785"
    assert guard["ordinary_index"]["sha256"] == "8ccf08bcd5b633a38fa81be4814ae264365f1a2cdd1ed81e1633fbcc0ac31502"
    assert guard["locks"]["codex-rs/Cargo.lock"]["sha256"] == "4a7a5535cf045089458468411e126b5f59bc6bbf34fc0deead9b0c1b8d84000a"
    assert guard["locks"]["MODULE.bazel.lock"]["sha256"] == "11f8a421224b9b05f32c4c14054e8868083d989fc497310c8d51e1156f189ca3"
    assert guard["untracked_source_paths"] == []
    sequence_number = int(path.name.split("-", 1)[0])
    expected_allowed = ["user.bazelrc"] if 40 <= sequence_number <= 46 else []
    assert guard["allowed_untracked_source_paths"] == expected_allowed
    guarded.append({"name": path.name, "source": guard["actual_source"]})
assert len(guarded) == 54
report.update({"schema": "hepta.root.three-repairs-complete-originals-review.v1",
               "observed_at_utc": datetime.now(timezone.utc).isoformat(),
               "status": "ALL_171_VALID_ATTEMPT_AND_36_INVALID_ATTEMPT_ORIGINALS_STRICTLY_RECONSTRUCTED",
               "previous_invalid_attempt": old_report, "all_small_bundle_overlaps_exact": overlaps,
               "verifier_schema_correction": "Initial verifier incorrectly equated the native root-guard.json with the separate execution-authorization object. Actual native file is the exact manifest c09347f; execution guard f9e355 is separately hash-checked and binds that manifest. Catalog selection field names follow the actual serialized schema. Guards40–46 explicitly permit only the previously reviewed task-owned user.bazelrc during actual lock generation/check/shutdown; actual untracked source lists remain empty, and the independent semantic review verifies exact task-config removal. No source, original receipt, test oracle or candidate changed.",
               "all_scoped_catalogs_and_commands_match": scopes,
               "full_graphs": {"members": 193, "nodes": 1501, "first_four_graphs_equal": True,
                               "v8_actual_graph_changes": graph_changes},
               "all_54_exact_source_guards": sorted(guarded, key=lambda x: int(x["name"].split("-", 1)[0])),
               "prior_semantic_root_review": "1504d23acdb8fc5076d4216ee693b220d9c44391",
               "qualification_limit": "Complete original receipt transport verified; scoped9/166/76 pass only. First invalid fixture attempt remains invalid. No whole-workspace or final-head hosted CI claim.",
               "all_original_blockers_closed": False})
destination = ROOT / "deliverables/fourth-three-repairs-complete-root-review.json"
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({"path": str(destination), **identity(destination.read_bytes()),
                  "originals": report["original_count"], "prior_invalid_originals": old_report["original_count"],
                  "raw_bytes": report["original_bytes"], "guards": len(guarded), "graph_changes": graph_changes}))
