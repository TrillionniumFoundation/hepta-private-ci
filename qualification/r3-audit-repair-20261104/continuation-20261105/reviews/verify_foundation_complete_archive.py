"""Independently reconstruct the complete Foundation archive, without native calls."""
from pathlib import Path
import base64
import collections
import gzip
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "ci-audit/recovered-20261105/b16-ai395-foundation-v7-v2"
ARCHIVE = BASE / "complete-archive"


def ident(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def matches(raw, expected):
    got = ident(raw)
    for key in got:
        if key in expected:
            assert got[key] == expected[key], (key, got[key], expected[key])
    return got


def verify():
    manifest_bytes = (ARCHIVE / "archive-manifest.json").read_bytes()
    assert ident(manifest_bytes)["git_blob"] == "4f65590b3d208854fa90ec5864f7b27fff61d31a"
    manifest = json.loads(manifest_bytes)
    delivery = json.loads((ARCHIVE / "git-delivery-map.json").read_bytes())
    assert delivery["all_created_and_read_back"] is True
    for row in delivery["files"]:
        assert row["actual_create"] is True and row["actual_get_equal"] is True
        matches((ROOT / row["path"]).read_bytes(), row)

    batches = []
    for row in manifest["batches"]:
        raw = Path(row["path"]).read_bytes()
        matches(raw, row)
        batches.append(json.loads(raw))
    expected_chunk_locations = set()
    assets = {}
    native_origins = {}
    for asset in manifest["assets"]:
        raw_id = asset["raw_identity"]
        sha = raw_id["sha256"]
        assert sha not in assets
        compressed = bytearray()
        for number, chunk in enumerate(asset["chunks"]):
            location = chunk["location"]
            pair = (location["batch"], location["item"])
            assert pair not in expected_chunk_locations
            expected_chunk_locations.add(pair)
            source = batches[pair[0]]["chunks"][pair[1]]
            assert {k: v for k, v in source.items() if k != "base64"} == {
                k: v for k, v in chunk.items() if k != "location"}
            assert source["asset_sha256"] == sha and source["chunk_index"] == number
            assert source["offset"] == len(compressed)
            decoded = base64.b64decode(source["base64"], validate=True)
            matches(decoded, source)
            compressed.extend(decoded)
        matches(compressed, asset["gzip_identity"])
        assert bytes(compressed[4:8]) == b"\0\0\0\0"
        raw = gzip.decompress(compressed)  # checks the original gzip trailer and CRC
        matches(raw, raw_id)
        assets[sha] = raw
        for origin in asset["origins"]:
            if origin["kind"] == "native-export-index":
                path = origin["path"]
                assert path not in native_origins
                native_origins[path] = sha
    assert expected_chunk_locations == {
        (batch_number, chunk_number)
        for batch_number, batch in enumerate(batches)
        for chunk_number in range(len(batch["chunks"]))}
    assert len(assets) == manifest["assets_including_outer_receipts_and_derived_verification"] == 341

    index_bytes = (BASE / "terminal-originals/complete-evidence-index.json").read_bytes()
    matches(index_bytes, manifest["original_export_index"])
    index = json.loads(index_bytes)
    original_files = index["files"]
    assert {r["path"]: r["sha256"] for r in original_files} == native_origins
    assert len(original_files) == 352
    for row in original_files:
        matches(assets[row["sha256"]], row)
    totals = {"files": len(original_files), "bytes": sum(r["bytes"] for r in original_files),
              "unique_contents": len(set(native_origins.values())),
              "unique_bytes": sum(len(assets[s]) for s in set(native_origins.values()))}
    assert totals == manifest["native_index_originals"]

    crosscheck = json.loads(assets[manifest["crosscheck"]["sha256"]])
    epoch_raw = (BASE / "terminal-originals/epoch-terminal.json").read_bytes()
    assert assets[ident(epoch_raw)["sha256"]] == epoch_raw
    epoch = json.loads(epoch_raw)
    assert epoch["status"] == "QUALIFIED" and epoch["error"] is None
    assert epoch["final_guard"] is True and epoch["post_hygiene_tests_run"] is False
    assert epoch["final_tree"] == "e510f685d2aa7b9a7121a78f96af3569919e6f88"
    guard_trees = collections.Counter()
    for row in crosscheck["source_guards"]:
        guard = json.loads(assets[native_origins[row["path"]]])
        assert guard["expected_tree"] == guard["actual_tree"] == row["tree"]
        assert guard["head"] == epoch["ordinary_head"]
        assert guard["untracked"] == []
        for key in ("bytes", "sha256"):
            assert guard["ordinary_index"][key] == epoch["ordinary_index"][key]
        for name, lock in guard["locks"].items():
            for key in ("bytes", "sha256"):
                assert lock[key] == epoch["locks"][name][key]
        guard_trees[guard["actual_tree"]] += 1
    assert sum(guard_trees.values()) == crosscheck["source_guard_count"] == 116
    return {"schema": "hepta-root-foundation-complete-archive-review-v1",
            "native_job": manifest["native_job"], "manifest": ident(manifest_bytes),
            "delivery_map": ident((ARCHIVE / "git-delivery-map.json").read_bytes()),
            "native_originals": totals, "assets_reconstructed": len(assets),
            "transport_batches": len(batches), "transport_chunks": len(expected_chunk_locations),
            "all_batch_and_chunk_and_gzip_and_original_hashes_verified": True,
            "all_native_paths_accounted_exactly_once": True,
            "source_guards_reconstructed_and_verified": 116,
            "source_guard_trees": dict(sorted(guard_trees.items())),
            "epoch_status": epoch["status"], "epoch_final_tree": epoch["final_tree"],
            "epoch_original_receipt": ident(epoch_raw),
            "native_commands_started": 0, "source_or_original_evidence_modified": False,
            "scope": "Complete bytes for the existing Foundation selected scopes only; the phase review separately verifies exact tests and original negative oracles.",
            "driver_execution_outcome": "UNKNOWN",
            "driver_pool_or_cross_platform_qualification_inferred": False}


if __name__ == "__main__":
    review = verify()
    target = ROOT / "hepta-audit-fifth/inputs/foundation-complete-archive-root-review.json"
    target.write_text(json.dumps(review, indent=2) + "\n")
    print(json.dumps({"result": "PASS", "review": str(target), **ident(target.read_bytes()),
                      "native_originals": review["native_originals"],
                      "assets": review["assets_reconstructed"],
                      "source_guards": review["source_guards_reconstructed_and_verified"]}))
