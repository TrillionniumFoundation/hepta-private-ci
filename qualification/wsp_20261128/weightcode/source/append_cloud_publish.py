"""Append public completed cloud evidence without rewriting frozen CPU results."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEST = HERE / "publish/weightcode"
CLOUD = HERE / "cloud_scan"
CHUNK = 450_000
ORIGINAL_CPU_MANIFEST = "6aa1ce0986282b424fcd985f70bb1cb1ffdd4cf3dfb03d758a1725853beecd7e"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as f:
        f.write(json.dumps(obj, indent=2, allow_nan=False)+"\n")


def put(relative, data):
    path = DEST / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(data) <= CHUNK:
        with path.open("xb") as f:
            f.write(data)
        return {"path": relative, "bytes": len(data), "sha256": sha(data)}
    parts = []
    for i, start in enumerate(range(0, len(data), CHUNK)):
        name = relative+f".part{i:03d}"
        block = data[start:start+CHUNK]
        with (DEST / name).open("xb") as f:
            f.write(block)
        parts.append({"path": name, "bytes": len(block), "sha256": sha(block)})
    result = {"reconstructed_path": relative, "bytes": len(data), "sha256": sha(data), "parts": parts,
              "reconstruction": "Concatenate listed parts, verify full SHA before unpacking"}
    save(DEST / (relative+".manifest.json"), result)
    return result


def main():
    old_raw = (DEST / "PACKAGE_MANIFEST.json").read_bytes()
    assert sha(old_raw) == ORIGINAL_CPU_MANIFEST
    old = json.loads(old_raw)
    for rec in old["files"]:
        path = DEST / rec["path"]
        assert path.stat().st_size == rec["bytes"] and sha(path.read_bytes()) == rec["sha256"]
    audit = json.loads((CLOUD / "INDEPENDENT_AUDIT.json").read_text())
    assert audit["fixed_configuration_completed"] and audit["audit_cost"]["new_network_forwards"] == 0
    root1 = CLOUD / "chunk01/unpacked/weightcode_rule_to_data"
    root2 = CLOUD / "chunk02/unpacked/weightcode_rule_to_data"
    put("CPU_PACKAGE_MANIFEST.json", old_raw)
    mappings = [("INDEPENDENT_AUDIT.json", "results/cloud/independent_audit.json"),
                ("HEPTARUNTIME_CLOUD_RECEIPT.json", "results/cloud/heptaruntime_receipt.json"),
                ("chunk01/result.json", "results/cloud/chunk01_result.json"),
                ("chunk02/result.json", "results/cloud/chunk02_result.json"),
                ("chunk01/artifact_manifest.json", "results/cloud/chunk01_artifact_manifest.json"),
                ("chunk02/artifact_manifest.json", "results/cloud/chunk02_artifact_manifest.json"),
                ("chunk02/TRANSFER_VERIFICATION.json", "results/cloud/transfer_verification.json"),
                ("chunk02/transfer_receipts.jsonl", "results/cloud/transfer_receipts.jsonl")]
    for source, target in mappings:
        put(target, (CLOUD / source).read_bytes())
    for source in ("audit_cloud_scan.py", "append_cloud_publish.py", "restore_cloud_evidence.py"):
        put("source/"+source, (HERE / source).read_bytes())
    member_index = {"schema": "hepta.wsp.cloud-content-deduplication.v1",
                    "chunk01_original_archive_sha256": audit["archive_manifests"][0]["archive_sha256"],
                    "chunk02_original_archive_sha256": audit["archive_manifests"][1]["archive_sha256"],
                    "chunk01_files": audit["chunk01_member_reconstruction"],
                    "chunk02_files": [],
                    "restoration_scope": "All bytes of all scientific files for both jobs; original chunk02 gzip exact. Original chunk01 gzip container itself is not reconstructed."}
    for rec in member_index["chunk01_files"]:
        source = (root2 if rec["source"] == "chunk02" else root1) / rec["path"]
        assert source.stat().st_size == rec["bytes"] and sha(source.read_bytes()) == rec["sha256"]
        if rec["source"] == "chunk01_override":
            put("artifacts/cloud_chunk01_overrides/"+rec["path"], source.read_bytes())
    for path in sorted(root2.rglob("*")):
        if path.is_file():
            member_index["chunk02_files"].append({"path": str(path.relative_to(root2)), "bytes": path.stat().st_size,
                                                  "sha256": sha(path.read_bytes())})
    save(DEST / "results/cloud/member_index.json", member_index)
    archive_bytes = (CLOUD / "chunk02/evidence.tar.gz").read_bytes()
    assert sha(archive_bytes) == audit["archive_manifests"][1]["archive_sha256"]
    archive = put("artifacts/colab_chunk02_evidence.tar.gz", archive_bytes)
    cloud_status = {"status": "complete_two_fixed_arms_and_independently_verified_artifacts",
                    "actual_accelerator": "Tesla T4", "native_jobs": 2, "optimizer_steps": 400,
                    "independent_audit_digest": audit["audit_digest"], "archive": archive,
                    "original_cpu_manifest_sha256": ORIGINAL_CPU_MANIFEST,
                    "all_original_cpu_result_files_unchanged": True,
                    "first_job_file_tree_restored_from_final_plus_prior_metadata": True,
                    "readme": "README_CLOUD.md", "private_pocket4_data_included": False}
    (DEST / "colab_status.json").write_text(json.dumps(cloud_status, indent=2)+"\n")
    readme = """# Completed SCAN grammar-to-data cloud follow-up

Both author-fixed reference configurations completed on a real Tesla T4 through
HeptaRuntime. The original 20-arm CPU matrix remains byte-for-byte unchanged.
`CPU_PACKAGE_MANIFEST.json` preserves its original manifest (SHA256
`6aa1ce0986282b424fcd985f70bb1cb1ffdd4cf3dfb03d758a1725853beecd7e`).

## Model quality

| Fixed method | Final new, /2568 | Final old, /1000 | Neither training-input nor WSP-probe input, /1658 | Changed scalars |
|---|---:|---:|---:|---:|
| Parent | 0 | 996 | 0 | 0 |
| Published WSP program, exact child hash reproduced | 2563 | 996 | 1654 | 257 |
| Grammar-to-data sparse Adam, q3, 300 steps | 2557 | 996 | 1647 | 152718 |
| Grammar-to-data full Adam, q2, 100 steps | 2561 | 992 | 1651 | 757779 |

The 1658-command subset was specified before these fits by removing every input
used by the generated-label fit and every input probed by the published WSP
program. It is an audit subset of already public data, not a new independent
holdout. The rule-generated training set includes 684 final-new and 170 final-old
commands. One public base checkpoint and one author-selected seed/configuration
per method were used. No cloud candidate was selected or retuned on final scores.

On all final-new commands the WSP-vs-full-Adam paired counts are only 3 WSP-only
correct and 1 Adam-only correct; on the overlap-excluded subset they are 3 and 0.
The result establishes strong performance for both routes, without establishing
universal superiority or robustness across independently trained base models.

The original 65-label comparisons start at token CE about 5.23e-9; their failure
to add compositions cannot be read as a failure of gradient learning given the
grammar. The same grammar can instead generate supervised training targets.

The published WSP child matches its full canonical hash exactly. The GPU Adam
children do not match the original authors' checkpoint hashes; these are fixed
configuration reexecutions with float32 microbatch accumulation, whose reduction
order differs from upstream dense full-batch execution. Quality is measured by
the canonical NumPy forward on the sealed completed parameters.

## Cost and numerical limits

Two worker jobs used 548.777372686 seconds in total, including checks, readouts,
serialization and local work. They executed 400 Adam steps, 1,630,195 gradient
question rows, 12,836 accumulated microbatches plus one dense parity backward,
25,174 NumPy forward rows and 130 Torch inference rows. Host peak RSS was
1,511,380 KiB. `process_time()` values are reported per job as recorded, not
mislabelled as pure training CPU time. Dollar charges were not measured.

The CPU WSP program update took 84.377566 seconds in the separate matrix and
actually executed 15,195 forward rows. Its original author discovery used
1,860.065 seconds plus large editor-token usage; those records are preserved in
`results/author_discovery_cost.json`. A patch-only application time does not
include discovery or weight-dependent probing. CPU-vs-T4 wall times are not a
controlled speed comparison. The fixed cloud reference choices also inherit
author configuration-discovery costs, which are not included in this rerun.

CUDA preflight used the 65 already-solved rows. The nonzero-loss accumulation
audit in the CPU package was performed after cloud submission; it checks the
objective implementation but is not a pre-fit CUDA check on every generated row.
The independent artifact audit added no model forwards, gradients or fits.

## Complete evidence and restoration

The second archive is split into 450000-byte blobs. Its original gzip SHA256 is
`eb70989a3acd8360b0f29e1ea9cea06ab7210c4e64729257ecf5bd88d9c5ea0e`.
All 299 remote transfer chunks and the complete archive were independently
verified before safe unpacking. It contains both completed checkpoint tensors,
final optimizer states, training curves, source/data identities, hardware,
cached predictions and results. Earlier overwritten optimizer snapshots are not
claimed to exist merely because a receipt contains their hash.

Nineteen of the first archive's twenty scientific files are byte-identical in
the final archive. Its prior `job_records.json` is saved separately. The complete
member map permits restoration of every first-job scientific file with its exact
SHA. The first original gzip SHA is retained as provenance; the package does
not claim to recreate that gzip container byte-for-byte.

Run `python source/restore_cloud_evidence.py PACKAGE_DIRECTORY NEW_OUTPUT` to
validate the package, reconstruct the final archive, and restore both exact
scientific file trees. It executes no checkpoint or model code.

`results/cloud/heptaruntime_receipt.json` records two successful jobs. Subsequent
official inventory observed zero assigned runtimes and zero consumption. The
release request returned `FIXED_RUNTIME_NOT_FOUND`; its cause was not verified
and the provisioning ledger still said bound. This is not reported as a
successful release mutation. No recurring automation was created.

## Published comparison that must remain visible

[WeightCode Table 2](https://arxiv.org/html/2611.25476v1) reports add-primitive
grammar-generated fine-tuning at 99.6% with unchanged old performance. In its
different around-right setting, WSP reaches 89.6% and loses 0.3 percentage points
on old commands, while grammar-generated fine-tuning reaches 100.0% and loses
0.1 points. The authors explicitly call it a rule-to-data reference because its
generated commands include test commands. We reproduced add-primitive only;
we did not rerun around-right here. These facts rule out a general claim that
direct weight editing always has higher quality than conventional training.

This package contains public WeightCode/SCAN scientific data and execution
provenance. It includes no pocket4 checkpoint, private Hepta model tensors or
trading dataset. Actual Hepta experiments are archived separately.
"""
    put("README_CLOUD.md", readme.encode())
    # The only overwritten pre-existing files are the completion-status metadata
    # and outer package manifest. All CPU experiment evidence remains frozen.
    for rec in old["files"]:
        if rec["path"] != "colab_status.json":
            assert sha((DEST / rec["path"]).read_bytes()) == rec["sha256"]
    files = [{"path": str(path.relative_to(DEST)), "bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}
             for path in sorted(DEST.rglob("*")) if path.is_file() and path.name != "PACKAGE_MANIFEST.json"]
    assert all(x["bytes"] <= CHUNK for x in files)
    manifest = {"files": files, "all_blobs_max_bytes": CHUNK, "cpu_matrix_complete": True, "cloud": cloud_status}
    (DEST / "PACKAGE_MANIFEST.json").write_text(json.dumps(manifest, indent=2)+"\n")
    old_map = {x["path"]: x["sha256"] for x in old["files"]}
    changes = [x for x in files if old_map.get(x["path"]) != x["sha256"]]
    changes.append({"path": "PACKAGE_MANIFEST.json", "bytes": (DEST / "PACKAGE_MANIFEST.json").stat().st_size,
                    "sha256": sha((DEST / "PACKAGE_MANIFEST.json").read_bytes())})
    save(HERE / "publish/CLOUD_CHANGED_FILES.json", {"previous_package_manifest_sha256": ORIGINAL_CPU_MANIFEST,
          "new_package_manifest_sha256": changes[-1]["sha256"], "changed_files": changes,
          "files_deleted": [], "original_cpu_scientific_evidence_unchanged": True,
          "private_pocket4_data_included": False})
    print(json.dumps({"new_manifest_sha256": changes[-1]["sha256"], "changed_files": len(changes),
                      "changed_bytes": sum(x["bytes"] for x in changes), "total_files": len(files)+1}))


if __name__ == "__main__":
    main()
