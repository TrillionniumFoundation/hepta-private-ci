"""Fail-closed P0-P7 research evidence audit; never grants runtime authority.

This validates submitted *data consistency*, not authenticity, model quality,
causal NDU benefit, production fitness, or an independent evaluator's signature.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import statistics
import sys

ARMS = ("base", "static", "moe", "router", "best_of_2", "risk_neutral_mpc",
        "fixed_risk_mpc", "ndu", "ndu_no_cov")
COST_KEYS = ("encoder", "head", "controller", "verifier", "decoder", "io")
SHA = re.compile(r"[a-f0-9]{64}\Z")
SAFE_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
MAX_JSON_BYTES = 8_000_000
MAX_EPISODES_BYTES = 24_000_000


class EvidenceError(ValueError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise EvidenceError(message)


def strict_pairs(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, f"duplicate JSON key: {key[:64]}")
        out[key] = value
    return out


def reject_constant(value):
    raise EvidenceError(f"nonfinite JSON constant: {value[:32]}")


def read_json(path: Path, cap: int = MAX_JSON_BYTES):
    """Legacy fixture reader only; evidence CLI uses pinned descriptor-safe reads."""
    require(path.is_file() and not path.is_symlink(), "missing or symlinked JSON")
    require(path.stat().st_size <= cap, "JSON exceeds byte cap")
    return json.loads(path.read_text(encoding="utf-8"),
                      object_pairs_hook=strict_pairs, parse_constant=reject_constant)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha(value) -> bool:
    return type(value) is str and SHA.fullmatch(value) is not None


def stable(value) -> bool:
    return type(value) is str and SAFE_ID.fullmatch(value) is not None


def finite_unit(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def nonnegative_int(value) -> bool:
    return type(value) is int and value >= 0


def _read_pinned_artifact(root: Path, filename: str, expected: str, cap=64_000_000, *, collect=False):
    """Verify pinned bytes through descriptor-relative, no-follow POSIX opens.

    Opening each component relative to its already-open parent avoids the
    check/open pathname race of Path.resolve/is_symlink/read_bytes. Unsupported
    platforms fail closed instead of silently reverting to pathname reads.
    """
    require(type(filename) is str and 0 < len(filename) <= 256, "invalid artifact path")
    require(type(cap) is int and 0 < cap <= 64_000_000 and sha(expected),
            "invalid artifact cap or SHA256")
    parts = filename.split("/")
    require(not filename.startswith("/") and "\\" not in filename and "\x00" not in filename
            and not re.match(r"^[A-Za-z]:", filename) and len(parts) <= 32
            and all(part not in ("", ".", "..") for part in parts),
            "absolute/traversal/noncanonical artifact path")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    require(nofollow != 0 and directory != 0 and os.name == "posix",
            "atomic no-follow artifact reading unsupported")
    common_flags = getattr(os, "O_CLOEXEC", 0) | nofollow | os.O_RDONLY
    dir_fd = None
    file_fd = None
    chunks = []
    try:
        dir_fd = os.open(root, common_flags | directory)
        for component in parts[:-1]:
            next_fd = os.open(component, common_flags | directory, dir_fd=dir_fd)
            os.close(dir_fd)
            dir_fd = next_fd
        file_fd = os.open(parts[-1], common_flags | getattr(os, "O_NONBLOCK", 0),
                          dir_fd=dir_fd)
        before = os.fstat(file_fd)
        require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= cap,
                "artifact absent, not regular or too large")
        hasher = hashlib.sha256()
        count = 0
        while True:
            data = os.read(file_fd, min(1_048_576, cap + 1 - count))
            if not data:
                break
            count += len(data)
            require(count <= cap, "artifact increased beyond byte cap during read")
            hasher.update(data)
            if collect:
                chunks.append(data)
        after = os.fstat(file_fd)
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                 before.st_ctime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                 after.st_ctime_ns) and count == after.st_size,
                "artifact modified during evidence read")
        require(hasher.hexdigest() == expected, "artifact SHA256 mismatch")
        return b"".join(chunks) if collect else None
    except OSError as error:
        raise EvidenceError("artifact could not be safely opened or read") from error
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if dir_fd is not None:
            os.close(dir_fd)


def read_pinned_json(path: Path, expected_sha: str, cap: int = MAX_JSON_BYTES):
    """Read one independently SHA-pinned JSON input with no path re-open."""
    raw = _read_pinned_artifact(path.parent, path.name, expected_sha,
                                cap, collect=True)
    return json.loads(raw.decode("utf-8"), object_pairs_hook=strict_pairs,
                      parse_constant=reject_constant)


def verify_artifact(root: Path, filename: str, expected: str, cap=64_000_000) -> None:
    _read_pinned_artifact(root, filename, expected, cap)


def validate_sources(root: Path, source_manifest: dict, history: dict):
    require(type(source_manifest) is dict and type(source_manifest.get("sources")) is list,
            "source manifest shape")
    require(type(history) is dict and type(history.get("source_sha256")) is list,
            "historical source registry required")
    historical = history["source_sha256"]
    require(all(sha(x) for x in historical) and len(historical) == len(set(historical)),
            "malformed historical exclusions")
    occupied, by_id, split_count = set(historical), {}, dict.fromkeys(
        ("train", "dev", "calibration", "test"), 0)
    groups = {}
    for item in source_manifest["sources"]:
        require(type(item) is dict, "source row must be object")
        sid, role = item.get("source_id"), item.get("split")
        image_sha, family = item.get("source_sha256"), item.get("original_group")
        require(stable(sid) and role in split_count and sha(image_sha) and stable(family),
                "source identity/split invalid")
        require(sid not in by_id and image_sha not in occupied,
                "duplicate or historical source content")
        require(family not in groups or groups[family] == role,
                "original source family split leakage")
        require(type(item.get("modalities")) is list and
                1 <= len(item["modalities"]) <= 4 and
                all(m in ("text", "image", "audio", "video") for m in item["modalities"]) and
                len(set(item["modalities"])) == len(item["modalities"]), "source modalities")
        verify_artifact(root, item.get("path"), image_sha)
        by_id[sid] = item
        occupied.add(image_sha)
        groups[family] = role
        split_count[role] += 1
    require(all(value > 0 for value in split_count.values()), "missing source split")
    require(split_count["test"] >= 128, "fewer than 128 original heldout sources")
    return by_id, split_count


def validate_protocol(protocol, protocol_path: Path, expected_sha: str):
    require(sha(expected_sha), "protocol not independently pinned by expected SHA256")
    contents = _read_pinned_artifact(protocol_path.parent, protocol_path.name,
                                    expected_sha, MAX_JSON_BYTES, collect=True)
    pinned = json.loads(contents, object_pairs_hook=strict_pairs,
                        parse_constant=reject_constant)
    # The bytes authenticated against the frozen SHA must describe the
    # exact protocol that all subsequent cohort/episode checks consume.
    # JSON canonicalization also distinguishes true, 1 and 1.0.
    require(type(protocol) is dict and
            json.dumps(protocol, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) ==
            json.dumps(pinned, sort_keys=True, separators=(",", ":"),
                       allow_nan=False),
            "parsed protocol differs from independently pinned original bytes")
    require(protocol.get("schema") == "hepta.p0-p7.research.v1", "unknown protocol")
    require(type(protocol.get("seeds")) is list and len(protocol["seeds"]) >= 3 and
            all(nonnegative_int(x) for x in protocol["seeds"]) and
            len(set(protocol["seeds"])) == len(protocol["seeds"]), "need >=3 distinct seeds")
    require(protocol.get("arms") == list(ARMS), "unmatched mandatory arm roster")
    require(nonnegative_int(protocol.get("episode_budget_us")) and
            0 < protocol["episode_budget_us"] <= 100_000_000,
            "episode budget missing/invalid")
    require(protocol.get("paired_noise_protocol") == "common-random-numbers-v1",
            "paired-noise plan not frozen")
    require(sha(protocol.get("encoder_digest")) and
            nonnegative_int(protocol.get("encoder_generation")) and
            protocol["encoder_generation"] > 0, "encoder/generation identity")


def read_episodes(path: Path, expected_sha: str):
    """Read the exact frozen JSONL ledger with a bounded descriptor-safe read."""
    raw = _read_pinned_artifact(path.parent, path.name, expected_sha,
                                MAX_EPISODES_BYTES, collect=True)
    lines = raw.decode("utf-8").splitlines()
    require(len(lines) <= 100_000, "episode count over cap")
    records = []
    for index, line in enumerate(lines):
        require(line and len(line) <= 80_000, f"episode {index} invalid size")
        try:
            records.append(json.loads(line, object_pairs_hook=strict_pairs,
                                      parse_constant=reject_constant))
        except (ValueError, TypeError) as error:
            raise EvidenceError(f"episode {index}: {error}") from error
    return records


def validate_trace(row):
    trace = row.get("decisions")
    require(type(trace) is list and len(trace) <= 16, "unbounded/missing decision trace")
    require(type(row.get("actual_steps")) is int and len(trace) == row["actual_steps"],
            "declared capacity is not observed steps")
    if row["arm"] == "ndu" and row["valid"]:
        require(8 <= len(trace) <= 16, "completed NDU has fewer than 8 actual decisions")
        require(trace[-1].get("action") in ("STOP", "ABSTAIN"),
                "completed NDU must record its terminal decision")
    prev = None
    for index, step in enumerate(trace):
        require(type(step) is dict and all(sha(step.get(key)) for key in
                ("pre_state_sha256", "post_state_sha256", "evidence_sha256")),
                "missing state/evidence digest")
        require(step.get("action") in ("RECALL", "ROUTE", "DECOMPOSE", "VERIFY",
                                       "REVISE", "BACKTRACK", "STOP", "ABSTAIN"),
                "invalid reasoning action")
        require(step["action"] not in ("STOP", "ABSTAIN") or index == len(trace) - 1,
                "terminal decision followed by additional actions")
        require(nonnegative_int(step.get("cost_us")) and step["cost_us"] > 0,
                "zero/unmeasured decision cost")
        require(prev is None or step["pre_state_sha256"] == prev,
                "noncontiguous state transition")
        prev = step["post_state_sha256"]
    require(sum(x["cost_us"] for x in trace) <= row["total_us"],
            "decision costs exceed entire physical run")
    actions = json.dumps([step["action"] for step in trace],
                         ensure_ascii=True, separators=(",", ":")).encode()
    require(row.get("action_digest") == digest(b"hepta.group.actions.v1\0" + actions),
            "action digest does not bind executed decision trace")
    trace_bytes = json.dumps(trace, sort_keys=True, separators=(",", ":")).encode()
    require(row.get("trace_sha256") == digest(b"hepta.group.trace.v1\0" + trace_bytes),
            "trace digest does not bind state transitions and paid actions")


def validate_episode(root, row, by_id, protocol):
    require(type(row) is dict, "episode row not object")
    arm, sid, seed = row.get("arm"), row.get("source_id"), row.get("seed")
    require(arm in ARMS and sid in by_id and by_id[sid]["split"] == "test" and
            type(seed) is int and seed in protocol["seeds"], "episode roster/source/seed")
    require(row.get("source_sha256") == by_id[sid]["source_sha256"] and
            sha(row.get("noise_digest")), "source or common-noise binding")
    owner = row.get("owner")
    require(type(owner) is dict and owner.get("encoder_digest") == protocol["encoder_digest"] and
            type(owner.get("generation")) is int and
            owner["generation"] == protocol["encoder_generation"] and
            type(owner.get("forward_calls")) is int and owner["forward_calls"] == 1 and
            sha(owner.get("feature_digest")),
            "unbound or duplicated Encoder forward")
    cells = owner.get("cells")
    require(type(cells) is list and 1 <= len(cells) <= 4096 and
            len(set(x.get("cell_id") for x in cells if type(x) is dict)) == len(cells) and
            all(type(x) is dict and stable(x.get("cell_id")) and
                x.get("feature_digest") == owner["feature_digest"] for x in cells),
            "private Cell feature identity or count")
    components = row.get("cost_us")
    require(type(components) is dict and set(components) == set(COST_KEYS) and
            all(nonnegative_int(components[k]) for k in COST_KEYS) and
            nonnegative_int(row.get("total_us")) and row["total_us"] == sum(components.values()),
            "missing/non-reconciled physical cost components")
    require(type(row.get("valid")) is bool and type(row.get("covered")) is bool and
            type(row.get("severe")) is bool and finite_unit(row.get("quality")),
            "outcome is not a bounded observed value")
    fail = not row["valid"] or row["total_us"] > protocol["episode_budget_us"]
    if fail:
        require(row["quality"] == 0 and row["severe"] and not row["covered"],
                "failed/over-budget output wrongly rewarded or censored")
    else:
        require(row["covered"] and sha(row.get("output_sha256")),
                "completed output missing")
        verify_artifact(root, row.get("output_path"), row["output_sha256"])
    require(finite_unit(row.get("risk_weight")), "unregistered risk weight")
    if arm == "ndu":
        require(row["risk_weight"] > 0, "NDU risk term calibrated to zero")
    validate_trace(row)


def cvar90(losses):
    require(losses and all(finite_unit(v) for v in losses), "invalid CVaR inputs")
    sorted_losses = sorted(losses, reverse=True)
    mass = len(losses) / 10
    whole = int(mass)
    return (sum(sorted_losses[:whole]) + (mass-whole)*sorted_losses[whole]) / mass


def report_status(by_id, protocol, rows):
    tests = [s for s, x in by_id.items() if x["split"] == "test"]
    table = {}
    for row in rows:
        key = (row["source_id"], row["seed"], row["arm"])
        require(key not in table, "duplicate source/seed/arm episode")
        table[key] = row
    require(len(table) == len(tests)*len(protocol["seeds"])*len(ARMS),
            "incomplete heldout arm/seed denominator")
    for sid in tests:
        for seed in protocol["seeds"]:
            matched = [table[(sid,seed,arm)] for arm in ARMS]
            require(len({r["noise_digest"] for r in matched}) == 1,
                    "unmatched stochastic world draws")
    summaries = {}
    for arm in ARMS:
        selected = [row for row in rows if row["arm"] == arm]
        summaries[arm] = {
            "quality": statistics.mean(row["quality"] for row in selected),
            "coverage": statistics.mean(row["covered"] for row in selected),
            "wall_us": statistics.mean(row["total_us"] for row in selected),
            "cvar90": cvar90([1-row["quality"] for row in selected]),
        }
    ndu = summaries["ndu"]
    matched = all(
        table[(sid, seed, "ndu")]["covered"] == table[(sid, seed, arm)]["covered"]
        and abs(table[(sid,seed,"ndu")]["total_us"] - table[(sid,seed,arm)]["total_us"])
        / max(1, table[(sid,seed,arm)]["total_us"]) <= 0.05
        for sid in tests for seed in protocol["seeds"]
        for arm in ARMS if arm not in ("ndu", "ndu_no_cov"))
    superior = all(ndu["quality"] > summaries[arm]["quality"]+0.01 and
                   ndu["cvar90"] < summaries[arm]["cvar90"]-0.01
                   for arm in ARMS if arm not in ("ndu", "ndu_no_cov"))
    ndu_rows = [row for row in rows if row["arm"] == "ndu"]
    has_verification = any(any(step["action"] == "VERIFY" for step in r["decisions"])
                           for r in ndu_rows)
    has_backtracking = any(any(step["action"] == "BACKTRACK" for step in r["decisions"])
                           for r in ndu_rows)
    covariance_effect = any(
        [x["action"] for x in table[(sid,seed,"ndu")]["decisions"]] !=
        [x["action"] for x in table[(sid,seed,"ndu_no_cov")]["decisions"]]
        for sid in tests for seed in protocol["seeds"])
    # Data checks are never converted into model promotion or production authority.
    return {"schema": "hepta.p0-p7.audit.v1", "source_groups": len(tests),
            "seeds": len(protocol["seeds"]), "episode_count": len(rows),
            "descriptive": summaries,
            "mechanism_checks": {"shared_encoder_receipt_consistent": True,
                                 "all_arms_and_draws_paired": True,
                                 "actual_cost_and_coverage_matched": matched,
                                 "ndu_descriptively_superior": superior,
                                 "ndu_covariance_changes_action": covariance_effect,
                                 "reasoning_verified_steps_observed": has_verification,
                                 "reasoning_backtrack_observed": has_backtracking},
            "stage_status": {f"P{i}": "HOLD_NO_GO" for i in range(8)},
            "blocking_reasons": [
                "P0: self-reported forward receipts lack independent execution attestation",
                "P1: independently tested actual task learning / OOD not established",
                "P2: natural audio/video and independently verified modality failures not established",
                "P3: decoded task correctness and superiority confidence intervals not established",
                "P4: independent risk/covariance causality and paired confidence bounds not established",
                "P5: independent post-distillation transfer/retention not established",
                "P6: externally witnessed split/merge/retire/withdrawal/rollback not established",
                "P7: exact-source CI, target-device energy/p95/p99, independent authorization absent"],
            "model_promotion_authorized": False, "authority": "DENY_ALL"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--sources-sha256", required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--history-sha256", required=True)
    parser.add_argument("--episodes", type=Path, required=True)
    parser.add_argument("--episodes-sha256", required=True)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        protocol = read_pinned_json(args.protocol, args.protocol_sha256)
        validate_protocol(protocol, args.protocol, args.protocol_sha256)
        root = args.artifacts_root.resolve(strict=True)
        sources = read_pinned_json(args.sources, args.sources_sha256)
        history = read_pinned_json(args.history, args.history_sha256)
        by_id, _ = validate_sources(root, sources, history)
        rows = read_episodes(args.episodes, args.episodes_sha256)
        for row in rows:
            validate_episode(root, row, by_id, protocol)
        report = report_status(by_id, protocol, rows)
        code = 2  # no evidence-only run can grant external promotion authority
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as error:
        report = {"schema": "hepta.p0-p7.audit.v1", "status": "INVALID_EVIDENCE",
                  "error": str(error)[:300], "authority": "DENY_ALL",
                  "model_promotion_authorized": False,
                  "stage_status": {f"P{i}": "HOLD_NO_GO" for i in range(8)}}
        code = 3
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
