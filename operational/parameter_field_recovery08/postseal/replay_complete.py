"""Read-only execution08 replay with original bytes and new restoration evidence."""

import argparse
from pathlib import Path
import resource
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from operational.parameter_field_recovery08 import common as c  # noqa: E402
from operational.parameter_field_recovery08.postseal import review  # noqa: E402
from operational.parameter_field_recovery08.postseal.replay_accounting import (  # noqa: E402
    CONFIG_SHA, SOURCE, restore_metadata,
)
from operational.parameter_field_recovery08.postseal.restored_archives import (  # noqa: E402
    SCHEMA, RestoredMetadata, copy_new, restore_archive, restore_final_raw,
)


def assets(config, contract):
    """Recover pinned input bytes; the historical preparation receipt stays historical."""
    receipt = c.bound(config["descriptors"]["assets_receipt"])
    old = c.bound(receipt["current_asset_assembly_copy"])
    manifest = c.bound(old["public_manifest"])
    destination = Path(config["assets_root"])
    c.need(not destination.exists(), "Fresh input destination required")
    for row in manifest["files"]:
        item = next(v for v in contract["assets"] if v["path"] == row["path"])
        url = row.get("public_download_url") or (
            "https://raw.githubusercontent.com/TrillionniumFoundation/hepta-private-ci/"
            + contract["public_assets_commit"] + "/" + row["repository_path"]
        )
        with urllib.request.urlopen(url, timeout=120) as stream:
            copy_new(stream, destination / review.logical(item["path"]), item)
    original = receipt["current_asset_assembly_copy"]
    with c.checked(original).open("rb") as stream:
        copy_new(stream, destination / "RESTORATION.json", original)


def replay(archive):
    started, cpu = time.monotonic(), time.process_time()
    archive_item, originals = restore_metadata(archive)
    config_item = c.descriptor(Path("/work/execution08/ops/registrations/initial/PIPELINE_CONFIG.json"))
    config = c.bound(config_item)
    c.need(config_item["sha256"] == CONFIG_SHA and config["source_commit"] == SOURCE,
           "Frozen configuration/source differs")
    source, ops, raw = (Path(config[k]) for k in ("source_root", "ops_root", "raw_root"))
    c.need(source == Path("/work/source"), "Canonical original source required")
    c.committed_sources(source, SOURCE, config["source_files"])
    contract = c.read(source / "operational/parameter_field_recovery08/INPUT_CONTRACT.json")
    c.need(all(config[k] == contract[k] for k in
               ("source_root", "ops_root", "raw_root", "cas_root", "assets_root", "python")),
           "Frozen destination contract differs")
    root = Path("/work/replay")
    root.mkdir(exist_ok=False)
    downloads, copies = root / "downloads", root / "archive_sources"
    downloads.mkdir()
    complete = c.read(ops / "COMPLETE.json")
    terminal_item = c.descriptor(ops / "TERMINAL_CLOSURE.json")
    terminal = c.bound(terminal_item)
    publication = c.bound(terminal["publication"])
    rows = [*complete["durable_stages"], publication["terminal_archive"]]
    c.need(len(rows) == 18 and len({r["artifact"]["id"] for r in rows}) == 18,
           "All eighteen distinct immutable deliveries required")
    records = []
    for row in rows:
        artifact_id = row["artifact"]["id"]
        downloaded = downloads / (str(artifact_id) + ".zip")
        with downloaded.open("xb") as output:
            subprocess.run(["gh", "api", "repos/TrillionniumFoundation/hepta-private-ci/"
                            + f"actions/artifacts/{artifact_id}/zip"], stdout=output,
                           check=True, timeout=240)
        records.append(restore_archive(row, downloaded, copies / str(artifact_id)))
        print("Restored immutable archive", artifact_id, flush=True)
    restored_raw = restore_final_raw(rows, copies, raw, complete["artifacts"]["manifest"])
    assets(config, contract)
    receipt = c.write_new(root / "READBACK.json", {
        "schema": SCHEMA, "historical_receipts_modified": False,
        "original_operations_archive": archive_item, "producer_source_commit": SOURCE,
        "reviewer_source_commit": c.git(ROOT, "rev-parse", "HEAD").decode().strip(),
        "reviewer_source_tree": c.git(ROOT, "rev-parse", "HEAD^{tree}").decode().strip(),
        "restored_raw_files": restored_raw, "archives": records,
        "input_preparation_receipt_role": "original episode history, not a new host receipt",
        "old_device_inode_numbers_are_not_current_machine_proof": True,
    })
    metadata = RestoredMetadata(receipt, rows)
    admitted, operations = review.operational_gate(config, config_item, terminal_item, metadata)
    operations["restored_readback"] = receipt
    operations["review_scope"] = "original execution with fresh byte restoration, no new science run"
    # Scientific imports resolve to the clean original commit, after all byte gates.
    sys.path.insert(0, str(source))
    result = review.analyze(config, config_item, terminal_item, root / "postseal",
                            metadata, admitted, operations, started, cpu)
    for path, expected in originals:
        c.need(c.descriptor(path)["sha256"] == expected, "Historical receipt changed")
    for name, module in tuple(sys.modules.items()):
        if name.startswith(("experiments.", "supplements.",
                            "operational.parameter_field_five_questions_20261031.")):
            filename = getattr(module, "__file__", None)
            if filename is not None:
                path = c.regular(filename)
                c.need(path.is_relative_to(source)
                       and config["source_files"].get(path.relative_to(source).as_posix())
                       == c.descriptor(path)["sha256"], "Scientific import escaped original closure")
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {"schema": "hepta.execution08.complete-replay.1", "complete": True,
              "status": result["status"], "review": c.descriptor(root / "postseal/COMPLETE.json"),
              "readback": receipt, "original_bytes_unchanged": True,
              "original_failed_exit_receipts_retained": True,
              "reviewer_python": sys.version, "new_independent_samples": 0,
              "training_refitting_or_scoring_performed": False,
              "wall_seconds": time.monotonic() - started,
              "parent_cpu_seconds": time.process_time() - cpu,
              "download_child_cpu_seconds": usage.ru_utime + usage.ru_stime,
              "historical_campaign_cost_complete": False, "adoption": "not_assessed"}
    c.write_new(root / "COMPLETE.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = replay(args.archive.resolve(strict=True))
    except Exception as error:
        failure = {"complete": False, "reason": str(error),
                   "scientific_completion_claim": False}
        print(c.encode(failure).decode(), flush=True)
        root = Path("/work/replay")
        if root.is_dir() and not (root / "FAILED.json").exists():
            c.write_new(root / "FAILED.json", failure)
        raise
    print(c.encode({"complete": True, "status": result["status"]}).decode(), flush=True)


if __name__ == "__main__":
    main()
