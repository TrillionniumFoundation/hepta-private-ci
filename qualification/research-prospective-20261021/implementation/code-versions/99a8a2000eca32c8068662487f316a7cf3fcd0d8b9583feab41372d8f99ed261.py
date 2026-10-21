"""Admit the first eight byte-verified sources under the sealed future window.

Read bounded primary API captures, try first-parent pairs in the registered
order, retain every acquisition failure, and forbid repository/object leakage.
No model outcomes, labels or adaptive source substitutions are inputs.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from capture_git_objects import capture, sha256, write
from external_git_projection import KINDS, PRECOMMIT_SHA, load_receipt, regular


def parse_utc(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise ValueError("canonical UTC publisher timestamp required")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def metadata_pairs(repo, slot, wrapper, window):
    lower, upper = window
    expected_url = (
        "https://api.github.com/repos/"
        + repo
        + "/commits?"
        + urlencode(dict(since=lower, until=upper, per_page=32))
    )
    if (
        wrapper["schema"] != "hepta.external-git-event.api-capture.v1"
        or wrapper["repository"] != repo
        or wrapper["request_url"] != expected_url
        or datetime.fromisoformat(wrapper["completed_at"].replace("Z", "+00:00"))
        < parse_utc(upper)
    ):
        raise ValueError("API capture does not bind the closed precommitted window")
    rows = wrapper["response"]
    if not isinstance(rows, list) or len(rows) > 32:
        raise ValueError("bounded 32-commit census required")
    by_sha = {}
    for row in rows:
        identifier = row["sha"]
        timestamp = row["commit"]["committer"]["date"]
        tree = row["commit"]["tree"]["sha"]
        if (
            not re.fullmatch(r"[0-9a-f]{40}", identifier)
            or not re.fullmatch(r"[0-9a-f]{40}", tree)
            or identifier in by_sha
        ):
            raise ValueError("duplicate or invalid original commit identity")
        parse_utc(timestamp)
        if lower <= timestamp <= upper:
            by_sha[identifier] = row
    pairs = []
    for current in sorted(
        by_sha.values(), key=lambda r: (r["commit"]["committer"]["date"], r["sha"])
    ):
        parents = current["parents"]
        if not parents or parents[0]["sha"] not in by_sha:
            continue
        previous = by_sha[parents[0]["sha"]]
        if previous["sha"] == current["sha"]:
            raise ValueError("self-parent cannot be a captured Git pair")
        pairs.append(
            dict(
                repo=repo,
                split="evaluation",
                slot=slot,
                kind=KINDS[slot % 4],
                status="metadata_pair_selected_bytes_pending",
                previous_sha=previous["sha"],
                current_sha=current["sha"],
                previous_tree=previous["commit"]["tree"]["sha"],
                current_tree=current["commit"]["tree"]["sha"],
                previous_date=previous["commit"]["committer"]["date"],
                current_date=current["commit"]["committer"]["date"],
                source_api_url=expected_url,
            )
        )
    return pairs


def select(precommit, metadata, calibration, output):
    raw = regular(precommit)
    if sha256(raw) != PRECOMMIT_SHA:
        raise ValueError("sealed prospective registration changed")
    registration = json.loads(raw)
    lower, upper = registration["evaluation_window"]
    if datetime.now(timezone.utc) < parse_utc(upper):
        raise ValueError("evaluation window has not closed; do not select early")
    cal_raw = regular(calibration)
    cal = json.loads(cal_raw)
    if cal["phase"] != "calibration" or cal["precommit_sha256"] != PRECOMMIT_SHA:
        raise ValueError("calibration source boundary unbound")
    cal_repos, cal_objects = (
        set(cal["source_repositories"]),
        set(cal["exact_source_object_ids"]),
    )
    output.mkdir()
    captures = output / "captures"
    captures.mkdir()
    selected, decisions, metadata_hashes = [], [], {}
    for slot, repo in enumerate(registration["evaluation_source_pool_order"]):
        capture_path = metadata / (repo.replace("/", "__") + ".json")
        if len(selected) == 8:
            decisions.append(
                dict(repository=repo, status="not_needed_after_first_eight_admitted")
            )
            continue
        if repo in cal_repos:
            raise ValueError("precommitted source pool leaked a calibration repository")
        decision = dict(repository=repo, slot=slot, attempts=[])
        try:
            metadata_raw = regular(capture_path)
            metadata_hashes[repo] = sha256(metadata_raw)
            pairs = metadata_pairs(repo, slot, json.loads(metadata_raw), (lower, upper))
            decision["metadata_candidate_pairs"] = len(pairs)
            decision["status"] = "no_eligible_original_pair"
            for entry in pairs:
                destination = captures / (
                    repo.replace("/", "__") + "--" + entry["current_sha"]
                )
                attempt = dict(
                    current_sha=entry["current_sha"], previous_sha=entry["previous_sha"]
                )
                try:
                    capture(entry, destination)
                    receipt_path = destination / "source-receipt.json"
                    receipt, _, _, _, receipt_sha = load_receipt(receipt_path)
                    objects = {
                        obj["git_sha1"]
                        for obj in receipt["original_objects"]
                        + receipt["root_license_objects"]
                    }
                    overlap = sorted(objects & cal_objects)
                    if overlap:
                        attempt.update(
                            status="ineligible_calibration_object_overlap",
                            overlapping_objects=overlap,
                        )
                    else:
                        attempt.update(
                            status="admitted_original_bytes", receipt_sha256=receipt_sha
                        )
                        selected.append(
                            entry
                            | dict(
                                source_receipt_path=str(receipt_path.resolve()),
                                source_receipt_sha256=receipt_sha,
                            )
                        )
                        decision["status"] = "admitted"
                except Exception as error:
                    attempt.update(
                        status="capture_failed",
                        error_type=type(error).__name__,
                        error=str(error)[:1024],
                    )
                decision["attempts"].append(attempt)
                if decision["status"] == "admitted":
                    break
        except Exception as error:
            decision.update(
                status="metadata_failed",
                error_type=type(error).__name__,
                error=str(error)[:1024],
            )
        decisions.append(decision)
        print(
            json.dumps(
                {
                    "repository": repo,
                    "status": decision["status"],
                    "admitted_total": len(selected),
                }
            ),
            flush=True,
        )
    complete = len(selected) == 8
    write(output / "EVALUATION_PAIRS.json", dict(entries=selected))
    write(
        output / "EVALUATION_ADMISSION.json",
        dict(
            schema="hepta.external-git-event.prospective-admission.v1",
            precommit_sha256=PRECOMMIT_SHA,
            calibration_collection_sha256=sha256(cal_raw),
            selector_sha256=sha256(Path(__file__).read_bytes()),
            metadata_sha256=metadata_hashes,
            window=[lower, upper],
            completed_at=datetime.now(timezone.utc).isoformat(),
            planned_sources=8,
            admitted_sources=len(selected),
            complete=complete,
            source_selection=decisions,
            selected_pairs_sha256=sha256(
                (output / "EVALUATION_PAIRS.json").read_bytes()
            ),
            model_outcomes_consulted=False,
            windows_extended=False,
            source_replacements=False,
            task_kind_uses_registered_pool_slot=True,
            timestamps_are_original_committer_fields=True,
            independent_creation_timestamp_attestation=False,
            mode="SHADOW_ONLY",
            authority="DENY_ALL",
            release="NO_GO",
            production_accepted=False,
        ),
    )
    if not complete:
        raise SystemExit(
            "fewer than eight eligible sources: retain all failures, "
            "do not run a reduced evaluation"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("precommit", "metadata", "calibration_collection", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    select(args.precommit, args.metadata, args.calibration_collection, args.output)


if __name__ == "__main__":
    main()
