"""Replay execution08's immutable accounting, without decoding scientific payloads."""

import argparse
import hashlib
from pathlib import Path
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from operational.parameter_field_recovery08 import common as c  # noqa: E402
from operational.parameter_field_recovery08.postseal import review  # noqa: E402

SOURCE = "01131230aac0aca8cf016ee407b267e40a29c3c8"
ARCHIVE_SHA = "9e666cf0aea68d154138b8c5f1cc70d5a3ec5565aee28769d4984cc11527e7a4"
CONFIG_SHA = "74863ca0141fdeb6a3556a8267b96a7e75ef7c580ed4303ef2585fcae177f2d1"


def restore_metadata(archive):
    item = c.descriptor(archive)
    c.need(item["sha256"] == ARCHIVE_SHA and item["bytes"] == 2239108,
           "Original provider artifact identity differs")
    restored = []
    with zipfile.ZipFile(archive) as saved:
        members = saved.infolist()
        c.need(len({v.filename for v in members}) == len(members)
               and sum(v.file_size for v in members) <= 128 * 1024**2,
               "Unsafe metadata archive population")
        for member in members:
            relative = review.logical(member.filename.rstrip("/"))
            c.need(relative.parts[0] in ("preparation", "qualification", "execution08")
                   and stat.S_IFMT(member.external_attr >> 16) in (0, stat.S_IFREG, stat.S_IFDIR)
                   and not member.flag_bits & 1, "Unsafe metadata archive member")
            if member.is_dir():
                continue
            target = Path("/work") / relative
            c.need(target.resolve() == target, "Restoration path contains a symlink")
            raw = saved.read(member)
            if target.exists():
                c.need(c.regular(target).read_bytes() == raw,
                       "Refusing to overwrite another receipt: " + str(target))
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as output:
                    output.write(raw)
            restored.append((target, hashlib.sha256(raw).hexdigest()))
    return item, restored


def replay(archive):
    item, restored = restore_metadata(archive)
    root = Path("/work/execution08")
    config_item = c.descriptor(root / "ops/registrations/initial/PIPELINE_CONFIG.json")
    config = c.bound(config_item)
    c.need(config_item["sha256"] == CONFIG_SHA
           and config["source_commit"] == SOURCE
           and config["actions_identity"]["run_id"] == "41260752710",
           "Frozen source or producer differs")
    scopes = [root / "ops/owned_workers" / name for name in
              sorted(set(c.ORDER) | {"register_" + s for s in
                     ("followups", "endpoints", "analysis", "finalizer")}
                     | {"analysis", "finalizer"})]
    nested = root / "ops/wrapper_runs/ANALYSIS_PARENT/owned_children"
    scopes += [root / "initialization_measurement/children", root / "ops/outer_wait4",
               root / "ops/registrations/initial/semantic_measurement",
               root / "ops/terminal_publication_measurement", nested]
    metadata, results = review.Metadata(), []
    for scope in scopes:
        bound_config = None if scope == root / "initialization_measurement/children" else config_item
        result = review.wait4(metadata, scope, config_item=bound_config,
                              allow_analysis_exit=scope == nested)
        results.append({"scope": str(scope.relative_to(root)), **result})
    preserved_failures = []
    for scope in (root / "pipeline_measurement/children", root / "postseal_measurement"):
        value = metadata.file(scope / "001.WAIT4.json")
        c.need(value["exit_code"] == 2, "Original failed exit was changed")
        preserved_failures.append({"scope": str(scope.relative_to(root)), "exit_code": 2})
    metadata.stable()
    for path, expected in restored:
        c.need(c.descriptor(path)["sha256"] == expected, "Original receipt was modified")
    return {
        "schema": "hepta.execution08.accounting-replay.1",
        "producer_run_id": 41260752710, "producer_source_commit": SOURCE,
        "provider_artifact_id": 13070691262, "provider_archive": item,
        "restored_metadata_files": len(restored), "original_bytes_unchanged": True,
        "successful_owned_scopes": results, "successful_scope_count": len(results),
        "original_failed_review_exits_preserved": preserved_failures,
        "scientific_payloads_decoded": False, "scientific_completion_claim": False,
        "full_postseal_review_complete": False,
        "remaining_review": ["original inputs and complete frozen source closure",
                             "all provider archives and fresh independent readback",
                             "original complete scientific seals and result interpretation"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.archive.resolve(strict=True))
    c.write_new(args.output, result)
    print(c.encode({"successful_scope_count": result["successful_scope_count"],
                    "original_bytes_unchanged": True,
                    "scientific_completion_claim": False}).decode(), end="")


if __name__ == "__main__":
    main()
