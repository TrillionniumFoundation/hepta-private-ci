"""Check exact original-document group reuse against pinned prior manifests.

Only detects reuse of IDs in supplied records; not scientific qualification.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

ROLES = ("train", "dev", "confirmation")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError("non-finite JSON constant: " + value)


def read_manifest(path, expected=None):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "invalid manifest path")
    size = path.stat().st_size
    require(0 < size <= 4 * 1024 * 1024, "manifest byte limit")
    raw = path.read_bytes()
    require(len(raw) == size, "manifest changed during read")
    digest = hashlib.sha256(raw).hexdigest()
    if expected is not None:
        require(
            type(expected) is str and HEX64.fullmatch(expected), "invalid prior pin"
        )
        require(digest == expected, "prior manifest byte hash mismatch")
    value = json.loads(
        raw, object_pairs_hook=strict_pairs, parse_constant=reject_constant
    )
    require(
        type(value) is dict and value.get("schema") == "perc1.manifest.v1",
        "manifest schema",
    )
    splits = value.get("splits")
    require(type(splits) is dict and set(splits) == set(ROLES), "split inventory")
    seen, by_role = set(), {}
    for role in ROLES:
        values = splits[role]
        require(type(values) is list and values, "empty split")
        require(
            all(type(v) is str and HEX64.fullmatch(v) for v in values),
            "group must be 64-hex original-document digest",
        )
        groups = set(values)
        require(len(groups) == len(values), "duplicate group")
        require(not seen.intersection(groups), "group crosses split")
        seen.update(groups)
        by_role[role] = groups
    return digest, by_role


def audit(candidate, priors):
    require(type(priors) is list and priors, "missing prior manifest pins")
    candidate_sha, candidate_roles = read_manifest(candidate)
    old, prior_info, prior_paths = {}, [], set()
    for index, entry in enumerate(priors):
        require(type(entry) in (list, tuple) and len(entry) == 2, "prior pin pair")
        path, pin = entry
        key = str(Path(path).resolve())
        require(key not in prior_paths, "duplicate prior manifest path")
        prior_paths.add(key)
        digest, roles = read_manifest(path, pin)
        prior_info.append(
            {
                "index": index,
                "file_sha256": digest,
                "counts": {r: len(roles[r]) for r in ROLES},
            }
        )
        for role, groups in roles.items():
            for group in groups:
                old.setdefault(group, []).append((index, role))
    reuse = [
        {
            "group_sha256": group,
            "candidate_role": role,
            "prior_index": i,
            "prior_role": old_role,
        }
        for role in ROLES
        for group in sorted(candidate_roles[role])
        for i, old_role in old.get(group, ())
    ]
    return {
        "schema": "perc1.source-reuse-audit.v1",
        "status": "HOLD_REUSED_SOURCE" if reuse else "PASS_GROUP_REUSE_CHECK_ONLY",
        "candidate_sha256": candidate_sha,
        "candidate_counts": {r: len(candidate_roles[r]) for r in ROLES},
        "prior_manifests": prior_info,
        "previously_seen_groups": len(old),
        "overlap": reuse,
        "scientific_qualified": False,
        "production_qualified": False,
        "origin_group_mapping_attested": False,
        "prior_registry_complete": False,
        "template_and_organization_independence_verified": False,
        "training_independence_verified": False,
        "evaluator_secrecy_verified": False,
        "preregistration_verified": False,
        "claim_scope": "exact source IDs in the provided pinned prior manifests only",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument(
        "--prior", nargs=2, action="append", required=True, metavar=("PATH", "SHA256")
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.candidate, args.prior)
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        require(not args.output.exists(), "refuse to overwrite an audit")
        args.output.write_text(serialized, encoding="utf8")
    print(serialized, end="")
    return 2 if report["overlap"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
