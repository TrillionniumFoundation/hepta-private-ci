"""Bounded process-death integration campaign; all outputs are create-only."""

import argparse
import copy
import gzip
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import scipy

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.world import make_episode
from ..support_retention_r16_20261101.compression import BlockLaw
from ..support_retention_r16_20261101.execution import execute
from .runtime import Session, Store, canonical, digest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODULE = "tools.hcsn.cold_recovery_r17_20261101.runtime"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def launch(database, config_sha, output, label, stop=None):
    command = [sys.executable, "-m", MODULE, str(database), config_sha]
    if stop is not None:
        command += ["--stop-event", stop]
    wall = time.perf_counter()
    with (output / f"{label}.stdout").open("xb") as stdout, (output / f"{label}.stderr").open("xb") as stderr:
        process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr)
        _, status, usage = os.wait4(process.pid, 0)
        code = os.waitstatus_to_exitcode(status)
        process.returncode = code
    receipt = dict(command=command, pid=process.pid, exit_code=code,
        user_cpu_seconds=usage.ru_utime, system_cpu_seconds=usage.ru_stime,
        cpu_seconds=usage.ru_utime + usage.ru_stime, max_rss_kib=usage.ru_maxrss,
        wall_seconds=time.perf_counter() - wall)
    save(output / f"{label}.process.json", receipt)
    starts = [json.loads(line) for line in (output / f"{label}.stdout").read_text().splitlines()]
    if (not starts or starts[0]["event"] != "cold_start"
            or starts[0]["transition_cache_entries"] != 0 or starts[0]["event_cache_entries"] != 0):
        raise AssertionError("Cold cache reconstruction was not observed")
    return receipt


def expect_rejection(function):
    try:
        function()
    except (ValueError, sqlite3.IntegrityError):
        return True
    raise AssertionError("Invalid request was accepted")


def negative_tests(directory, config):
    path = directory / "negative.sqlite"
    store = Store(path, config)
    state = Session(config).initial()
    seq = store.commit(-1, state, "initial")
    results = {}
    wrong = copy.deepcopy(config)
    wrong["model"]["Q"][0][0] -= .1
    results["wrong_model_config"] = expect_rejection(lambda: Store(path, wrong))
    results["invalid_model_payload"] = expect_rejection(lambda: Session(wrong))
    wrong = copy.deepcopy(config)
    wrong["owner_fingerprint"] = "0" * 64
    results["wrong_owner_config"] = expect_rejection(lambda: Store(path, wrong))
    results["wrong_owner_world"] = expect_rejection(lambda: Session(wrong))
    results["stale_sequence_replay"] = expect_rejection(lambda: store.commit(-1, state, "replay"))
    bad_state = copy.deepcopy(state)
    bad_state["config_sha256"] = "0" * 64
    results["state_wrong_run"] = expect_rejection(lambda: Session(config).advance(bad_state))
    store.db.execute("UPDATE state SET body=?", (canonical(bad_state),))
    store.db.commit()
    results["state_corruption"] = expect_rejection(store.load)
    store.db.execute("UPDATE state SET body=?,sha=?", (canonical(state), digest(state)))
    store.db.execute("DELETE FROM history WHERE sequence=?", (seq,))
    store.db.commit()
    results["state_history_rollback"] = expect_rejection(store.load)
    store.db.close()
    # Replay an already-applied effect at the application boundary.
    session, pending_state = Session(config), Session(config).initial()
    while pending_state["pending"] is None or pending_state["pending"]["phase"] != "received":
        session.advance(pending_state)
    pending_state["effects"].append(pending_state["pending"]["id"])
    results["duplicate_effect"] = expect_rejection(lambda: session.advance(pending_state))
    return results


def run(output, manifest_path):
    output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    freeze = json.loads(manifest_path.read_text())
    for path, sha in freeze["files"].items():
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != sha:
            raise ValueError(f"Source changed since freeze: {path}")
    process_receipts, cases, negatives = [], [], None
    owner = Law(tuple(protocol["world_theta"]))
    for domain in protocol["domains"]:
        training_path = ROOT / protocol["training_file"]
        training = json.loads(gzip.decompress(training_path.read_bytes()))
        law = BlockLaw.from_payload(training["calibration"]["models"]["hx"]["payload"])
        seed = protocol["seed"] + (1 if domain == "ood" else 0)
        episode = make_episode(owner, seed, domain)
        for representation in protocol["representations"]:
            for policy, pattern in protocol["policies"]:
                config = dict(model=law.export(), owner_model=owner.export(), seed=seed,
                    domain=domain, owner_fingerprint=episode.fingerprint,
                    representation=representation, policy=policy, pattern=pattern)
                name = f"{domain}_{representation}_{policy}_{pattern}"
                directory = output / name
                directory.mkdir()
                save(directory / "config.json", config)
                # The old execute is the independent control-flow reference.
                old = execute(law, episode, policy=policy, pattern=pattern, representation=representation)
                database = directory / "uninterrupted.sqlite"
                Store(database, config).db.close()
                receipt = launch(database, digest(config), directory, "uninterrupted")
                process_receipts.append(receipt)
                if receipt["exit_code"] != 0:
                    raise AssertionError("Uninterrupted worker failed")
                baseline = Store(database).load()[1]
                if baseline["queries"] != old["queries"]:
                    raise AssertionError("New state machine differs from frozen R16 execution")
                save(directory / "expected.json", baseline)
                events = protocol["fault_events"][pattern] if policy == "fixed" else ["after:query_boundary"]
                for index, stop in enumerate(events):
                    database = directory / f"fault_{index:02d}.sqlite"
                    Store(database, config).db.close()
                    killed = launch(database, digest(config), directory, f"fault_{index:02d}_kill", stop)
                    process_receipts.append(killed)
                    if killed["exit_code"] != -9:
                        raise AssertionError(f"Requested fault did not kill worker: {stop}")
                    suspended = Store(database).load()[1]
                    save(directory / f"fault_{index:02d}_suspended.json", suspended)
                    resumed = launch(database, digest(config), directory, f"fault_{index:02d}_resume")
                    process_receipts.append(resumed)
                    actual = Store(database).load()[1]
                    if resumed["exit_code"] != 0 or actual != baseline:
                        raise AssertionError(f"Recovered trace/state/effects differ: {stop}")
                    cases.append(dict(case=name, stop=stop, equal_complete_state=True,
                        expected_sha256=digest(baseline), actual_sha256=digest(actual),
                        pending_at_death=suspended["pending"], status_at_death=suspended["status"],
                        sqlite_bytes=database.stat().st_size))
                if negatives is None and policy == "fixed" and pattern == "wait_read":
                    negatives = negative_tests(output, config)
    summary = dict(schema="hcsn-r17-cold-recovery-results-v1", scope=protocol["scope"],
        source_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        source_manifest=str(manifest_path.relative_to(ROOT)),
        cases=cases, recovery_cases=len(cases), negative_rejections=negatives,
        all_passed=all(c["equal_complete_state"] for c in cases) and all(negatives.values()),
        complete_child_cpu_seconds=sum(r["cpu_seconds"] for r in process_receipts),
        killed_child_cpu_seconds=sum(r["cpu_seconds"] for r in process_receipts if r["exit_code"] == -9),
        process_count=len(process_receipts), environment=dict(python=sys.version,
        numpy=np.__version__, scipy=scipy.__version__, platform=platform.platform()),
        unmeasured=protocol["unmeasured"], production_activation=False)
    save(output / "SUMMARY.json", summary)
    print(canonical({k: v for k, v in summary.items() if k != "cases"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=HERE / "SOURCE_MANIFEST.json")
    args = parser.parse_args()
    run(args.output.resolve(), args.manifest.resolve())
