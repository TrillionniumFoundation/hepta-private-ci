"""Fail-closed v2 cohort isolation against v1 and earlier image histories.

The historical input may be a regular hepta.grounded-cohort manifest or the
hepta.ndu.historical-exclusions wrapper. This checks observable identities
only; it cannot attest real-world entity overlap or base-model pretraining.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

HEX256 = re.compile(r"^[0-9a-f]{64}$")
HEX64 = re.compile(r"^[0-9a-f]{16}$")
SPLITS = ("train", "dev", "calibration", "test")
V1_SPLIT_COUNTS = (128, 32, 32, 64)
MAX_CANDIDATE_SOURCES = 2048
MAX_HISTORICAL_SOURCES = 4096
MAX_PAIR_COMPARISONS = 2_000_000
MAX_VIOLATIONS = 4096
MAX_INPUT_BYTES = 16 * 1024 * 1024


class CohortContractError(ValueError):
    pass


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
    for split in SPLITS:
        part = splits[split]
        if not isinstance(part, dict) or not isinstance(part.get("sources"), list):
            raise CohortContractError(f"{origin}:{split}: malformed source list")
        if type(part.get("count")) is not int or part["count"] != len(part["sources"]) or not part["sources"]:
            raise CohortContractError(f"{origin}:{split}: empty or incorrect count")
        if len(part["sources"]) > MAX_CANDIDATE_SOURCES:
            raise CohortContractError(f"{origin}:{split}: source limit exceeded")
        for n, item in enumerate(part["sources"]):
            if not isinstance(item, dict) or not isinstance(item.get("task_id"), str) or not item["task_id"]:
                raise CohortContractError(f"{origin}:{split}:{n}: missing task_id")
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
        if len(args.historical) != len(args.historical_sha256):
            raise CohortContractError("each historical manifest requires an out-of-band SHA256")

        def read_bounded(path):
            file = Path(path)
            if file.stat().st_size > MAX_INPUT_BYTES:
                raise CohortContractError("cohort manifest byte limit exceeded")
            raw = file.read_bytes()
            if len(raw) > MAX_INPUT_BYTES:
                raise CohortContractError("cohort manifest byte limit exceeded")
            return raw

        candidate = json.loads(read_bounded(args.candidate))
        history = []
        for path, expected in zip(args.historical, args.historical_sha256):
            if not isinstance(expected, str) or not HEX256.fullmatch(expected):
                raise CohortContractError("invalid externally supplied historical SHA256")
            raw = read_bounded(path)
            if hashlib.sha256(raw).hexdigest() != expected:
                raise CohortContractError("historical SHA256 mismatch")
            history.append(json.loads(raw))
        result = check_cohort(candidate, history,
                              max_hamming=args.max_dhash_distance,
                              require_complete_history=True)
        result["caller_pinned_historical_bytes"] = True
    except (OSError, json.JSONDecodeError, CohortContractError) as exc:
        result = {"schema": "hepta.ndu-cohort-firewall.v2", "status": "fail",
                  "error": str(exc), "observable_image_identity_disjoint": False}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "output": str(dest)}, sort_keys=True))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
