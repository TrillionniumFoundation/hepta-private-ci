"""Restore hash-pinned research evidence and replay Heads without model downloads.

This verifies retained bytes and predictions. It does not repeat original-image
encoding, establish publisher authenticity, or grant production admission.
"""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile

MAX_COMPRESSED = 32 * 1024 * 1024
MAX_EXPANDED = 96 * 1024 * 1024
HEX = re.compile(r"[0-9a-f]{64}\Z")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def relative_path(name):
    if (type(name) is not str or name in ("", ".") or "\\" in name or ":" in name
            or any(ord(character) < 32 for character in name)
            or PurePosixPath(name).is_absolute()
            or ".." in PurePosixPath(name).parts
            or PurePosixPath(name).as_posix() != name):
        raise ValueError("canonical relative evidence path required")
    return name


def checked_bytes(path, record, limit):
    if (type(record.get("bytes")) is not int or not 0 < record["bytes"] <= limit
            or type(record.get("sha256")) is not str
            or HEX.fullmatch(record["sha256"]) is None
            or path.is_symlink() or not path.is_file()
            or path.stat().st_size != record["bytes"]):
        raise ValueError("irregular or oversized evidence payload")
    raw = path.read_bytes()
    if len(raw) != record["bytes"] or digest(raw) != record["sha256"]:
        raise ValueError("evidence payload differs from retained digest")
    return raw


def restore_evidence(directory, *, expected_manifest_sha256, output):
    source, target = Path(directory), Path(output)
    manifest_path = source / "archive-manifest.json"
    if (source.is_symlink() or not source.is_dir() or manifest_path.is_symlink()
            or not manifest_path.is_file() or manifest_path.stat().st_size > 512000
            or type(expected_manifest_sha256) is not str
            or HEX.fullmatch(expected_manifest_sha256) is None
            or target.exists() or target.is_symlink()
            or not target.parent.is_dir() or target.parent.is_symlink()):
        raise ValueError("pinned manifest and new output in a real parent required")
    raw_manifest = manifest_path.read_bytes()
    if digest(raw_manifest) != expected_manifest_sha256:
        raise ValueError("archive manifest differs from external digest")
    manifest = json.loads(raw_manifest)
    if (manifest.get("schema") != "hepta.multimodal-evidence-archive.v1"
            or manifest.get("authority") != "DENY_ALL"
            or manifest.get("production_activation_allowed") is not False):
        raise ValueError("unexpected archive schema or authority")
    archive, members = manifest["archive"], manifest["members"]
    parts = archive["parts"]
    if (archive["format"] != "tar+gzip" or type(parts) is not list
            or not 1 <= len(parts) <= 64 or type(members) is not dict
            or not 1 <= len(members) <= 1024
            or type(archive["bytes"]) is not int
            or not 0 < archive["bytes"] <= MAX_COMPRESSED):
        raise ValueError("archive inventory exceeds budget")
    names, payloads, compressed_bytes = set(), [], 0
    for part in parts:
        name = relative_path(part["name"])
        if len(PurePosixPath(name).parts) != 1 or name in names:
            raise ValueError("unique local archive parts required")
        names.add(name)
        payload = checked_bytes(source / name, part, 512000)
        compressed_bytes += len(payload)
        if compressed_bytes > MAX_COMPRESSED:
            raise ValueError("combined archive exceeds byte budget")
        payloads.append(payload)
    compressed = b"".join(payloads)
    if len(compressed) != archive["bytes"] or digest(compressed) != archive["sha256"]:
        raise ValueError("assembled archive digest mismatch")
    total = 0
    for name, record in members.items():
        relative_path(name)
        if (type(record.get("bytes")) is not int or not 0 < record["bytes"] <= MAX_EXPANDED
                or type(record.get("sha256")) is not str
                or HEX.fullmatch(record["sha256"]) is None):
            raise ValueError("invalid retained member record")
        total += record["bytes"]
    if total > MAX_EXPANDED:
        raise ValueError("expanded member inventory exceeds budget")
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        expanded = stream.read(MAX_EXPANDED + 1)
    if len(expanded) > MAX_EXPANDED:
        raise ValueError("expanded archive exceeds byte budget")
    temporary = Path(tempfile.mkdtemp(prefix=".hepta-mm-restore-", dir=target.parent))
    try:
        seen = set()
        with tarfile.open(fileobj=io.BytesIO(expanded), mode="r:") as tar:
            for member in tar:
                name = relative_path(member.name)
                if (not member.isfile() or name in seen or name not in members
                        or member.size != members[name]["bytes"]):
                    raise ValueError("unindexed, repeated or nonregular archive member")
                seen.add(name)
                payload = tar.extractfile(member).read(member.size + 1)
                if len(payload) != member.size or digest(payload) != members[name]["sha256"]:
                    raise ValueError("archive member digest mismatch")
                destination = temporary / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as stream:
                    stream.write(payload)
                destination.chmod(0o600)
        if seen != set(members):
            raise ValueError("archive member inventory differs")
        temporary.rename(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return manifest


def replay_heads(output):
    """Recompute all 20 ledgers from the six retained Heads and frozen features."""
    root = Path(output)
    report = json.loads((root / "results/report.json").read_text())
    plan = report["plan"]
    import torch
    from cell_head_training import load_head_artifact
    from multimodal_features import ARMS, load_bank, pair_features
    from multimodal_research import INTERVENTIONS, MODES, make_ledger, make_plan, minority_indices
    from prediction_ledger import canonical, load_prediction_ledger, sha

    if (report.get("schema") != "hepta.multimodal-research-report.v1"
            or report.get("engineering_status") != "COMPLETE"
            or report.get("authority") != "DENY_ALL"
            or report.get("production_activation_allowed") is not False
            or type(plan.get("threads")) is not int or not 1 <= plan["threads"] <= 8
            or plan != make_plan(data_sha256=report["data_manifest_sha256"],
                bank_sha256=report["bank_manifest_sha256"], threads=plan["threads"])
            or report.get("plan_sha256") != sha(canonical(plan))):
        raise ValueError("report or full fixed plan differs from the current research source")
    expected_heads = {f"{arm}-{mode}": f"{arm}-{mode}-head" for arm in ARMS for mode in MODES}
    expected_ledgers = {key: key + "-test" for key in expected_heads}
    expected_ledgers.update({key + "-minority": key + "-minority" for key in expected_heads})
    expected_ledgers.update({f"text_image-{mode}-{item}": f"text_image-{mode}-{item}"
        for mode in MODES for item in (*INTERVENTIONS, "shuffled_relabelled")})
    for category, expected in (("head_artifacts", expected_heads), ("ledgers", expected_ledgers)):
        records = report.get(category)
        if (type(records) is not dict or set(records) != set(expected)
                or any(type(records[key]) is not dict
                    or records[key].get("directory") != directory
                    for key, directory in expected.items())):
            raise ValueError("complete fixed Head/ledger inventory and local directories required")

    torch.set_num_threads(plan["threads"])
    bank, features = load_bank(root / "bank",
        expected_manifest_sha256=report["bank_manifest_sha256"],
        expected_data_sha256=report["data_manifest_sha256"])
    rows = [json.loads(line) for line in (root / "cohorts/test.jsonl").read_text().splitlines()]
    minority = minority_indices(rows, plan)
    count = 0
    for arm in plan["arms"]:
        paired = pair_features(rows, bank, features, arm=arm)
        for mode in plan["modes"]:
            key = f"{arm}-{mode}"
            record = report["head_artifacts"][key]
            head = load_head_artifact(root / "results" / record["directory"],
                expected_manifest_sha256=record["manifest_sha256"], expected_identity=paired.identity)
            cases = [(key, "paired", None, False),
                     (key + "-minority", "paired", minority, False)]
            if arm == "text_image":
                cases += [(key + "-" + item, item, None, False) for item in plan["interventions"]]
                cases.append((key + "-shuffled_relabelled", "shuffled_image", None, True))
            for ledger_key, intervention, indices, relabel in cases:
                bundle = paired if intervention == "paired" else pair_features(
                    rows, bank, features, arm=arm, intervention=intervention)
                retained = report["ledgers"][ledger_key]
                metadata = json.loads((root / "results" / retained["directory"] / "manifest.json").read_text())["metadata"]
                replay = make_ledger(head, bundle, rows, plan, arm=metadata["arm"],
                    split=metadata["split"], intervention=metadata["intervention"],
                    indices=indices, relabel=relabel)
                stored = load_prediction_ledger(root / "results" / retained["directory"],
                    expected_manifest_sha256=retained["manifest_sha256"], expected_identity=replay.identity)
                if (replay.ledger_sha256 != stored.ledger_sha256
                        or replay.ledger_sha256 != retained["ledger_sha256"]
                        or replay.metrics() != retained["metrics"]):
                    raise ValueError("replayed predictions differ: " + ledger_key)
                count += 1
    return {"head_count": len(report["head_artifacts"]), "replayed_ledgers": count,
        "predictions_match_exactly": True, "original_image_encoding_repeated": False,
        "quality_qualified": report["quality_qualified"],
        "authority": "DENY_ALL", "production_activation_allowed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--replay-heads", action="store_true")
    args = parser.parse_args()
    manifest = restore_evidence(args.directory,
        expected_manifest_sha256=args.manifest_sha256, output=args.output)
    receipt = {"restored_members": len(manifest["members"]), "source_sha": manifest["source_sha"]}
    if args.replay_heads:
        receipt.update(replay_heads(args.output))
    print(json.dumps(receipt, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
