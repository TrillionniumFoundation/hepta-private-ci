"""Fail-closed v2 cohort isolation against v1 and earlier image histories.

The historical input may be a regular hepta.grounded-cohort manifest or the
hepta.ndu.historical-exclusions wrapper. This checks observable identities
only; it cannot attest real-world entity overlap or base-model pretraining.
"""

import argparse
import hashlib
import json
import math
import os
import stat
import tempfile
from pathlib import Path
import re

HEX256 = re.compile(r"^[0-9a-f]{64}$")
HEX64 = re.compile(r"^[0-9a-f]{16}$")
TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
SPLITS = ("train", "dev", "calibration", "test")
V1_SPLIT_COUNTS = (128, 32, 32, 64)
MAX_CANDIDATE_SOURCES = 2048
MAX_HISTORICAL_SOURCES = 4096
MAX_PAIR_COMPARISONS = 2_000_000
MAX_VIOLATIONS = 4096
MAX_INPUT_BYTES = 16 * 1024 * 1024

# Immutable identities from the originally completed negative-v1 evidence.
# Caller-provided SHA256 is only an integrity check for arbitrary supplied
# bytes; it cannot establish that the actual frozen history was provided.
ORIGINAL_HISTORICAL_SHA256 = {
    "hepta.grounded-cohort.v1": "71168c26fffdd913d71a69d8708cec957f55dc2bece112c9c50153fbf31de75d",
    "hepta.ndu.historical-exclusions.v1": "4c2b88f85c9ef5fea08790775a652798a72e9281bed1534561f14c681e7bba9d",
}


class CohortContractError(ValueError):
    pass


def decode_unambiguous_json(raw):
    """Reject ambiguous source evidence before normalizing a manifest."""
    def unique_pairs(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise CohortContractError(f"duplicate JSON object key: {name!r}")
            result[name] = value
        return result

    def reject_constant(value):
        raise CohortContractError(f"nonstandard JSON number: {value}")

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise CohortContractError("nonfinite JSON numeric value")
        return number

    try:
        return json.loads(raw, object_pairs_hook=unique_pairs,
                          parse_constant=reject_constant, parse_float=finite_float)
    except CohortContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as error:
        raise CohortContractError("invalid cohort JSON bytes") from error


def verify_frozen_history_pins(raw_documents, documents):
    """Bind original history to the published, preregistered raw bytes.

    This remains an image-provenance guard, not independent signer custody,
    entity/pretraining disjointness, real learning efficacy or authority.
    """
    if len(raw_documents) != 2 or len(documents) != 2:
        raise CohortContractError("v2 requires both original v1 and historical exclusions")
    seen = set()
    for index, (raw, document) in enumerate(zip(raw_documents, documents)):
        if not isinstance(raw, bytes) or not isinstance(document, dict):
            raise CohortContractError(f"history:{index}: invalid original history input")
        schema = document.get("schema")
        if (not isinstance(schema, str) or schema not in ORIGINAL_HISTORICAL_SHA256
                or schema in seen):
            raise CohortContractError(
                f"history:{index}: duplicated or unknown original history schema"
            )
        if hashlib.sha256(raw).hexdigest() != ORIGINAL_HISTORICAL_SHA256[schema]:
            raise CohortContractError(f"history:{index}: original frozen SHA256 mismatch")
        seen.add(schema)
    if seen != set(ORIGINAL_HISTORICAL_SHA256):
        raise CohortContractError("original historical evidence set is incomplete")


def _checked_image(row, origin, *, allow_image_id=False):
    if not isinstance(row, dict):
        raise CohortContractError(f"{origin}: source must be an object")
    identifier = row.get("source_id")
    if allow_image_id and not identifier:
        image_id = row.get("image_id")
        if type(image_id) is not int or image_id < 0:
            raise CohortContractError(f"{origin}: invalid historical image_id")
        identifier = f"coco:val2017:{image_id}"
    if not isinstance(identifier, str) or not identifier.strip():
        raise CohortContractError(f"{origin}: missing source_id")
    if (len(identifier) > 256 or identifier != identifier.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in identifier)):
        raise CohortContractError(f"{origin}: noncanonical source_id")
    if allow_image_id and "image_id" in row:
        image_id = row["image_id"]
        if (type(image_id) is not int or image_id < 0
                or identifier != f"coco:val2017:{image_id}"):
            raise CohortContractError(f"{origin}: source_id/image_id mismatch")
    keys = ("image_sha256", "decoded_rgb_sha256", "dhash64")
    for key, rule in zip(keys, (HEX256, HEX256, HEX64)):
        if not isinstance(row.get(key), str) or not rule.fullmatch(row[key]):
            raise CohortContractError(f"{origin}: missing or invalid {key}")
    return {"origin": origin, "source_id": identifier,
            # Only a four-split manifest carries score/journal task identity.
            # Historical image-exclusion wrappers carry source identity only.
            **({} if allow_image_id else {"task_id": row["task_id"]}),
            **{key: row[key] for key in keys}}


def load_sources(document, origin, *, historical=False):
    if not isinstance(document, dict):
        raise CohortContractError(f"{origin}: manifest is not an object")
    if document.get("schema") == "hepta.ndu.historical-exclusions.v1":
        if not historical:
            raise CohortContractError(f"{origin}: an exclusions wrapper cannot be a candidate cohort")
        sample = document.get("source_sample")
        images = sample.get("images") if isinstance(sample, dict) else None
        if not isinstance(images, list) or not images:
            raise CohortContractError(f"{origin}: empty historical exclusions")
        if len(images) > MAX_HISTORICAL_SOURCES:
            raise CohortContractError(f"{origin}: historical source limit exceeded")
        return [_checked_image(item, f"{origin}:prior:{n}", allow_image_id=True)
                for n, item in enumerate(images)]
    if document.get("schema") != "hepta.grounded-cohort.v1":
        raise CohortContractError(f"{origin}: unsupported manifest schema")
    splits = document.get("splits")
    if not isinstance(splits, dict) or set(splits) != set(SPLITS):
        raise CohortContractError(f"{origin}: require exactly four original-source splits")
    sources = []
    task_ids = set()
    for split in SPLITS:
        part = splits[split]
        if not isinstance(part, dict) or not isinstance(part.get("sources"), list):
            raise CohortContractError(f"{origin}:{split}: malformed source list")
        if type(part.get("count")) is not int or part["count"] != len(part["sources"]) or not part["sources"]:
            raise CohortContractError(f"{origin}:{split}: empty or incorrect count")
        if len(part["sources"]) > MAX_CANDIDATE_SOURCES:
            raise CohortContractError(f"{origin}:{split}: source limit exceeded")
        for n, item in enumerate(part["sources"]):
            task_id = item.get("task_id") if isinstance(item, dict) else None
            if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
                raise CohortContractError(f"{origin}:{split}:{n}: missing or noncanonical task_id")
            if task_id in task_ids:
                raise CohortContractError(f"{origin}:{split}:{n}: duplicate task_id across source splits")
            task_ids.add(task_id)
            sources.append(_checked_image(item, f"{origin}:{split}:{n}"))
    return sources


def collision(first, second, distance):
    keys = ("source_id", "image_sha256", "decoded_rgb_sha256")
    exact = [key for key in keys if first[key] == second[key]]
    hamming = (int(first["dhash64"], 16) ^ int(second["dhash64"], 16)).bit_count()
    if hamming <= distance:
        exact.append(f"dhash64_distance_{hamming}")
    return exact


def check_cohort(candidate, history, *, max_hamming=4, require_complete_history=False):
    """Return a machine-verifiable verdict; a missing source list fails closed.

    Only *identity overlap* passes. Entity/pretraining disjointness must be
    attested independently, not inferred from hashes.
    """
    if type(max_hamming) is not int or not 0 <= max_hamming <= 64:
        raise CohortContractError("max_hamming must be an integer in [0,64]")
    new_sources = load_sources(candidate, "candidate")
    if len(new_sources) > MAX_CANDIDATE_SOURCES:
        raise CohortContractError("candidate source limit exceeded")
    if not history:
        raise CohortContractError("at least one pinned historical manifest is required")
    old_sources = []
    kinds = []
    for index, document in enumerate(history):
        part = load_sources(document, f"history:{index}", historical=True)
        old_sources.extend(part)
        kinds.append((document["schema"], len(part), document))
        if len(old_sources) > MAX_HISTORICAL_SOURCES:
            raise CohortContractError("historical source limit exceeded")
    if require_complete_history:
        if len(kinds) != 2 or {k[0] for k in kinds} != {
                "hepta.grounded-cohort.v1", "hepta.ndu.historical-exclusions.v1"}:
            raise CohortContractError("v2 requires both original v1 and historical exclusions")
        for schema, count, doc in kinds:
            if schema == "hepta.grounded-cohort.v1":
                if (count != 256 or tuple(doc["splits"][s]["count"] for s in SPLITS)
                        != V1_SPLIT_COUNTS):
                    raise CohortContractError("incomplete original v1 source roster")
            elif count != 384:
                raise CohortContractError("incomplete 384-source historical exclusions")
    if require_complete_history:
        historical_ids = [row["source_id"] for row in old_sources]
        if len(set(historical_ids)) != len(historical_ids):
            raise CohortContractError("duplicate identities in historical source roster")
    # A task key is a global score/journal join identity, not just a
    # split-local label. Reuse across source-disjoint cohorts can silently
    # alias old and new evaluation rows even when every image hash differs.
    historical_task_ids = set()
    for prior in old_sources:
        task_id = prior.get("task_id")
        if task_id is not None:
            if task_id in historical_task_ids:
                raise CohortContractError("duplicate task_id across historical cohorts")
            historical_task_ids.add(task_id)
    if any(row["task_id"] in historical_task_ids for row in new_sources):
        raise CohortContractError("candidate task_id aliases historical cohort")
    comparisons = (len(new_sources) * (len(new_sources) - 1) // 2
                   + len(new_sources) * len(old_sources))
    if comparisons > MAX_PAIR_COMPARISONS:
        raise CohortContractError("pairwise source comparison budget exceeded")
    violations = []

    def record_collision(entry, prior):
        reasons = collision(entry, prior, max_hamming)
        if reasons:
            if len(violations) >= MAX_VIOLATIONS:
                raise CohortContractError("source collision evidence limit exceeded")
            violations.append({"candidate": entry["origin"],
                               "prior": prior["origin"], "reasons": reasons})

    for n, entry in enumerate(new_sources):
        for prior in new_sources[:n]:
            record_collision(entry, prior)
        for prior in old_sources:
            record_collision(entry, prior)
    return {"schema": "hepta.ndu-cohort-firewall.v2", "status": "pass" if not violations else "fail",
            "candidate_sources": len(new_sources), "historical_sources": len(old_sources),
            "max_dhash_distance": max_hamming, "violations": violations,
            "historical_roster_shape_confirmed": bool(require_complete_history),
            "independent_history_trust_established": False,
            "observable_image_identity_disjoint": not bool(violations),
            "real_world_entity_disjointness_attested": False,
            "foundation_pretraining_contamination_excluded": False,
            "scope": "source_id/byte/RGB/dHash only; entity and pretraining claims remain unproven"}


def validate_output_destination(output, input_paths):
    """Never overwrite frozen source evidence, including aliases or links.

    Invalid output destinations cannot receive even a denial receipt. The
    caller must select a separate, ordinary path for that receipt.
    """
    try:
        if output.is_symlink():
            raise CohortContractError("output path must not be a symlink")
        if output.exists():
            if not output.is_file() or output.stat().st_nlink != 1:
                raise CohortContractError("output path must be an unlinked regular file")
        resolved_output = output.resolve(strict=False)
        for source in input_paths:
            if resolved_output == source.resolve(strict=False) or (
                output.exists() and source.exists() and output.samefile(source)
            ):
                raise CohortContractError("output path aliases frozen input evidence")
    except (OSError, RuntimeError) as error:
        raise CohortContractError("cannot verify safe output path") from error


def write_receipt_atomically(dest, result, input_paths):
    """Publish without following a late-swapped symlink or mutating a hardlink.

    A shared hostile parent directory is not a security boundary: keep inputs
    and receipts in separately trusted directories for a production run.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    validate_output_destination(dest, input_paths)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=dest.parent,
                prefix=".hepta-ndu-firewall-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(result, sort_keys=True, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        validate_output_destination(dest, input_paths)
        # rename replaces the pathname itself, not the target of a late link.
        os.replace(temporary, dest)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--historical", action="append", required=True)
    parser.add_argument("--historical-sha256", action="append", default=[],
                        help="externally pinned raw SHA256 per --historical, same order")
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-dhash-distance", type=int, default=4)
    args = parser.parse_args(argv)
    dest = Path(args.output)
    try:
        validate_output_destination(
            dest, [Path(args.candidate), *(Path(item) for item in args.historical)]
        )
    except CohortContractError as error:
        # A denial receipt cannot safely be written to an aliased output.
        print(json.dumps({"status": "fail", "error": str(error),
                          "output_written": False}, sort_keys=True))
        return 2
    try:
        # The original v2 identity firewall preregisters dHash distance <=4.
        # A caller must not weaken this floor while retaining a PASS receipt.
        # Direct check_cohort() lower thresholds remain diagnostic only.
        if not 4 <= args.max_dhash_distance <= 64:
            raise CohortContractError(
                "v2 CLI requires --max-dhash-distance between 4 and 64"
            )
        if len(args.historical) != len(args.historical_sha256):
            raise CohortContractError("each historical manifest requires an out-of-band SHA256")

        def read_bounded(path):
            # O_NONBLOCK prevents a FIFO from stalling before its type can be
            # checked. The opened descriptor, rather than a pathname stat,
            # supplies the canonical type and size of the bytes being read.
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NONBLOCK", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            with os.fdopen(os.open(path, flags), "rb") as handle:
                metadata = os.fstat(handle.fileno())
                if not stat.S_ISREG(metadata.st_mode):
                    raise CohortContractError("cohort manifest must be a regular file")
                if metadata.st_size > MAX_INPUT_BYTES:
                    raise CohortContractError("cohort manifest byte limit exceeded")
                raw = handle.read(MAX_INPUT_BYTES + 1)
            if len(raw) > MAX_INPUT_BYTES:
                raise CohortContractError("cohort manifest byte limit exceeded")
            return raw

        candidate = decode_unambiguous_json(read_bounded(args.candidate))
        history = []
        raw_histories = []
        for path, expected in zip(args.historical, args.historical_sha256):
            if not isinstance(expected, str) or not HEX256.fullmatch(expected):
                raise CohortContractError("invalid externally supplied historical SHA256")
            raw = read_bounded(path)
            if hashlib.sha256(raw).hexdigest() != expected:
                raise CohortContractError("historical SHA256 mismatch")
            history.append(decode_unambiguous_json(raw))
            raw_histories.append(raw)
        verify_frozen_history_pins(raw_histories, history)
        result = check_cohort(candidate, history,
                              max_hamming=args.max_dhash_distance,
                              require_complete_history=True)
        result["caller_pinned_historical_bytes"] = True
        result["original_frozen_histories_verified"] = True
    except (OSError, json.JSONDecodeError, CohortContractError) as exc:
        result = {"schema": "hepta.ndu-cohort-firewall.v2", "status": "fail",
                  "error": str(exc), "observable_image_identity_disjoint": False}
    try:
        write_receipt_atomically(dest, result,
                                 [Path(args.candidate), *(Path(item) for item in args.historical)])
    except (CohortContractError, OSError) as error:
        print(json.dumps({"status": "fail", "error": str(error),
                          "output_written": False}, sort_keys=True))
        return 2
    print(json.dumps({"status": result["status"], "output": str(dest)}, sort_keys=True))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
