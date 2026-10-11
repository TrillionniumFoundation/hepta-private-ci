#!/usr/bin/env python3
"""Read-only, non-authorizing gate for externally produced Hepta Neuron cohorts.

This tool verifies byte bindings, out-of-band pinned Ed25519 signatures, source
membership, split chronology and the *actual selected* no-change descriptor. It
never reads a private key, signs evidence, loads a model, or authorizes NDU,
shadow, production, or an effect. It does NOT itself re-open LedgerWriter or
verify the host's physical clock; the independent owner must do that before
signing and native ProductEvaluationRunner remains the qualification authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re

DOMAIN = b"hepta.neuron.real-cohort.attestation.v1\x00"
COHORT_SCHEMA = "hepta.neuron.real-cohort.v1"
TRUST_SCHEMA = "hepta.neuron.real-cohort.trust.v1"
ATTEST_SCHEMA = "hepta.neuron.real-cohort.attestation.v1"
REPORT_SCHEMA = "hepta.neuron.real-cohort-preflight.diagnostic.v1"
ROLES = ("ledger_owner", "observation_owner", "baseline_owner", "evaluator", "observer")
SPLITS = ("train", "calibration", "holdout", "future_1", "future_2")
SHA = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_RECORDS = 4096  # Native LedgerWriter::read_dataset_records bounded materialization.
MAX_ROWS = 4096


class InvalidCohort(ValueError):
    pass


def require(value: bool, reason: str) -> None:
    if not value:
        raise InvalidCohort(reason)


def check_sha(value: object) -> bool:
    return isinstance(value, str) and bool(SHA.fullmatch(value)) and value != "0" * 64


def check_id(value: object) -> bool:
    return isinstance(value, str) and bool(ID.fullmatch(value))


def check_time(value: object) -> bool:
    # UTC Unix microseconds, not ms or self-reported local ticks.
    return (
        type(value) is int and 1_500_000_000_000_000 <= value <= 4_000_000_000_000_000
    )


def no_dups(pairs):
    d = {}
    for k, v in pairs:
        require(k not in d, "duplicate JSON field")
        d[k] = v
    return d


def forbid_nonfinite(value):
    raise InvalidCohort("nonfinite JSON value")


def reject_float_overflow(value: object) -> object:
    if isinstance(value, float):
        require(math.isfinite(value), "numeric overflow")
    elif isinstance(value, list):
        for item in value:
            reject_float_overflow(item)
    elif isinstance(value, dict):
        for item in value.values():
            reject_float_overflow(item)
    return value


def read_json(path: Path):
    require(path.is_file() and not path.is_symlink(), "JSON must be a regular file")
    require(path.stat().st_size <= 4 * 1024 * 1024, "JSON too large")
    try:
        obj = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=no_dups,
            parse_constant=forbid_nonfinite,
        )
    except (UnicodeError, json.JSONDecodeError, OSError) as exc:
        raise InvalidCohort("invalid JSON file") from exc
    return reject_float_overflow(obj)


def canonical(obj) -> bytes:
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_trust(trust, digest):
    require(
        isinstance(trust, dict)
        and set(trust) == {"schema", "roles"}
        and trust["schema"] == TRUST_SCHEMA,
        "invalid independent trust profile",
    )
    require(
        isinstance(trust["roles"], dict) and set(trust["roles"]) == set(ROLES),
        "incomplete independent trust roles",
    )
    controllers, keys, principals = set(), set(), set()
    for role in ROLES:
        issuer = trust["roles"][role]
        require(
            isinstance(issuer, dict)
            and set(issuer)
            == {"key_id", "ed25519_public_key_hex", "controller_id", "principal_id"},
            "invalid trust issuer",
        )
        require(
            check_id(issuer["key_id"])
            and check_id(issuer["controller_id"])
            and check_id(issuer["principal_id"]),
            "unbounded trust identity",
        )
        key = issuer["ed25519_public_key_hex"]
        require(
            isinstance(key, str) and re.fullmatch("[0-9a-f]{64}", key),
            "invalid Ed25519 public key",
        )
        require(
            key not in keys
            and issuer["controller_id"] not in controllers
            and issuer["principal_id"] not in principals,
            "signing key, controller or principal reused across roles",
        )
        keys.add(key)
        controllers.add(issuer["controller_id"])
        principals.add(issuer["principal_id"])
    require(check_sha(digest), "independent trust SHA-256 required")


def observation_digest(row, family):
    if family == "heads":
        require(isinstance(row.get("features_q24"), list), "head input missing")
        return sha_bytes(canonical({"features_q24": row["features_q24"]}))
    require(
        all(
            k in row
            for k in ("state", "question", "option_order", "language", "domain")
        ),
        "semantic model observation incomplete",
    )
    return sha_bytes(
        canonical(
            {
                k: row[k]
                for k in ("state", "question", "option_order", "language", "domain")
            }
        )
    )


def validate_payload(payload, sealed_rows):
    require(
        isinstance(payload, dict)
        and set(payload)
        == {
            "schema",
            "family",
            "source",
            "dataset",
            "no_change",
            "frozen_plan_digest",
            "sealed_dataset_sha256",
            "source_current_revalidated_at_unix_micros",
            "rows",
        },
        "cohort schema mismatch",
    )
    require(
        payload["schema"] == COHORT_SCHEMA
        and payload["source"] == "hepta.learning-ledger.LedgerWriter"
        and payload["family"] in ("decisions", "multilingual", "heads"),
        "cohort origin/family not recognized",
    )
    require(
        check_sha(payload["frozen_plan_digest"])
        and check_sha(payload["sealed_dataset_sha256"]),
        "missing frozen plan or signed sealed-label byte commitment",
    )
    d = payload["dataset"]
    require(
        isinstance(d, dict)
        and set(d)
        == {
            "receipt_schema",
            "snapshot_id",
            "dataset_digest",
            "ledger_head_digest",
            "objective_digest",
            "correction_cut_digest",
            "revocation_cut_digest",
            "inclusion_policy_digest",
            "eligible_frontier",
            "outcome_watermark",
            "source_record_digests",
        },
        "DatasetSnapshotReceiptV3 fields incomplete",
    )
    require(
        d["receipt_schema"] == "DatasetSnapshotReceiptV3"
        and check_id(d["snapshot_id"]),
        "invalid dataset snapshot type",
    )
    for key in (
        "dataset_digest",
        "ledger_head_digest",
        "objective_digest",
        "correction_cut_digest",
        "revocation_cut_digest",
        "inclusion_policy_digest",
    ):
        require(check_sha(d[key]), f"missing dataset {key}")
    require(
        type(d["eligible_frontier"]) is int
        and d["eligible_frontier"] > 0
        and type(d["outcome_watermark"]) is int
        and d["outcome_watermark"] > 0,
        "invalid ledger frontier",
    )
    members = d["source_record_digests"]
    require(
        isinstance(members, list)
        and 1 <= len(members) <= MAX_RECORDS
        and all(check_sha(x) for x in members)
        and members == sorted(set(members)),
        "ledger source set must be complete bounded sorted and unique",
    )
    included = set(members)
    b = payload["no_change"]
    core = {
        "kind",
        "scope_digest",
        "objective_digest",
        "generation",
        "policy_digest",
        "route_digest",
        "checkpoint_digest",
        "runtime_receipt_digest",
        "artifact_load_receipt_digest",
        "source_use_receipt_digest",
        "frozen_at_unix_micros",
        "model_manifest_digest",
        "weights_digest",
        "code_digest",
    }
    require(isinstance(b, dict) and set(b) == core, "actual no-change tuple incomplete")
    require(
        b["kind"] in ("deployed_learned", "deployed_deterministic"),
        "no-change cannot be an arbitrary Laya test arm",
    )
    for k in (
        "scope_digest",
        "objective_digest",
        "policy_digest",
        "route_digest",
        "checkpoint_digest",
        "runtime_receipt_digest",
        "artifact_load_receipt_digest",
        "source_use_receipt_digest",
    ):
        require(check_sha(b[k]), f"missing selected no-change {k}")
    require(
        b["objective_digest"] == d["objective_digest"], "baseline objective mismatch"
    )
    require(
        type(b["generation"]) is int and b["generation"] > 0,
        "invalid production generation",
    )
    require(check_time(b["frozen_at_unix_micros"]), "baseline freeze clock required")
    if b["kind"] == "deployed_learned":
        require(
            check_sha(b["model_manifest_digest"])
            and check_sha(b["weights_digest"])
            and b["code_digest"] is None,
            "real learned no-change weights required",
        )
    else:
        require(
            check_sha(b["code_digest"])
            and b["weights_digest"] is None
            and b["model_manifest_digest"] is None,
            "deterministic no-change must be code-bound, not invented weights",
        )
    require(
        check_time(payload["source_current_revalidated_at_unix_micros"])
        and payload["source_current_revalidated_at_unix_micros"]
        > b["frozen_at_unix_micros"],
        "native source-current revalidation must postdate freeze",
    )
    rows = payload["rows"]
    require(
        isinstance(rows, list) and len(rows) > 0 and len(rows) <= MAX_ROWS,
        "source join row count out of range",
    )
    sealed = {r["id"]: r for r in sealed_rows}
    require(len(sealed) == len(sealed_rows), "duplicate sealed trial ID")
    require(len(rows) == len(sealed), "sealed/source membership mismatch")
    ids, decisions, outcomes, groups = set(), set(), set(), {s: set() for s in SPLITS}
    episode_windows = {}
    observation_windows = {}
    times = {s: [] for s in SPLITS}
    terminals = {s: [] for s in SPLITS}
    latest_terminal = 0
    required_row = {
        "id",
        "episode_id",
        "split",
        "source_group",
        "decision_record_digest",
        "terminal_outcome_record_digest",
        "observation_sha256",
        "observed_at_unix_micros",
        "terminal_at_unix_micros",
        "terminality",
    }
    for r in rows:
        require(
            isinstance(r, dict) and set(r) == required_row, "source join row incomplete"
        )
        require(
            all(check_id(r[k]) for k in ("id", "episode_id", "source_group"))
            and r["split"] in SPLITS
            and r["terminality"] == "Terminal",
            "invalid source, split or nonterminal outcome",
        )
        require(
            r["id"] not in ids
            and r["decision_record_digest"] not in decisions
            and r["terminal_outcome_record_digest"] not in outcomes,
            "duplicate trial, decision or terminal outcome",
        )
        ids.add(r["id"])
        decisions.add(r["decision_record_digest"])
        outcomes.add(r["terminal_outcome_record_digest"])
        require(
            r["decision_record_digest"] in included
            and r["terminal_outcome_record_digest"] in included,
            "decision/outcome not in frozen active ledger source set",
        )
        require(
            check_sha(r["observation_sha256"]) and r["id"] in sealed,
            "unbound source observation",
        )
        sr = sealed[r["id"]]
        require(
            sr.get("split") == r["split"]
            and sr.get("source_group") == r["source_group"]
            and observation_digest(sr, payload["family"]) == r["observation_sha256"],
            "observable source not joined to exact sealed model input",
        )
        start, end = r["observed_at_unix_micros"], r["terminal_at_unix_micros"]
        require(
            check_time(start) and check_time(end) and start <= end,
            "invalid terminal outcome ordering",
        )
        require(
            sr.get("observed_at_ms") == start // 1000,
            "observation time unit mismatch (ms vs Unix micros)",
        )
        if r["split"].startswith("future_"):
            require(
                start > b["frozen_at_unix_micros"],
                "future event predates baseline freeze",
            )
        else:
            require(
                start < b["frozen_at_unix_micros"],
                "training/calibration/holdout leaked post-freeze",
            )
        previous = episode_windows.setdefault(r["episode_id"], r["split"])
        require(previous == r["split"], "correlated episode crosses dataset windows")
        previous_observation = observation_windows.setdefault(
            r["observation_sha256"], r["split"]
        )
        require(
            previous_observation == r["split"],
            "identical model input leaks across split boundaries",
        )
        groups[r["split"]].add(r["source_group"])
        times[r["split"]].append(start)
        terminals[r["split"]].append(end)
        latest_terminal = max(latest_terminal, end)
    require(ids == set(sealed), "sealing and source membership inconsistent")
    require(
        all(groups[x] for x in ("calibration", "holdout", "future_1", "future_2")),
        "each evaluation window requires observed rows",
    )
    # Prohibit source groups crossing split boundaries, even if IDs differ.
    for i, split in enumerate(SPLITS):
        for other in SPLITS[i + 1 :]:
            require(
                not groups[split].intersection(groups[other]),
                "correlated source group leaked across splits",
            )
    for earlier, later in (
        ("train", "calibration"),
        ("calibration", "holdout"),
        ("holdout", "future_1"),
        ("future_1", "future_2"),
    ):
        if terminals[earlier] and times[later]:
            require(
                max(terminals[earlier]) < min(times[later]),
                f"{earlier}/{later} observation or terminal window overlaps",
            )
    require(
        payload["source_current_revalidated_at_unix_micros"] >= latest_terminal,
        "ledger current proof predates terminal outcomes",
    )
    return {s: len(times[s]) for s in SPLITS}, latest_terminal


def verify_attestations(packet, trust, latest_terminal, revalidated):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    attest = packet["attestations"]
    require(
        isinstance(attest, dict) and set(attest) == set(ROLES),
        "missing independently pinned role attestations",
    )
    body_sha = sha_bytes(canonical(packet["payload"]))
    result = {}
    for role in ROLES:
        record = attest[role]
        require(
            isinstance(record, dict)
            and set(record)
            == {
                "schema",
                "role",
                "key_id",
                "body_sha256",
                "signed_at_unix_micros",
                "signature_ed25519_hex",
            },
            "attestation has missing or unexpected fields",
        )
        issuer = trust["roles"][role]
        require(
            record["schema"] == ATTEST_SCHEMA
            and record["role"] == role
            and record["key_id"] == issuer["key_id"]
            and record["body_sha256"] == body_sha
            and check_time(record["signed_at_unix_micros"]),
            "signature does not bind exact role and payload",
        )
        require(
            record["signed_at_unix_micros"] >= revalidated,
            "attestation predates native ledger-current revalidation",
        )
        if role == "observer":
            require(
                record["signed_at_unix_micros"] >= latest_terminal,
                "observer signature predates future observations",
            )
        hexsig = record["signature_ed25519_hex"]
        require(
            isinstance(hexsig, str) and bool(re.fullmatch("[0-9a-f]{128}", hexsig)),
            "Ed25519 signature missing",
        )
        body = {k: v for k, v in record.items() if k != "signature_ed25519_hex"}
        try:
            pub = Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(issuer["ed25519_public_key_hex"])
            )
            pub.verify(bytes.fromhex(hexsig), DOMAIN + canonical(body))
        except (InvalidSignature, ValueError) as exc:
            raise InvalidCohort(f"invalid {role} signature") from exc
        result[role] = sha_bytes(DOMAIN + canonical(body))
    return result


def read_sealed(path: Path):
    require(
        path.is_file()
        and not path.is_symlink()
        and path.stat().st_size <= 10 * 1024 * 1024,
        "sealed dataset must be a bounded regular file",
    )
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            require(len(rows) < MAX_ROWS, "sealed row cap exceeded")
            try:
                value = json.loads(
                    line, object_pairs_hook=no_dups, parse_constant=forbid_nonfinite
                )
            except (ValueError, UnicodeError) as exc:
                raise InvalidCohort("invalid sealed row") from exc
            reject_float_overflow(value)
            require(
                isinstance(value, dict) and check_id(value.get("id")),
                "invalid trial ID",
            )
            rows.append(value)
    return rows


def verify(
    cohort_path: Path, sealed_path: Path, trust_path: Path, expected_trust_sha: str
):
    cohort_path = Path(cohort_path)
    sealed_path = Path(sealed_path)
    trust_path = Path(trust_path)
    require(
        trust_path.resolve() != cohort_path.resolve()
        and trust_path.resolve() != sealed_path.resolve(),
        "independent trust root cannot be supplied as the dataset",
    )
    require(
        check_sha(expected_trust_sha)
        and sha_bytes(trust_path.read_bytes()) == expected_trust_sha,
        "trust root did not match independent SHA-256 pin",
    )
    trust = read_json(trust_path)
    validate_trust(trust, expected_trust_sha)
    packet = read_json(cohort_path)
    require(
        isinstance(packet, dict)
        and set(packet) == {"schema", "payload", "attestations"}
        and packet["schema"] == COHORT_SCHEMA,
        "invalid cohort envelope",
    )
    rows = read_sealed(sealed_path)
    require(
        packet["payload"].get("sealed_dataset_sha256")
        == sha_bytes(sealed_path.read_bytes()),
        "sealed labels or row bytes changed after signed freeze",
    )
    counts, latest_terminal = validate_payload(packet["payload"], rows)
    signers = verify_attestations(
        packet,
        trust,
        latest_terminal,
        packet["payload"]["source_current_revalidated_at_unix_micros"],
    )
    return {
        "schema": REPORT_SCHEMA,
        "status": "structurally_valid_signed_diagnostic_only",
        "cohort_sha256": sha_bytes(cohort_path.read_bytes()),
        "sealed_sha256": sha_bytes(sealed_path.read_bytes()),
        "trust_sha256": expected_trust_sha,
        "ledger_dataset_digest": packet["payload"]["dataset"]["dataset_digest"],
        "production_baseline_kind": packet["payload"]["no_change"]["kind"],
        "row_counts_by_split": counts,
        "verified_role_signature_count": len(signers),
        "signer_payload_commitments": signers,
        "note": "Cryptographic role signatures attest claims; this tool cannot validate physical ledger, source-use permission, observation truth, independent hosts, elapsed windows, or NDU impact.",
        "actual_ledger_owner_queried": False,
        "physical_data_origin_independently_verified": False,
        "production_no_change_observed_by_this_process": False,
        "future_calendar_independently_verified": False,
        "ndu_net_gain_verified": False,
        "selection_authorized": False,
        "production_promotion_authorized": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cohort", type=Path, required=True)
    p.add_argument("--sealed", type=Path, required=True)
    p.add_argument("--trusted-issuers", type=Path, required=True)
    p.add_argument("--trust-sha256", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    try:
        require(
            a.output.is_absolute() and not a.output.exists(),
            "output must be a new absolute path",
        )
        report = verify(a.cohort, a.sealed, a.trusted_issuers, a.trust_sha256)
        with a.output.open("x", encoding="utf-8") as f:
            json.dump(report, f, sort_keys=True, separators=(",", ":"), allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
    except (InvalidCohort, OSError, ValueError, TypeError, KeyError) as e:
        p.exit(2, f"blocked: {e}\n")


if __name__ == "__main__":
    main()
