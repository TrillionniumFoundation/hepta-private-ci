"""Bounded local commands for scheduling and candidate qualification."""

import argparse
from dataclasses import asdict, fields
import json
from pathlib import Path
import sys

from .candidate import (
    CandidateEnvelope,
    Mutation,
    generate_candidates,
    sandbox_candidate,
)
from .control_plane import EngineeringError, EngineeringStore, WorkEnvelope, WorkPackage

MAX_INPUT_BYTES = 2 * 1024 * 1024


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EngineeringError("duplicate_json_field")
        result[key] = value
    return result


def _read(path):
    with Path(path).open("rb") as source:
        content = source.read(MAX_INPUT_BYTES + 1)
    if len(content) > MAX_INPUT_BYTES:
        raise EngineeringError("input_byte_limit_exceeded")
    return json.loads(content, object_pairs_hook=_unique_pairs)


def _record(record_type, value):
    if not isinstance(value, dict) or set(value) - {
        f.name for f in fields(record_type)
    }:
        raise EngineeringError("invalid_input_fields")
    return record_type(
        **{
            key: tuple(item) if isinstance(item, list) else item
            for key, item in value.items()
        }
    )


def _records(record_type, value, limit):
    if not isinstance(value, list) or len(value) > limit:
        raise EngineeringError("input_record_limit_exceeded")
    return tuple(_record(record_type, item) for item in value)


def _candidate_inputs(args):
    envelope = _record(CandidateEnvelope, _read(args.envelope))
    mutations = _records(Mutation, _read(args.mutations), 32)
    return envelope, generate_candidates(envelope, mutations)


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    schedule = commands.add_parser(
        "schedule", help="persist an envelope and bounded assignment generation"
    )
    schedule.add_argument("--database", required=True)
    schedule.add_argument("--envelope", required=True)
    schedule.add_argument("--packages", required=True)
    schedule.add_argument("--completed")
    schedule.add_argument("--generation-id", required=True)
    for name, help_text in (
        ("candidates", "generate deterministic proposals including no-change"),
        ("sandbox", "execute one candidate in the admitted isolation profile"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--envelope", required=True)
        command.add_argument("--mutations", required=True)
        if name == "sandbox":
            command.add_argument("--repository", required=True)
            command.add_argument("--candidate-id", required=True)
            command.add_argument("--checks", required=True)
    return root


def run(args):
    if args.command == "schedule":
        envelope = _record(WorkEnvelope, _read(args.envelope))
        packages = _records(WorkPackage, _read(args.packages), 4096)
        completed = _read(args.completed) if args.completed else []
        if not isinstance(completed, list):
            raise EngineeringError("invalid_completed_set")
        with EngineeringStore(args.database) as store:
            store.issue_work_envelope(envelope)
            receipt = store.schedule_ready_packages(
                envelope.envelope_id,
                packages,
                completed,
                generation_id=args.generation_id,
            )
            return {
                "assignment": asdict(receipt),
                "frontier": store.assignment_frontier(args.generation_id),
            }
    envelope, candidates = _candidate_inputs(args)
    if args.command == "candidates":
        return {"candidates": [asdict(candidate) for candidate in candidates]}
    candidate = next(
        (item for item in candidates if item.candidate_id == args.candidate_id), None
    )
    if candidate is None:
        raise EngineeringError("unknown_candidate")
    checks = _read(args.checks)
    if not isinstance(checks, list):
        raise EngineeringError("invalid_check")
    tested, receipt = sandbox_candidate(args.repository, envelope, candidate, checks)
    return {"candidate": asdict(tested), "receipt": asdict(receipt)}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = run(args)
    except (EngineeringError, OSError, ValueError, TypeError) as exc:
        code = exc.code if isinstance(exc, EngineeringError) else "invalid_input"
        print(json.dumps({"error": code, "authorityGranted": False}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return int(args.command == "sandbox" and result["receipt"]["passed"] is not True)
