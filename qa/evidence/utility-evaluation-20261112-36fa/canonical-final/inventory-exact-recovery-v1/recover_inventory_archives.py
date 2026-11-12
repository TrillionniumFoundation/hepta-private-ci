#!/usr/bin/env python3
"""Reproduce two observed canonical-alignment inventory archives offline.

No source checkout, Git command, H process, gate, or native driver is used.
Only exact known JSON bytes are compressed and checked against actual RESULT
identities. A mismatch fails recovery; no replacement or normalization is tried.
"""
import argparse
import ast
import base64
import gzip
import hashlib
import json
from pathlib import Path
import platform
import zlib

RESULT_PIN = {
    "bytes": 368586,
    "sha256": "33cd2a23b1bd4a4b7b8ec5d41b5658d3149d701e7096cea00aee6f5d9f2f82c7",
    "git_blob": "2678be6c23d00696d356e988120887a61f88bfab",
}
DRIVER_PIN = {
    "bytes": 46094,
    "sha256": "6fa25f21dce6aa93dc17b0f490107e767676df44c42d6b2c564def1cba7c4bb2",
    "git_blob": "765ada67a33f4d9aeaf29c9c522898057083cafb",
}
ACTUAL_JOB = "1a1d1ddc8e4-2564-1c83"
PREFIX = "qa/evidence/utility-evaluation-20261112-36fa/canonical-final/inventory-exact-recovery-v1"
PART = 262144

def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}

def check(ok, explanation):
    if not ok:
        raise ValueError(explanation)

def check_pin(raw, expected, explanation):
    check(all(expected.get(k) == v for k, v in pin(raw).items()), explanation)

def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()

def write(root, name, raw):
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(raw)
    check(target.read_bytes() == raw, "local recovery write mismatch")
    return {"relative_path": name, "local": str(target), **pin(raw)}

def recover(result_raw, before_raw, final_raw, driver_raw, prior, out):
    check_pin(result_raw, RESULT_PIN, "exact original RESULT differs")
    check_pin(driver_raw, DRIVER_PIN, "exact original gzrecord source differs")
    result = json.loads(result_raw)
    check(result["format"] == "hepta-final-canonical-alignment-result-v1"
          and result["status"] == "CANONICAL_SOURCE_ALIGNED_CLEAN_ONLY",
          "successful actual canonical-alignment RESULT required")
    original_text = driver_raw.decode()
    gzrecord_text = next(ast.get_source_segment(original_text, node)
                         for node in ast.parse(original_text).body
                         if isinstance(node, ast.FunctionDef) and node.name == "gzrecord")
    check("gzip.compress(raw,mtime=0)" in gzrecord_text
          and "range(0,len(gz),262144)" in gzrecord_text
          and "base64.b64encode(block)+b'\\n'" in gzrecord_text,
          "original compression/part recipe differs")
    all_artifacts = result["artifacts"]
    artifacts = {row["name"]: row for row in all_artifacts}
    check(len(artifacts) == len(all_artifacts), "unique actual artifact names required")
    prior_by_blob = {}
    for row in prior["files"]:
        prior_by_blob.setdefault(row["git_blob"], []).append(row)
    out.mkdir(parents=True, exist_ok=False)
    records, published_files = [], []
    for label, raw in (("before", before_raw), ("final", final_raw)):
        base = "SOURCE." + label + ".inventory.json"
        observed = artifacts[base + ".gz"]
        raw_expected = {"bytes": observed["raw_bytes"],
                        "sha256": observed["raw_sha256"],
                        "git_blob": observed["raw_git_blob"]}
        check_pin(raw, raw_expected, label + " raw identity differs")
        state = result["before" if label == "before" else "after"]
        check_pin(raw, state["inventory"], label + " actual source inventory differs")
        parsed = json.loads(raw)
        check(parsed["tracked_entries"] == parsed["filesystem_entries"] == 15188,
              "complete observed membership differs")
        check(parsed["source"]["head"] == state["commit"]
              and parsed["source"]["tree"] == state["tree"],
              "actual source identity differs")
        write(out, "recovered/" + base, raw)
        # Exact original 765ada recipe, unchanged.
        packed = gzip.compress(raw, mtime=0)
        check(gzip.decompress(packed) == raw, "gzip roundtrip differs")
        check_pin(packed, observed, label + " gzip identity differs")
        write(out, "recovered/" + base + ".gz", packed)
        parts = []
        for number, offset in enumerate(range(0, len(packed), PART), 1):
            block = packed[offset:offset + PART]
            text = base64.b64encode(block) + b"\n"
            name = base + ".gz.part-%03d.b64" % number
            expected = observed["parts"][number - 1]
            check(expected["name"] == name and artifacts[name] == expected,
                  "nested/standalone actual part metadata differs")
            check_pin(text, expected, name + " exact base64 identity differs")
            check(expected["decoded_offset"] == offset
                  and expected["decoded_bytes"] == len(block)
                  and expected["decoded_sha256"] == hashlib.sha256(block).hexdigest(),
                  name + " decoded identity differs")
            check(base64.b64decode(text[:-1], validate=True) == block,
                  "exact original base64 roundtrip differs")
            item = write(out, "recovered/" + name, text)
            item.update(kind="exact_recovered_original_base64_part",
                        original_artifact_name=name,
                        decoded_offset=offset, decoded_bytes=len(block),
                        decoded_sha256=hashlib.sha256(block).hexdigest(),
                        actual_result_pins_all_equal=True)
            if label == "before":
                same = prior_by_blob.get(item["git_blob"], [])
                check(same, "expected prior before-inventory part absent")
                check(any(row.get("full_github_readback_equal") is True for row in same),
                      "prior part lacks full GitHub readback provenance")
                old = next(row for row in same if row.get("full_github_readback_equal") is True)
                check_pin(Path(old["local"]).read_bytes(), item,
                          "prior exact-recovered part local identity differs")
                check(Path(old["local"]).read_bytes() == text, "prior part bytes differ")
                item.update(reuse_existing_blob=True, reuse_existing_path=old["path"],
                            reuse_existing_local=old["local"])
            else:
                item.update(reuse_existing_blob=False)
            published_files.append(item)
            parts.append({k: item[k] for k in (
                "relative_path", "original_artifact_name", "bytes", "sha256", "git_blob",
                "decoded_offset", "decoded_bytes", "decoded_sha256", "reuse_existing_blob")})
        check(len(parts) == len(observed["parts"]), "part count differs")
        joined = b"".join(base64.b64decode((out / p["relative_path"]).read_bytes()[:-1],
                                         validate=True) for p in parts)
        check(joined == packed and gzip.decompress(joined) == raw,
              "ordered published parts do not reconstruct original bytes")
        records.append({
            "record": base, "raw": pin(raw), "gzip": pin(packed), "parts": parts,
            "all_raw_gzip_part_pins_equal_actual_result": True,
            "actual_head": parsed["source"]["head"],
            "actual_index_tree": parsed["source"]["tree"],
            "actual_status_empty": parsed["source"]["status"] == "",
            "tracked_entries": parsed["tracked_entries"],
            "filesystem_entries": parsed["filesystem_entries"],
        })
    before, after = json.loads(before_raw), json.loads(final_raw)
    physical = ("path", "kind", "permissions", "bytes", "sha256", "working_blob", "stable")
    bmap = {row["path"]: {k: row[k] for k in physical} for row in before["files"]}
    amap = {row["path"]: {k: row[k] for k in physical} for row in after["files"]}
    check(bmap == amap and len(amap) == 15188,
          "physical source bytes/modes changed between recovered observations")
    report = {
        "format": "hepta-canonical-full-inventory-exact-recovery-review-v1",
        "status": "EXACT_RECOVERY_MATCHED_ACTUAL_RAW_GZIP_AND_ALL_PART_PINS",
        "actual_job": ACTUAL_JOB, "actual_result": RESULT_PIN,
        "original_driver": DRIVER_PIN,
        "algorithm": "Original gzrecord: gzip.compress(raw,mtime=0); 262144-byte gzip chunks; base64.b64encode(chunk)+one LF. No JSON reserialization or gzip/header correction.",
        "runtime": {"python": platform.python_version(), "zlib": zlib.ZLIB_VERSION,
                    "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION},
        "records": records,
        "source_physical_fields_equal": list(physical),
        "all_15188_physical_rows_equal": True,
        "source_before": {"head": result["before"]["commit"], "index_tree": result["before"]["tree"],
                          "inventory": records[0]["raw"]},
        "source_after": {"head": result["after"]["commit"], "index_tree": result["after"]["tree"],
                         "parents": result["after"]["parents"], "inventory": records[1]["raw"]},
        "reuse": "The five before parts exactly equal prior finalfmt final.inventory parts. Reuse those existing immutable Git blobs; only five final-inventory parts need new creation.",
        "after_provenance": "The file named CANONICAL_CLEAN_INVENTORY.expected.json was initially a projection. Its entire bytes now match the actual canonical RESULT raw/gzip/all-part identities. This supports exact recovery of that original observation, not a second H read.",
        "not_claimed": [
            "No new H/native/source/gate/test/main execution.",
            "No physical source or Git index/config/ref modification.",
            "No native compact snapshot was actually observed here; the earlier compact hash remains a projection until the original native runner reads it.",
            "No raw Git index, stat extension or Git metadata archive was reconstructed from incomplete data or hashes.",
            "No source/behavioral gate or real authorized A/T/B/C iteration PASS is inferred.",
        ],
        "native_or_H_calls": 0, "source_checkout_reads_or_writes": 0,
        "recovered_index_or_stat_archives": 0, "qualification": False,
    }
    excerpt = ("Original source: " + DRIVER_PIN["git_blob"] + "\n\n" + gzrecord_text + "\n").encode()
    extra = write(out, "ORIGINAL_GZRECORD.txt", excerpt)
    extra["kind"] = "verbatim_original_serializer_excerpt"
    published_files.append(extra)
    extra = write(out, "RECOVERY_REVIEW.json", json_bytes(report))
    extra["kind"] = "derived_exact_recovery_report"
    published_files.append(extra)
    source = Path(__file__).read_bytes()
    extra = write(out, "recover_inventory_archives.py", source)
    extra["kind"] = "pure_offline_recovery_script"
    published_files.append(extra)
    manifest = {
        "format": "hepta-canonical-full-inventory-exact-recovery-manifest-v1",
        "status": report["status"], "actual_job": ACTUAL_JOB,
        "actual_result": RESULT_PIN,
        "evidence_prefix": PREFIX, "files": published_files, "records": records,
        "unique_base64_blobs": len({r["git_blob"] for r in published_files
                                   if r["kind"] == "exact_recovered_original_base64_part"}),
        "reused_base64_blobs": 5, "new_base64_blobs": 5,
        "large_raw_and_gzip_not_uploaded": True,
        "reconstruction": "Read each record's parts in decoded_offset order; remove their one final LF and strictly base64-decode; concatenate; verify the complete gzip triple; decompress and verify the raw triple. Exact names are aliases to original content identities.",
        "not_second_native_read": True, "native_compact_actual_observed": False,
        "index_metadata_stat_recovery": "Not attempted: original bytes not supplied; native retains that separate evidence.",
        "qualification": False,
    }
    write(out, "MANIFEST.json", json_bytes(manifest))
    return manifest

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--result", type=Path, required=True)
    p.add_argument("--before", type=Path, required=True)
    p.add_argument("--final", type=Path, required=True)
    p.add_argument("--original-driver", type=Path, required=True)
    p.add_argument("--prior-placement", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    m = recover(a.result.read_bytes(), a.before.read_bytes(), a.final.read_bytes(),
                a.original_driver.read_bytes(), json.loads(a.prior_placement.read_bytes()),
                a.output_dir)
    print(json.dumps({"status": m["status"], "records": len(m["records"]),
                      "base64_parts": m["unique_base64_blobs"], "reused": 5, "new": 5,
                      "manifest": pin((a.output_dir / "MANIFEST.json").read_bytes())},
                     sort_keys=True))

