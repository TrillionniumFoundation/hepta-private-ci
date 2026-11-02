"""Read-only frontend prerequisites; reuse the pinned v6 baseline verifier.

This checks bytes and declared recording inventories, not quality or independent
execution. A ledger's completeness still requires the recovered historical owner
records; an arbitrary newly written exclusion list cannot establish that claim.
"""

import argparse
import json
from pathlib import Path
import re

from experiments.hcsn_v7_support_20261101 import restore_check

ROOT = Path(__file__).resolve().parents[3]
DRAFT = Path("experiments/hcsn_v7_support_20261101/protocol/PROTOCOL_DRAFT.json")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RECORDING = re.compile(r"(?P<actor>[0-9]{4})_[A-Z]{3}_(?:ANG|DIS|FEA|HAP|NEU|SAD)_(?:LO|MD|HI|XX)\Z")
ASSETS = {
    "strong_audio": "strong_audio_weight_sha256",
    "common_content_head": "common_content_head_weight_sha256",
    "projection_alignment": "common_projection_alignment_weight_sha256",
    "encoder": "common_encoder_weight_sha256",
}


def file_at(repo, name):
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError("expected a nonempty repository-relative path")
    path = (repo / name).resolve()
    if not path.is_relative_to(repo.resolve()) or not path.is_file():
        raise ValueError("missing file or path outside repository: " + name)
    return path


def read_bound(repo, name, expected):
    if not isinstance(expected, str) or not SHA256.fullmatch(expected):
        raise ValueError("missing or malformed SHA256 for " + str(name))
    path = file_at(repo, name)
    if restore_check.digest(path) != expected:
        raise ValueError("SHA256 mismatch: " + str(name))
    return path


def recording_rows(rows, role):
    """Require canonical IDs; do not silently normalize ambiguous aliases."""
    if not isinstance(rows, list) or not rows:
        raise ValueError(role + ": recording inventory missing or empty")
    result = {}
    hashes = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(role + ": malformed recording row")
        name, sha = row.get("recording_id"), row.get("media_sha256")
        match = RECORDING.fullmatch(name) if isinstance(name, str) else None
        if match is None or row.get("actor_id") != match.group("actor"):
            raise ValueError(role + ": noncanonical recording ID or inconsistent actor")
        if not isinstance(sha, str) or not SHA256.fullmatch(sha):
            raise ValueError(role + ": missing raw-media SHA256")
        if name in result or sha in hashes:
            raise ValueError(role + ": duplicate recording or raw-media alias")
        result[name] = row
        hashes.add(sha)
    return result


def check_recordings(history, development, confirmation):
    """Check source-recording and exact-byte overlap, not prefixes or pair IDs."""
    old = recording_rows(history, "history")
    dev = recording_rows(development, "development")
    fresh = recording_rows(confirmation, "confirmation")
    prior_names = set(old) | set(dev)
    prior_hashes = {r["media_sha256"] for r in [*old.values(), *dev.values()]}
    if set(fresh) & prior_names:
        raise ValueError("confirmation reuses a historical/development source recording")
    if {r["media_sha256"] for r in fresh.values()} & prior_hashes:
        raise ValueError("confirmation reuses raw media under another recording ID")
    return {"history_recordings": len(old), "development_recordings": len(dev),
            "confirmation_recordings": len(fresh),
            "confirmation_actors": sorted({r["actor_id"] for r in fresh.values()}),
            "reused_historical_actors": sorted({r["actor_id"] for r in fresh.values()} &
                                                {r["actor_id"] for r in old.values()})}


def inspect(repo, handoff_path=None, protocol_path=DRAFT):
    baseline = restore_check.inspect(repo, {})
    result = {"schema": "hcsn-v9-frontend-prerequisites.v1", "baseline": baseline,
              "problems": list(baseline["problems"]), "recording_nonoverlap": None,
              "asset_bytes_verified": {}, "history_completeness_verified": False,
              "admitted_for_confirmation": False, "quality_gate_passed": False,
              "new_confirmation_executed": False, "production_activation": False}
    try:
        protocol = json.loads(file_at(repo, str(protocol_path)).read_text())
        fields = protocol["required_before_freeze"]
        if not isinstance(fields, dict):
            raise ValueError("required_before_freeze must be an object")
        if fields.get("v6_all_source_and_input_hashes_verified") is not True:
            result["problems"].append("protocol does not attest completed v6 source/input verification")
        if protocol.get("frozen") is not True:
            result["problems"].append("protocol is not frozen")
        required = json.loads((ROOT / DRAFT).read_text())["required_before_freeze"]
        missing = [key for key in required if fields.get(key) is None or fields.get(key) == ""]
        result["missing_protocol_fields"] = missing
        if missing:
            result["problems"].append("required protocol fields unavailable: " + ", ".join(missing))
        for key, value in fields.items():
            if key.endswith("sha256") and value is not None and (
                    not isinstance(value, str) or not SHA256.fullmatch(value)):
                result["problems"].append("malformed protocol digest: " + key)
        if handoff_path is None:
            raise ValueError("frontend handoff unavailable; no exclusion/strong-audio identity inferred")
        handoff = json.loads(file_at(repo, str(handoff_path)).read_text())
        if handoff.get("schema") != "hcsn-v9-frontend-handoff.v1":
            raise ValueError("unsupported frontend handoff schema")
        for name, field in ASSETS.items():
            asset = handoff.get("assets", {}).get(name, {})
            expected = fields.get(field)
            if asset.get("sha256") != expected:
                raise ValueError("asset differs from frozen protocol: " + name)
            read_bound(repo, asset.get("path"), expected)
            result["asset_bytes_verified"][name] = expected
        exclusion_path = read_bound(repo, fields.get("v5_v6_source_recording_exclusion_manifest_path"),
                                    fields.get("v5_v6_source_recording_exclusion_manifest_sha256"))
        exclusions = json.loads(exclusion_path.read_text())
        # Original owner-ledger bytes must occur in the pinned original protocol.
        # A caller's assertion that a new list is complete is never accepted.
        original_path = repo / restore_check.V6_ROOT / "configs/frontend/CONFIRMATION_PROTOCOL.json"
        if not original_path.is_file() or restore_check.digest(original_path) != restore_check.PROTOCOL_SHA256:
            raise ValueError("pinned original v6 protocol unavailable for historical provenance")
        original = json.loads(original_path.read_text())
        original_inputs = original.get("inputs", {})
        ledgers = exclusions.get("historical_owner_ledgers")
        if not isinstance(ledgers, list) or not ledgers:
            raise ValueError("historical owner ledgers unavailable")
        covered_versions, records = set(), []
        for ledger in ledgers:
            if ledger.get("version") not in ("v5", "v6"):
                raise ValueError("unknown historical ledger version")
            path, sha = ledger.get("path"), ledger.get("sha256")
            if original_inputs.get(path) != sha:
                raise ValueError("historical ledger not bound by original v6 inputs")
            doc = json.loads(read_bound(repo, path, sha).read_text())
            # This explicit format avoids guessing IDs out of arbitrary filenames.
            if doc.get("schema") != "hcsn-recording-owner-ledger.v1" or doc.get("version") != ledger["version"]:
                raise ValueError("unsupported original owner-ledger layout; add a reviewed parser")
            records.extend(recording_rows(doc.get("recordings"), "original ledger").values())
            covered_versions.add(ledger["version"])
        if covered_versions != {"v5", "v6"}:
            raise ValueError("historical ledgers do not cover both v5 and v6")
        # Repeated recordings across historical stages are expected. The same ID
        # must still refer to the same media; union first, then validate aliases.
        union = {}
        for row in records:
            if row["recording_id"] in union and union[row["recording_id"]] != row:
                raise ValueError("historical owner ledgers disagree on recording identity")
            union[row["recording_id"]] = row
        if recording_rows(exclusions.get("recordings"), "exclusions") != union:
            raise ValueError("exclusion inventory differs from original historical ledger union")
        result["history_completeness_verified"] = True
        dev_path = read_bound(repo, fields.get("v7_development_manifest_path"), fields.get("v7_development_manifest_sha256"))
        confirm_path = read_bound(repo, fields.get("v7_confirmation_manifest_path"), fields.get("v7_confirmation_manifest_sha256"))
        dev = json.loads(dev_path.read_text())["recordings"]
        confirm = json.loads(confirm_path.read_text())["recordings"]
        result["recording_nonoverlap"] = check_recordings(list(union.values()), dev, confirm)
        for row in confirm:
            read_bound(repo, row.get("media_path"), row["media_sha256"])
        if sorted(row["recording_id"] for row in confirm) != sorted(fields.get("v7_confirmation_recording_ids") or []):
            raise ValueError("confirmation IDs differ from protocol")
        if result["recording_nonoverlap"]["confirmation_actors"] != sorted(fields.get("v7_confirmation_actor_ids") or []):
            raise ValueError("confirmation actors differ from protocol")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result["problems"].append(str(exc))
    result["admitted_for_confirmation"] = not result["problems"]
    result["status"] = "prerequisites_verified" if result["admitted_for_confirmation"] else "HOLD"
    result["limits"] = "Byte and declared inventory checks only; owner-ledger exhaustiveness/authenticity, new-actor independence, frontend quality and calibration require separate evidence. Unsupported historical layouts fail closed."
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--protocol", type=Path, default=DRAFT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.repo, args.handoff, args.protocol)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"status": result["status"], "problems": result["problems"]}))
    return 0 if result["admitted_for_confirmation"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
