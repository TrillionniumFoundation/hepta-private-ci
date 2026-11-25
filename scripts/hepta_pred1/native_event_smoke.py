"""Exercise the actual Rust-test fact through Python import and fresh readback.

The input must be the retained native fixture and its manifest. There is no
synthetic fallback. This qualifies only a fixture bridge: manifest hashes do
not authenticate live owners, authorize actions or supply independent labels.
"""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from .native_event_abi import (
    import_native_events,
    read_native_fact,
    validate_native_events,
)
from .native_ledger import Artifact, _digest, _require

PRODUCER_TEST = (
    "automation_predispatch_export::tests::"
    "ordinary_product_caller_retains_claimed_fact_before_contact_and_replays_once"
)


def _unique_object(pairs):
    value = dict(pairs)
    _require(len(value) == len(pairs), "duplicate fixture manifest key")
    return value


def _save_new(path, encoded):
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())


def verify_abi(path, *, expected_owner, expected_native_sha256):
    """Replay retained source bytes; report this process identity to the parent."""
    _digest(expected_native_sha256)
    artifact = Artifact.read(path)
    p = validate_native_events(
        artifact, expected_owner=expected_owner, expected_source="fixture"
    )
    _require(
        p["native_source_sha256"] == expected_native_sha256,
        "readback native source digest differs",
    )
    _require(
        p["shared_arrival_cursor"] is None
        and p["shared_clock_id"] is None
        and p["collector_arrival_declaration"] is None
        and p["collection_utf8"] is None
        and all(value is None for value in p["effect_labels"].values())
        and p["phase_status"]
        == {
            "intention": "claimed_intent_record",
            "authorization": "unknown",
            "dispatch": "unknown",
            "execution": "unknown",
            "independent_effect": "unknown",
            "censoring": "unobserved",
        }
        and p["authorization_verified"] is False
        and p["source_provenance_authenticated"] is False
        and p["predecision_snapshots_created"] == 0
        and p["effect_labels_created"] == 0
        and p["production_activation"] is False,
        "native fixture was promoted beyond retained intention facts",
    )
    return {
        "schema": "pred1-native-abi-readback-v1",
        "process_id": os.getpid(),
        "abi_sha256": artifact.digest,
        "native_fact_sha256": expected_native_sha256,
        "source": "native_test_fixture",
        "fixture_only": True,
        "source_provenance_authenticated": False,
        "independent_effect_labels": 0,
    }


def run_fixture_smoke(fixture_dir, output_dir):
    """Retain the original Rust output, import once and verify in a fresh process."""
    fixture = Path(fixture_dir)
    _require(fixture.is_absolute(), "native fixture directory must be absolute")
    metadata = fixture.lstat()
    _require(
        stat.S_ISDIR(metadata.st_mode) and metadata.st_mode & 0o077 == 0,
        "native fixture directory must be a private directory, not a symlink",
    )
    raw_manifest = read_native_fact(fixture / "manifest.json")
    _require(len(raw_manifest) <= 4096, "fixture manifest exceeds byte bound")
    manifest = json.loads(
        raw_manifest.decode("utf-8"), object_pairs_hook=_unique_object
    )
    _require(
        type(manifest) is dict
        and set(manifest)
        == {
            "schema",
            "source",
            "expected_owner",
            "fact_file",
            "fact_sha256",
            "producer_test",
            "fixture_only",
            "independent_effect_labels",
        },
        "native fixture manifest fields differ",
    )
    _require(
        manifest["schema"] == "hepta-pred-native-fixture-v1"
        and manifest["source"] == "native_test_fixture"
        and manifest["fixture_only"] is True
        and manifest["producer_test"] == PRODUCER_TEST
        and manifest["fact_file"] == "native-fact.json"
        and type(manifest["independent_effect_labels"]) is int
        and manifest["independent_effect_labels"] == 0,
        "fixture source or producer contract differs",
    )
    _digest(manifest["fact_sha256"])
    raw_fact = read_native_fact(fixture / "native-fact.json")
    _require(
        sha256(raw_fact).hexdigest() == manifest["fact_sha256"],
        "native fixture bytes differ from manifest",
    )
    artifact = import_native_events(
        raw_fact, expected_owner=manifest["expected_owner"], source="fixture"
    )
    output = Path(output_dir)
    _require(output.is_absolute(), "smoke output directory must be absolute")
    output.mkdir(mode=0o700)
    _save_new(output / "SOURCE_NATIVE_FACT.json", raw_fact)
    _save_new(output / "SOURCE_NATIVE_MANIFEST.json", raw_manifest)
    abi_path = output / "native-event-abi.json"
    artifact.save(abi_path)
    child_environment = dict(os.environ)
    child_environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    try:
        child = subprocess.run(
            [
                sys.executable,
                "-m",
                "hepta_pred1.native_event_smoke",
                "--verify-abi",
                str(abi_path),
                "--expected-owner",
                manifest["expected_owner"],
                "--expected-native-sha256",
                manifest["fact_sha256"],
            ],
            env=child_environment,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        _save_new(output / "readback.stdout.json", error.stdout or b"")
        _save_new(output / "readback.stderr.log", error.stderr or b"")
        raise ValueError(
            "fresh-process ABI readback timed out; retained partial logs"
        ) from error
    _save_new(output / "readback.stdout.json", child.stdout)
    _save_new(output / "readback.stderr.log", child.stderr)
    _require(
        child.returncode == 0, "fresh-process ABI readback failed; retained child logs"
    )
    readback = json.loads(child.stdout)
    _require(
        type(readback["process_id"]) is int
        and readback["process_id"] != os.getpid()
        and readback["abi_sha256"] == artifact.digest
        and readback["native_fact_sha256"] == manifest["fact_sha256"],
        "fresh-process identity or retained artifact differs",
    )
    report = {
        "schema": "pred1-native-cross-language-smoke-v1",
        "fixture_bridge_status": "PASS",
        "source": "native_test_fixture",
        "producer_test": PRODUCER_TEST,
        "fixture_only": True,
        "native_manifest_sha256": sha256(raw_manifest).hexdigest(),
        "native_fact_sha256": manifest["fact_sha256"],
        "abi_sha256": artifact.digest,
        "import_process_id": os.getpid(),
        "readback": readback,
        "new_live_owner_records": 0,
        "independent_effect_labels": 0,
        "real_policy_comparisons": 0,
        "source_provenance_authenticated": False,
        "production_qualification": "HOLD",
        "production_activation": False,
    }
    _save_new(
        output / "SMOKE_REPORT.json", json.dumps(report, indent=2).encode("utf-8")
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture-dir")
    source.add_argument("--verify-abi")
    parser.add_argument("--output-dir")
    parser.add_argument("--expected-owner")
    parser.add_argument("--expected-native-sha256")
    args = parser.parse_args()
    if args.fixture_dir is not None:
        if (
            args.output_dir is None
            or args.expected_owner is not None
            or args.expected_native_sha256 is not None
        ):
            parser.error("fixture import requires only --fixture-dir and --output-dir")
        report = run_fixture_smoke(args.fixture_dir, args.output_dir)
    else:
        if (
            args.output_dir is not None
            or args.expected_owner is None
            or args.expected_native_sha256 is None
        ):
            parser.error(
                "readback requires --verify-abi, --expected-owner and --expected-native-sha256"
            )
        report = verify_abi(
            args.verify_abi,
            expected_owner=args.expected_owner,
            expected_native_sha256=args.expected_native_sha256,
        )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
