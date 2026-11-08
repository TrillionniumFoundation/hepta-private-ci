"""Read-only coverage audit for pinned NDU material metadata.

This command reads registry/catalog/exposure metadata, never task packets,
references, images, model weights, or answers. A consistent metadata graph does
not authenticate its upstream source owner, establish independent task domains,
prove statistical power, or release confirmation. Existing records are not
rewritten, relabeled, or excluded from their historical denominator.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys


FAMILIES = (
    "text_sufficient",
    "text_image_complementary",
    "selective_refinement",
    "preparation_required",
    "continuation_not_worthwhile",
)
ROLES = (
    "train",
    "development",
    "confirmation",
    "retention_validation",
    "retention_test",
)
SELECTION_ROLES = {
    "training": "train",
    "tuning": "train",
    "pilot_new": "development",
    "pilot_retention": "retention_validation",
}
MAX_METADATA_BYTES = 32 * 1024 * 1024
HEX = re.compile(r"[0-9a-f]{64}\Z")


class MetadataError(ValueError):
    """A pinned input cannot be interpreted under its declared metadata schema."""


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise MetadataError("duplicate JSON object key")
            result[key] = value
        return result

    def constant(_value):
        raise MetadataError("nonfinite JSON number")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise MetadataError("invalid UTF-8 JSON metadata") from error


def _require(condition, message):
    if not condition:
        raise MetadataError(message)


def _object(value, required, label, *, exact=False):
    _require(
        isinstance(value, dict) and set(required) <= set(value),
        label + " missing required fields",
    )
    _require(not exact or set(value) == set(required), label + " has unknown fields")


def _identity(value, label):
    _require(
        isinstance(value, str)
        and 0 < len(value) <= 512
        and all(ord(char) >= 32 for char in value),
        label + " is not a bounded identity",
    )
    return value


def _sha(value, label):
    _require(
        isinstance(value, str) and HEX.fullmatch(value), label + " is not a SHA-256"
    )
    return value


def _integer(value, label):
    _require(type(value) is int and value >= 0, label + " is not a nonnegative integer")
    return value


def _identities(value, label):
    _require(isinstance(value, list), label + " is not an array")
    values = [_identity(item, label) for item in value]
    _require(len(values) == len(set(values)), label + " contains duplicates")
    return values


def _hashes(value, label):
    values = _identities(value, label)
    for item in values:
        _sha(item, label)
    return values


def _binding(value, label):
    _object(value, ("path", "sha256", "bytes"), label, exact=True)
    path = _identity(value["path"], label + " path")
    _require(
        not path.startswith("/")
        and "\\" not in path
        and all(part not in {"", ".", ".."} for part in path.split("/")),
        label + " path is not canonical relative metadata",
    )
    _sha(value["sha256"], label + " hash")
    _integer(value["bytes"], label + " bytes")


def read_pinned(path, expected_sha256):
    """Read bounded stable bytes and compare an independently supplied exact pin."""
    _sha(expected_sha256, "expected input pin")
    path = Path(path)
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode), "metadata input is not a regular file")
        _require(
            before.st_size <= MAX_METADATA_BYTES,
            "metadata input exceeds the bounded profile",
        )
        blocks, size = [], 0
        while True:
            block = os.read(descriptor, min(65536, MAX_METADATA_BYTES + 1 - size))
            if not block:
                break
            blocks.append(block)
            size += len(block)
            _require(
                size <= MAX_METADATA_BYTES, "metadata grew beyond the bounded profile"
            )
        after = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
    finally:
        os.close(descriptor)
    identity = lambda value: (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )
    _require(
        identity(before) == identity(after) == identity(named),
        "metadata input changed during read",
    )
    raw = b"".join(blocks)
    observed = hashlib.sha256(raw).hexdigest()
    _require(
        observed == expected_sha256, "metadata input does not match its supplied pin"
    )
    return strict_json(raw), {
        "sha256": observed,
        "bytes": len(raw),
        "stable_read": True,
    }


def audit_coverage(
    registry,
    catalog,
    exposure,
    *,
    input_bindings,
    registration=None,
    selected_sources=None,
):
    """Reconcile an exact full catalog against registry v2 and later exposures.

    The pure function accepts already parsed metadata. Only ``read_pinned`` and
    the CLI verify actual file bytes; no supplied hash is native authentication.
    """
    report = {
        "schema": "ndu.real.material-coverage.v1",
        "input_bindings": input_bindings,
        "metadata_consistent": False,
        "requested_scope_complete": False,
        "status": "METADATA_REJECTED",
        "issues": [],
        "coverage_gaps": [],
        "scientific_admission": "HOLD",
        "confirmation_release": False,
        "native_owner_authentication": "SEPARATE_REQUIRED",
        "authenticated_source_origin": "NOT_ESTABLISHED",
        "independent_task_domains": "NOT_ESTABLISHED",
        "read_scope": "Pinned metadata only; no reference contents, answers, task packets, images, or weights",
        "limits": [
            "Metadata source groups do not prove causal or statistical independence.",
            "All five workflow labels can belong to one source domain.",
            "A preallocated retention panel is not evidence that historic abilities were retained.",
            "Exposure counters are declarations, not authenticated actor or evaluator access logs.",
            "Shared instruction text is not treated as an independent source or as a source-content alias.",
            "No power, model quality, native owner authority, or confirmation admission is established.",
        ],
    }

    def issue(code, **details):
        report["issues"].append({"code": code, **details})

    try:
        _object(input_bindings, ("registry", "catalog", "exposure"), "input bindings")
        for name, value in input_bindings.items():
            _sha(value["sha256"], name + " supplied hash")
        _object(registry, ("schema", "sources"), "registry", exact=True)
        _require(
            registry["schema"] == "hepta.source-use-registry.v2",
            "registry v2 is required",
        )
        _require(
            isinstance(registry["sources"], list), "registry sources is not an array"
        )
        _object(catalog, ("cases",), "full catalog", exact=True)
        _require(isinstance(catalog["cases"], list), "catalog cases is not an array")
        _object(
            exposure,
            ("schema", "registry_sha256", "quarantined_source_groups", "matches"),
            "exposure ledger",
        )
        _require(
            exposure["schema"] == "ndu.real.researcher-exposure.v1",
            "unsupported exposure ledger",
        )
        _require(
            exposure["registry_sha256"] == input_bindings["registry"]["sha256"],
            "exposure pins another registry",
        )

        sources, registered_cases = {}, {}
        source_fields = (
            "source_id",
            "source_family",
            "allowed_split",
            "text_sha256s",
            "image_sha256s",
            "source_evidence_sha256",
            "used_in_training",
            "previously_observed",
            "case_bindings",
        )
        case_binding_fields = (
            "case_id",
            "task_family",
            "text_sha256",
            "image_sha256",
            "reference_sha256",
        )
        for source in registry["sources"]:
            _object(source, source_fields, "source record", exact=True)
            sid = _identity(source["source_id"], "source ID")
            _require(sid not in sources, "duplicate source ID")
            _identity(source["source_family"], "source family")
            _require(
                source["allowed_split"]
                in {"train", "development", "confirmation", "retention"},
                "unknown registry split",
            )
            _require(
                type(source["used_in_training"]) is bool
                and type(source["previously_observed"]) is bool,
                "source exposure fields must be booleans",
            )
            text_hashes = set(_hashes(source["text_sha256s"], "source text hashes"))
            image_hashes = set(_hashes(source["image_sha256s"], "source image hashes"))
            _sha(source["source_evidence_sha256"], "source evidence")
            _require(
                isinstance(source["case_bindings"], list),
                "source case bindings is not an array",
            )
            for bound in source["case_bindings"]:
                _object(bound, case_binding_fields, "registered case", exact=True)
                cid = _identity(bound["case_id"], "case ID")
                _require(
                    cid not in registered_cases, "case is registered more than once"
                )
                _require(
                    bound["task_family"] in FAMILIES, "unknown registered task family"
                )
                for key in ("text_sha256", "image_sha256", "reference_sha256"):
                    _sha(bound[key], "case " + key)
                _require(
                    bound["text_sha256"] in text_hashes
                    and bound["image_sha256"] in image_hashes,
                    "case content hashes are absent from their registered source",
                )
                registered_cases[cid] = (sid, bound)
            sources[sid] = source

        cases, roles_by_source, episodes, case_role_counts = (
            {},
            defaultdict(set),
            defaultdict(set),
            Counter(),
        )
        families_by_source, families_by_episode = defaultdict(set), defaultdict(set)
        case_families = {role: Counter() for role in ROLES}
        aliases = defaultdict(lambda: defaultdict(set))
        triples = set()
        for case in catalog["cases"]:
            _object(
                case,
                (
                    "id",
                    "source_id",
                    "role",
                    "task_family",
                    "packet",
                    "reference",
                    "episode_group",
                ),
                "catalog case",
                exact=True,
            )
            cid, sid = (
                _identity(case["id"], "catalog case ID"),
                _identity(case["source_id"], "catalog source ID"),
            )
            _require(cid not in cases, "duplicate catalog case ID")
            _require(
                sid in sources and cid in registered_cases,
                "catalog case lacks a registered source binding",
            )
            role, family = case["role"], case["task_family"]
            _require(
                role in ROLES and family in FAMILIES,
                "unknown catalog role or task family",
            )
            episode = _identity(case["episode_group"], "episode group")
            _binding(case["packet"], "packet")
            _binding(case["reference"], "reference")
            registered_source, bound = registered_cases[cid]
            if (
                registered_source != sid
                or family != bound["task_family"]
                or case["reference"]["sha256"] != bound["reference_sha256"]
            ):
                issue("catalog_registry_binding_mismatch", case_id=cid)
            expected_split = "retention" if role.startswith("retention_") else role
            if sources[sid]["allowed_split"] != expected_split:
                issue("catalog_registry_role_mismatch", source_id=sid, role=role)
            triple = (sid, episode, family)
            _require(triple not in triples, "duplicate source/episode/family case")
            triples.add(triple)
            cases[cid] = case
            roles_by_source[sid].add(role)
            episodes[episode].add((sid, role))
            families_by_source[(sid, role)].add(family)
            families_by_episode[(sid, episode, role)].add(family)
            case_role_counts[role] += 1
            case_families[role][family] += 1
            for kind in ("packet", "reference"):
                for field in ("path", "sha256"):
                    aliases[kind + "_" + field][case[kind][field]].add(cid)
        if set(cases) != set(registered_cases):
            issue(
                "full_catalog_not_closed",
                missing_cases=len(set(registered_cases) - set(cases)),
            )
        for sid, roles in roles_by_source.items():
            if len(roles) != 1:
                issue("source_crosses_exact_roles", source_id=sid, roles=sorted(roles))
        for episode, owners in episodes.items():
            if len(owners) != 1:
                issue(
                    "episode_crosses_source_or_role",
                    episode_group=episode,
                    owners=[list(value) for value in sorted(owners)],
                )
        for kind, values in aliases.items():
            for value, identities in values.items():
                if len(identities) > 1:
                    issue(
                        "case_metadata_alias",
                        alias_kind=kind,
                        case_count=len(identities),
                        alias_sha256=hashlib.sha256(value.encode()).hexdigest(),
                    )

        quarantine = set(
            _identities(exposure["quarantined_source_groups"], "quarantine")
        )
        _require(quarantine <= set(sources), "quarantine names an unregistered source")
        source_aliases, prompt_aliases = (
            defaultdict(lambda: defaultdict(set)),
            defaultdict(set),
        )
        for sid, source in sources.items():
            roles = roles_by_source[sid]
            if source["used_in_training"] and source["allowed_split"] != "train":
                issue("trained_source_in_evaluation_split", source_id=sid)
            if (
                source["previously_observed"]
                and source["allowed_split"] != "train"
                and sid not in quarantine
            ):
                issue("previously_observed_source_not_quarantined", source_id=sid)
            source_aliases["source_evidence"][source["source_evidence_sha256"]].add(sid)
            case_text = {bound["text_sha256"] for bound in source["case_bindings"]}
            # Registry v2 mixes generic instruction hashes and source transcripts.
            # Residual text hashes are source transcripts in the actual registrar;
            # text_sufficient case inputs additionally include actual transcripts.
            for value in set(source["text_sha256s"]) - case_text:
                source_aliases["source_transcript"][value].add(sid)
            for bound in source["case_bindings"]:
                if bound["task_family"] == "text_sufficient":
                    source_aliases["text_sufficient_input"][bound["text_sha256"]].add(
                        sid
                    )
                else:
                    prompt_aliases[bound["text_sha256"]].add(sid)
            for value in source["image_sha256s"]:
                source_aliases["source_or_public_image"][value].add(sid)
        for kind, values in source_aliases.items():
            for value, owners in values.items():
                if len(owners) > 1:
                    issue(
                        "source_content_alias",
                        alias_kind=kind,
                        content_sha256=value,
                        source_ids=sorted(owners),
                    )

        _require(
            isinstance(exposure["matches"], list), "exposure matches is not an array"
        )
        matched_sources = set()
        for match in exposure["matches"]:
            _object(
                match,
                (
                    "source_group",
                    "role",
                    "episode_groups",
                    "source_evidence_sha256",
                    "all_group_case_count",
                ),
                "exposure match",
            )
            sid, role = match["source_group"], match["role"]
            _require(sid in sources and role in ROLES, "unknown exposed source or role")
            _require(sid not in matched_sources, "duplicate exposed source match")
            matched_sources.add(sid)
            seen_episodes = set(
                _identities(match["episode_groups"], "exposed episodes")
            )
            actual_episodes = {
                case["episode_group"]
                for case in cases.values()
                if case["source_id"] == sid
            }
            if (
                roles_by_source[sid] != {role}
                or not seen_episodes <= actual_episodes
                or match["source_evidence_sha256"]
                != sources[sid]["source_evidence_sha256"]
                or _integer(match["all_group_case_count"], "exposed case count")
                != sum(case["source_id"] == sid for case in cases.values())
            ):
                issue("exposure_catalog_binding_mismatch", source_id=sid)
            if role != "train" and sid not in quarantine:
                issue(
                    "exposed_evaluation_source_not_quarantined",
                    source_id=sid,
                    role=role,
                )

        groups_by_role = {
            role: {sid for sid, roles in roles_by_source.items() if role in roles}
            for role in ROLES
        }
        for key, role in (
            ("quarantined_confirmation_source_groups", "confirmation"),
            ("excluded_pilot_new_source_groups", "development"),
        ):
            if (
                key in exposure
                and set(_identities(exposure[key], key))
                != quarantine & groups_by_role[role]
            ):
                issue("exposure_quarantine_projection_mismatch", field=key)
        future_counts = {
            role: len(groups_by_role[role] - quarantine)
            for role in ("confirmation", "retention_test")
        }
        if (
            "available_future_source_groups" in exposure
            and exposure["available_future_source_groups"] != future_counts
        ):
            issue("exposure_future_count_mismatch")

        if registration is not None:
            _object(input_bindings, ("registration",), "registration input pin")
            _object(
                registration,
                (
                    "schema",
                    "registry_sha256",
                    "case_counts",
                    "source_group_counts",
                    "merchant_groups",
                    "eligible_receipts",
                    "excluded_receipts",
                    "original_receipts",
                ),
                "registration",
            )
            _require(
                registration["schema"] == "ndu.real.registration.v1",
                "unsupported registration schema",
            )
            if registration["registry_sha256"] != input_bindings["registry"]["sha256"]:
                issue("registration_registry_pin_mismatch")
            if (
                exposure.get("registration_sha256")
                != input_bindings["registration"]["sha256"]
            ):
                issue("exposure_registration_pin_mismatch")
            expected_counts = {role: case_role_counts[role] for role in ROLES}
            if registration["case_counts"] != expected_counts or registration[
                "source_group_counts"
            ] != {role: len(groups_by_role[role]) for role in ROLES}:
                issue("registration_counts_mismatch")
            if (
                _integer(registration["merchant_groups"], "merchant count")
                != len(sources)
                or _integer(registration["eligible_receipts"], "eligible count")
                != len(episodes)
                or _integer(registration["original_receipts"], "receipt count")
                != registration["eligible_receipts"]
                + _integer(registration["excluded_receipts"], "excluded count")
            ):
                issue("registration_source_denominator_mismatch")

        if selected_sources is not None:
            _object(input_bindings, ("selected_sources",), "selected sources input pin")
            _object(
                selected_sources,
                ("schema", "groups", "cases"),
                "selected sources",
                exact=True,
            )
            _require(
                selected_sources["schema"] == "ndu.real.selected-sources.v1",
                "unsupported selected source schema",
            )
            _object(
                selected_sources["groups"],
                SELECTION_ROLES,
                "selected groups",
                exact=True,
            )
            _object(
                selected_sources["cases"], SELECTION_ROLES, "selected cases", exact=True
            )
            all_selected = set()
            for panel, role in SELECTION_ROLES.items():
                group_ids = set(
                    _identities(selected_sources["groups"][panel], "selected group IDs")
                )
                if not group_ids <= groups_by_role[role] or group_ids & all_selected:
                    issue("selected_sources_cross_role_or_panel", panel=panel)
                if role != "train" and group_ids & quarantine:
                    issue(
                        "quarantined_source_selected",
                        panel=panel,
                        source_count=len(group_ids & quarantine),
                    )
                all_selected |= group_ids
                rows = selected_sources["cases"][panel]
                _require(isinstance(rows, list), "selected cases is not an array")
                seen, chosen = set(), defaultdict(list)
                for case in rows:
                    _require(
                        isinstance(case, dict) and "id" in case, "invalid selected case"
                    )
                    cid = case["id"]
                    if cid in seen or cid not in cases or case != cases[cid]:
                        issue("selected_case_not_exact_catalog_row", panel=panel)
                        continue
                    seen.add(cid)
                    chosen[case["source_id"]].append(case)
                if set(chosen) != group_ids:
                    issue("selected_group_roster_incomplete", panel=panel)
                for sid, values in chosen.items():
                    if (
                        len({row["episode_group"] for row in values}) != 1
                        or any(row["role"] != role for row in values)
                        or {row["task_family"] for row in values}
                        != (
                            {"text_image_complementary"}
                            if panel == "pilot_retention"
                            else set(FAMILIES)
                        )
                    ):
                        issue(
                            "selected_original_panel_coverage_mismatch",
                            panel=panel,
                            source_id=sid,
                        )
            report["selected_source_group_counts"] = {
                name: len(values) for name, values in selected_sources["groups"].items()
            }

        family_source_counts, family_episode_counts = {}, {}
        for role in ROLES:
            family_source_counts[role] = {}
            family_episode_counts[role] = {}
            for family in FAMILIES:
                source_count = sum(
                    family in values
                    for (sid, row_role), values in families_by_source.items()
                    if row_role == role
                )
                episode_count = sum(
                    family in values
                    for (sid, episode, row_role), values in families_by_episode.items()
                    if row_role == role
                )
                family_source_counts[role][family] = source_count
                family_episode_counts[role][family] = episode_count
                total_episodes = sum(
                    row_role == role for (sid, episode, row_role) in families_by_episode
                )
                if (
                    not groups_by_role[role]
                    or source_count != len(groups_by_role[role])
                    or episode_count != total_episodes
                ):
                    report["coverage_gaps"].append(
                        {
                            "role": role,
                            "task_family": family,
                            "source_groups_with_family": source_count,
                            "source_groups_total": len(groups_by_role[role]),
                            "episode_groups_with_family": episode_count,
                            "episode_groups_total": total_episodes,
                            "classification": "requested_five_family_scope_not_covered",
                        }
                    )
        report.update(
            registered_sources=len(sources),
            registered_cases=len(registered_cases),
            catalog_cases=len(cases),
            eligible_episode_groups=len(episodes),
            source_group_counts={role: len(groups_by_role[role]) for role in ROLES},
            case_counts={role: case_role_counts[role] for role in ROLES},
            family_case_counts={role: dict(case_families[role]) for role in ROLES},
            family_source_group_counts=family_source_counts,
            family_episode_group_counts=family_episode_counts,
            source_family_counts=dict(
                Counter(source["source_family"] for source in sources.values())
            ),
            shared_instruction_hashes_across_sources=sum(
                len(owners) > 1 for owners in prompt_aliases.values()
            ),
            quarantine_source_groups_by_role={
                role: len(groups_by_role[role] & quarantine) for role in ROLES
            },
            available_future_source_groups=future_counts,
            text_alias_scope="Registry v2 residual transcripts and text_sufficient case inputs checked; shared instruction-only hashes disclosed separately",
        )
        report["metadata_consistent"] = not report["issues"]
        report["requested_scope_complete"] = (
            report["metadata_consistent"] and not report["coverage_gaps"]
        )
        if report["metadata_consistent"]:
            report["status"] = (
                "METADATA_CONSISTENT"
                if report["requested_scope_complete"]
                else "METADATA_CONSISTENT_SCOPE_INCOMPLETE"
            )
    except (MetadataError, KeyError, TypeError) as error:
        issue("malformed_or_unbound_metadata", detail=str(error))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("registry", "catalog", "exposure", "registration", "selected_sources"):
        flag = name.replace("_", "-")
        required = name in {"registry", "catalog", "exposure"}
        parser.add_argument("--" + flag, type=Path, required=required)
        parser.add_argument("--" + flag + "-sha256", required=required)
    parser.add_argument(
        "--require-requested-scope",
        action="store_true",
        help="Exit 3 for structurally consistent but incomplete five-family retention coverage",
    )
    args = parser.parse_args(argv)
    try:
        documents, bindings = {}, {}
        for name in (
            "registry",
            "catalog",
            "exposure",
            "registration",
            "selected_sources",
        ):
            path, pin = getattr(args, name), getattr(args, name + "_sha256")
            _require(
                (path is None) == (pin is None),
                "optional metadata path and exact pin must be supplied together",
            )
            if path is not None:
                documents[name], bindings[name] = read_pinned(path, pin)
        report = audit_coverage(
            documents["registry"],
            documents["catalog"],
            documents["exposure"],
            input_bindings=bindings,
            registration=documents.get("registration"),
            selected_sources=documents.get("selected_sources"),
        )
    except (OSError, MetadataError, ValueError) as error:
        report = {
            "schema": "ndu.real.material-coverage.v1",
            "status": "METADATA_REJECTED",
            "metadata_consistent": False,
            "requested_scope_complete": False,
            "scientific_admission": "HOLD",
            "confirmation_release": False,
            "issues": [{"code": "pinned_input_read_failed", "detail": str(error)}],
        }
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    if not report["metadata_consistent"]:
        return 2
    return (
        3
        if args.require_requested_scope and not report["requested_scope_complete"]
        else 0
    )


if __name__ == "__main__":
    sys.exit(main())
