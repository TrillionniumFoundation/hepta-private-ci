"""Audit precommitted PR commit ancestry without opening targets or model data.

A registered commit reachable through other REGISTERED commits is only a
partial DAG witness. It does not prove the full PR chronology, base diff,
reviewer authority, or sufficient task evidence.
"""

import argparse
import json
import os
from pathlib import Path
import re

from project_pr_source_materialize import (
    ObjectReader,
    atomic_json,
    canonical,
    digest,
    github_json,
    reopen_materialized,
)
from project_pr_source_precommit import CUT, read_pinned, timestamp

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
SCHEMA = "hepta.memorycell.project-registered-ancestry.v1"


def check_case(case, records):
    """Evaluate only SHA-pinned registered edges; unknown ancestry stays unknown."""
    listed = case["commits"]
    names = [x["sha"] for x in listed]
    if len(names) != len(set(names)) or set(records) != set(names):
        raise ValueError("missing, extra or duplicated registered commit objects")
    if names[-1] != case["head_sha"]:
        raise ValueError("declared head changed")
    cutoff = timestamp(CUT)
    for declared in listed:
        oid = declared["sha"]
        record = records[oid]
        if (
            not isinstance(record, dict)
            or set(record)
            != {"sha", "tree_sha", "parents", "authored_at", "committed_at"}
            or record["sha"] != oid
            or not isinstance(record["tree_sha"], str)
            or HEX40.fullmatch(record["tree_sha"]) is None
            or not isinstance(record["parents"], list)
            or len(record["parents"]) > 2
            or len(set(record["parents"])) != len(record["parents"])
            or any(
                type(p) is not str or HEX40.fullmatch(p) is None or p == oid
                for p in record["parents"]
            )
        ):
            raise ValueError("unbound or malformed immutable Git commit")
        authored = timestamp(record["authored_at"])
        committed = timestamp(record["committed_at"])
        if (
            authored > cutoff
            or committed > cutoff
            or committed != timestamp(declared["committed_at"])
        ):
            raise ValueError(
                "original commit chronology conflicts with frozen pre-cut data"
            )
    head = records[case["head_sha"]]
    if head["tree_sha"] != case["tree_sha"] or head["parents"] != case["parents"]:
        raise ValueError(
            "HEAD tree or declared parent identity differs from frozen source"
        )
    reachable = set()
    pending = [case["head_sha"]]
    registered = set(names)
    while pending:
        oid = pending.pop()
        if oid in reachable:
            continue
        reachable.add(oid)
        pending.extend(p for p in records[oid]["parents"] if p in registered)
    unproven = [oid for oid in names if oid not in reachable]
    return dict(
        source_project=case["repo"],
        source_pull_number=case["pull_number"],
        registered_commits=len(names),
        registered_reachable=len(reachable),
        registered_ancestry_unproven=unproven,
        registered_merge_commits=sum(
            len(records[oid]["parents"]) == 2 for oid in names
        ),
        out_of_register_parent_edges=sum(
            p not in registered for oid in names for p in records[oid]["parents"]
        ),
        all_registered_commits_reachable=not unproven,
        full_pull_request_ancestry_certified=False,
        historical_patch_semantics_certified=False,
    )


def assess(manifest, observed):
    if type(observed) is not list or len(observed) != len(manifest["cases"]):
        raise ValueError("eight original registered PRs required")
    results = []
    for case, records in zip(manifest["cases"], observed, strict=True):
        results.append(check_case(case, records))
    return dict(
        schema=SCHEMA,
        original_prs=len(results),
        registered_commit_refs=sum(x["registered_commits"] for x in results),
        reachable_registered_commit_refs=sum(
            x["registered_reachable"] for x in results
        ),
        unproven_registered_commit_refs=sum(
            len(x["registered_ancestry_unproven"]) for x in results
        ),
        projects=list(results),
        no_answers_or_targets_read=True,
        new_model_calls=0,
        independent_semantic_review=False,
        citation_precision=None,
        production_accepted=False,
    )


def records_from_remote(manifest, fetch):
    reader = ObjectReader(fetch, request_limit=128)
    result = []
    for case in manifest["cases"]:
        group = {}
        for declared in case["commits"]:
            oid = declared["sha"]
            obj = reader.get(case["repo"], "commits", oid)
            group[oid] = dict(
                sha=obj["sha"],
                tree_sha=obj["tree"]["sha"],
                parents=[p["sha"] for p in obj["parents"]],
                authored_at=obj["author"]["date"],
                committed_at=obj["committer"]["date"],
            )
        result.append(group)
    return result, reader.count


def unique_pairs(pairs):
    data = {}
    for k, v in pairs:
        if k in data:
            raise ValueError("duplicate registered-ancestry field")
        data[k] = v
    return data


def read_receipt(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
        raise ValueError("missing or oversized registered-ancestry receipt")
    raw = path.read_bytes()

    def invalid(_):
        raise ValueError("nonfinite registered-ancestry JSON number")

    obj = json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=invalid)
    if raw != canonical(obj) + b"\n":
        raise ValueError("noncanonical registered-ancestry receipt")
    return obj, digest(raw)


def run(source, original, out, *, sha, offline=False):
    manifest = read_pinned(source, sha)
    reopened = reopen_materialized(manifest, original, manifest_sha=sha)
    if offline:
        output = Path(out)
        if (
            output.is_symlink()
            or not output.is_dir()
            or {p.name for p in output.iterdir()} != {"inventory.json", "READY.json"}
        ):
            raise ValueError("unsealed or contaminated ancestry output directory")
        raw, raw_sha = read_receipt(output / "inventory.json")
        ready, _ = read_receipt(Path(out) / "READY.json")
        if (
            set(raw)
            != {
                "schema",
                "original_source_sha256",
                "original_ready_sha256",
                "observed",
                "analysis",
                "remote_git_object_requests",
                "complete_original_git_commit_objects",
            }
            or type(raw.get("remote_git_object_requests")) is not int
            or not 1 <= raw["remote_git_object_requests"] <= 128
            or raw.get("schema") != SCHEMA
            or raw.get("original_source_sha256") != sha
            or raw.get("original_ready_sha256") != reopened["original_ready_sha256"]
            or raw.get("complete_original_git_commit_objects") is not True
            or ready
            != dict(
                schema="hepta.memorycell.project-registered-ancestry-ready.v1",
                inventory_sha256=raw_sha,
                original_source_sha256=sha,
                research_only=True,
                independent_semantic_review=False,
                production_accepted=False,
            )
            or raw.get("analysis") != assess(manifest, raw["observed"])
        ):
            raise ValueError(
                "registered commit ancestry does not reproduce from sealed bytes"
            )
        return raw["analysis"]
    if Path(out).exists():
        raise ValueError("ancestry output must not overwrite another run")
    Path(out).mkdir(parents=True)
    try:
        observed, requests = records_from_remote(
            manifest,
            lambda repo, kind, oid: github_json(
                repo, kind, oid, token=os.environ.get("GITHUB_TOKEN")
            ),
        )
        report = assess(manifest, observed)
        atomic_json(
            Path(out) / "inventory.json",
            dict(
                schema=SCHEMA,
                original_source_sha256=sha,
                original_ready_sha256=reopened["original_ready_sha256"],
                observed=observed,
                analysis=report,
                remote_git_object_requests=requests,
                complete_original_git_commit_objects=True,
            ),
        )
        atomic_json(
            Path(out) / "READY.json",
            dict(
                schema="hepta.memorycell.project-registered-ancestry-ready.v1",
                inventory_sha256=digest((Path(out) / "inventory.json").read_bytes()),
                original_source_sha256=sha,
                research_only=True,
                independent_semantic_review=False,
                production_accepted=False,
            ),
        )
        return report
    except Exception as exc:
        if not (Path(out) / "READY.json").exists():
            atomic_json(
                Path(out) / "INCOMPLETE.json",
                dict(
                    status="incomplete",
                    reason=type(exc).__name__,
                    research_ready=False,
                ),
            )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("original", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--reopen-only", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.source,
                args.original,
                args.output,
                sha=args.source_sha256,
                offline=args.reopen_only,
            ),
            sort_keys=True,
            allow_nan=False,
        )
    )
