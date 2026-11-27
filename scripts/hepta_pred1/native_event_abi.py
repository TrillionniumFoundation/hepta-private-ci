"""Import native predispatch facts without promoting them to effect labels.

This is a private, retrospective research ABI. Native hashes bind bytes, not
provenance or FinalUse authority. Original wall times and per-step sequences
never become shared arrival cursors, monotonic event times or frozen inputs.
Independent execution/effect witnesses still belong to owner_bridge.
"""

import argparse
from hashlib import sha256
import json

from .native_fact import _parse_native, read_native_fact
from .native_ledger import Artifact, _collection, _require


def import_native_events(encoded, *, expected_owner, source, collection=None):
    """Bind one native fact and optional owner collection, never infer ordering.

    Collection clocks/cursors remain collector declarations. Every collection
    row shares its one read transaction, not a fabricated arrival per row. An
    absent attempt is only an absent row in that supplied snapshot. This ABI
    deliberately cannot be consumed as a numerical snapshot or effect label.
    """
    _require(
        source in ("fixture", "declared_native"), "explicit source category required"
    )
    fact, profiles = _parse_native(encoded, expected_owner)
    step, intent = fact["claimed_step"], fact["intent"]
    identity = {
        name: step[name]
        for name in (
            "owner_agent_id",
            "run_id",
            "step_id",
            "attempt",
            "intent_digest",
            "payload_digest",
        )
    }
    identity["destination_id"] = intent["destination_id"]
    digest = sha256(encoded).hexdigest()
    events = [
        {
            "domain": "intention",
            "source_sha256": digest,
            "native_wall_time_ms": fact["caller_time_ms"],
            "per_step_sequence": step["event_seq"],
            "detail": {"intent": intent, "claimed_step": step},
        }
    ]
    collector = None
    attempts = []
    if collection is not None:
        try:
            c = _collection(collection)
        except (KeyError, TypeError) as error:
            raise ValueError("malformed owner collection") from error
        _require(
            all(c["identity"][name] == value for name, value in identity.items()),
            "native fact and collection identity differ",
        )
        _require(
            all(
                type(row["attempt"]) is int
                for rows in c["rows"].values()
                for row in rows
            ),
            "owner row attempt must be an integer",
        )
        collector = {name: c[name] for name in ("clock_id", "cursor", "available_at")}
        attempts = c["rows"]["attempts"]
        for table, domain, time_name in (
            ("attempts", "owner_dispatch_boundary", "started_at_ms"),
            ("observations", "owner_settlement", "observed_at_ms"),
            ("reconciliations", "owner_reconciliation", "observed_at_ms"),
        ):
            for row in c["rows"][table]:
                events.append(
                    {
                        "domain": domain,
                        "source_sha256": collection.digest,
                        "native_wall_time_ms": row[time_name],
                        "per_step_sequence": None,
                        "detail": row,
                    }
                )
    return Artifact.make(
        {
            "schema": "pred1-native-event-abi-v1",
            "identity": identity,
            "source": source,
            "native_source_sha256": digest,
            "native_source_utf8": encoded.decode("utf-8"),
            "native_serialization_profiles": profiles,
            "collection_sha256": None if collection is None else collection.digest,
            "collection_utf8": None
            if collection is None
            else collection.encoded.decode("utf-8"),
            "collector_arrival_declaration": collector,
            "shared_arrival_cursor": None,
            "shared_clock_id": None,
            "events": events,
            "event_order_scope": "source grouping only; not chronology or a shared arrival sequence",
            "native_time_scope": "raw owner/caller wall-clock milliseconds; no monotonic conversion",
            "phase_status": {
                "intention": "claimed_intent_record",
                "authorization": "owner_attempt_record_only" if attempts else "unknown",
                "dispatch": "may_have_contacted" if attempts else "unknown",
                "execution": "unknown",
                "independent_effect": "unknown",
                "censoring": "unobserved",
            },
            "effect_labels": {
                "outcome": None,
                "duration": None,
                "final_cost": None,
                "time_lower": None,
                "time_upper": None,
                "nonoccurrence_witness": None,
            },
            "native_intent_digest_recomputed": False,
            "source_provenance_authenticated": False,
            "authorization_verified": False,
            "physical_cost_complete": False,
            "predecision_snapshots_created": 0,
            "effect_labels_created": 0,
            "qualification": "HOLD",
            "production_activation": False,
        }
    )


def validate_native_events(artifact, *, expected_owner, expected_source):
    """Replay the entire ABI from retained sources; a rehash cannot relabel phases."""
    _require(isinstance(artifact, Artifact), "immutable native event ABI required")
    p = artifact.payload
    try:
        collection = p["collection_utf8"]
        replay = import_native_events(
            p["native_source_utf8"].encode("utf-8"),
            expected_owner=expected_owner,
            source=expected_source,
            collection=None
            if collection is None
            else Artifact(collection.encode("utf-8")),
        )
    except (KeyError, TypeError, AttributeError, UnicodeError) as error:
        raise ValueError("malformed retained native sources") from error
    _require(
        replay.encoded == artifact.encoded, "native ABI differs from retained sources"
    )
    return p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-fact", required=True)
    parser.add_argument("--expected-owner", required=True)
    parser.add_argument(
        "--source", required=True, choices=("fixture", "declared_native")
    )
    parser.add_argument("--collection")
    parser.add_argument(
        "--output", required=True, help="new private artifact; never overwritten"
    )
    args = parser.parse_args()
    artifact = import_native_events(
        read_native_fact(args.native_fact),
        expected_owner=args.expected_owner,
        source=args.source,
        collection=None if args.collection is None else Artifact.read(args.collection),
    )
    artifact.save(args.output)
    print(json.dumps({"abi_sha256": artifact.digest, "qualification": "HOLD"}))


if __name__ == "__main__":
    main()
