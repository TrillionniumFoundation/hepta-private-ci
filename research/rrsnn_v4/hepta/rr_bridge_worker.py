"""One research host transaction; an external supervisor pins every frontier.

The pending proposal is durably pinned outside this process before native commit.
This file does not grant production authority or replace a protected owner store.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

from rr_bridge_backend import ZERO, digest, read, sha, write


def event(stage, **fields):
    print(json.dumps({"stage": stage, **fields}, allow_nan=False), flush=True)
    if sys.stdin.readline().strip() != "go":
        raise ValueError("ExternalSupervisorAcknowledgementRequired")


def invoke(command):
    result = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def checked_pending(args, path):
    if not args.pending_pin or sha(path) != args.pending_pin:
        raise ValueError("IndependentPendingIntentPinRequired")
    pending = read(path)
    if (pending["manifest_sha256"] != args.manifest_pin
            or pending["admission_sha256"] != sha(args.admission)
            or pending["sequence"] != read(args.admission)["sequence"]):
        raise ValueError("PendingIntentBindingMismatch")
    for field, expected in [(pending["prepared_path"], pending["prepared_sha256"]),
                            (pending["next_frontier"]["state_path"], pending["next_frontier"]["state_sha256"])]:
        if sha(args.root / field) != expected:
            raise ValueError("PendingArtifactPinMismatch")
    if digest(pending["next_frontier"]) != pending["next_frontier_sha256"]:
        raise ValueError("PendingFrontierChecksumMismatch")
    return pending


def publish(args, pending, native_process=None, backend_executed=False, reconciled=False):
    current = sha(args.root / "frontier.json")
    allowed = [pending["previous_frontier_sha256"], pending["next_frontier_sha256"]]
    if args.frontier_pin not in allowed or current not in allowed:
        raise ValueError("JointFrontierOutsideTrustedIntent")
    if args.frontier_pin == pending["next_frontier_sha256"] and current != args.frontier_pin:
        raise ValueError("PublishedJointFrontierRolledBack")
    write(args.root / "frontier.json", pending["next_frontier"], immutable=False)
    event("joint_file_written", frontier_sha256=pending["next_frontier_sha256"],
          pending_sha256=sha(args.root / "pending" / f"sequence-{pending['sequence']:04}.json"))
    event("joint_published", frontier_sha256=pending["next_frontier_sha256"],
          checkpoint=pending["expected_native_checkpoint"], sequence=pending["sequence"])
    if native_process is not None:
        native_process.stdin.write("go\n")
        native_process.stdin.flush()
        code = native_process.wait(timeout=30)
        if code:
            raise RuntimeError(native_process.stderr.read())
    prepared = read(args.root / pending["prepared_path"])
    print(json.dumps({"stage": "done", "sequence": pending["sequence"],
        "frontier_sha256": pending["next_frontier_sha256"], "native_checkpoint": pending["expected_native_checkpoint"],
        "state_sha256": pending["next_frontier"]["state_sha256"], "backend_executed_this_attempt": backend_executed,
        "reconciled_without_model_execution": reconciled, "authority": False,
        "drive_q24": prepared["drive_q24"], "actual_internal_spikes": prepared["actual_internal_spikes"]}), flush=True)


def run(args):
    if sha(args.manifest) != args.manifest_pin:
        raise ValueError("IndependentManifestPinMismatch")
    manifest = read(args.manifest)
    if sha(args.native) != manifest["native_binary_sha256"]:
        raise ValueError("ActualNativeBinaryIdentityMismatch")
    if sha(args.backend) != manifest["source_sha256"]["rrsnn_v4/hepta/rr_bridge_backend.py"]:
        raise ValueError("ActualBackendScriptIdentityMismatch")
    if sha(args.python) != manifest["python_executable_sha256"]:
        raise ValueError("ActualPythonExecutableIdentityMismatch")
    admission = read(args.admission)
    if admission["manifest_sha256"] != args.manifest_pin:
        raise ValueError("AdmissionManifestMismatch")
    with (args.root / "host-owner.lock").open("ab") as owner_lock:
        try:
            fcntl.flock(owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("ResearchOwnerBusy") from None
        pending_path = args.root / "pending" / f"sequence-{admission['sequence']:04}.json"
        pending = None
        if pending_path.exists():
            pending = checked_pending(args, pending_path)
            current = sha(args.root / "frontier.json")
            if current not in [pending["previous_frontier_sha256"], pending["next_frontier_sha256"]]:
                raise ValueError("JointFrontierOutsideTrustedIntent")
            if args.frontier_pin == pending["next_frontier_sha256"] and current != args.frontier_pin:
                raise ValueError("PublishedJointFrontierRolledBack")
            if args.frontier_pin not in [pending["previous_frontier_sha256"], pending["next_frontier_sha256"]]:
                raise ValueError("UnrelatedTrustedFrontier")
            actual = invoke([args.native, "recover", args.root / "native", args.manifest])
            if actual["checkpoint"] == pending["expected_native_checkpoint"]:
                if actual["sequence"] != admission["sequence"] or actual["model_calls"] != 0:
                    raise ValueError("NativeRecoveredSequenceMismatch")
                publish(args, pending, reconciled=True)
                return
            if (actual["checkpoint"] != pending["previous_native_checkpoint"]
                    or actual["sequence"] != admission["sequence"] - 1
                    or current != pending["previous_frontier_sha256"]):
                raise ValueError("NativeJointFrontierInconsistent")
        elif args.pending_pin:
            raise ValueError("MissingIndependentlyPinnedPendingIntent")
        if sha(args.root / "frontier.json") != args.frontier_pin or args.frontier_pin != admission["expected_frontier_sha256"]:
            raise ValueError("CurrentFrontierPinMismatch")
        frontier = read(args.root / "frontier.json")
        if frontier["sequence"] + 1 != admission["sequence"]:
            raise ValueError("NoncontiguousAdmittedSequence")
        phase = args.fault if args.fault in ["before_witness", "after_witness"] else "none"
        command = [args.native, "tick", args.root / "native", args.manifest, args.admission,
                   args.python, args.backend, args.root, phase]
        environment = dict(os.environ)
        for key in ("RR_BRIDGE_TRUSTED_PREPARED_PATH", "RR_BRIDGE_TRUSTED_PREPARED_SHA256"):
            environment.pop(key, None)
        if pending is not None:
            environment["RR_BRIDGE_TRUSTED_PREPARED_PATH"] = pending["prepared_path"]
            environment["RR_BRIDGE_TRUSTED_PREPARED_SHA256"] = pending["prepared_sha256"]
        process = subprocess.Popen(list(map(str, command)), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, env=environment)
        try:
            while True:
                line = process.stdout.readline()
                if not line:
                    code = process.wait(timeout=30)
                    raise RuntimeError(f"NativeBrokerExitedBeforeCommit[{code}]: " + process.stderr.read())
                row = json.loads(line)
                if row["stage"] == "prepared":
                    backend = row["backend"]
                    path = Path(backend["prepared_path"])
                    relative = path.resolve().relative_to(args.root.resolve())
                    if sha(path) != backend["prepared_sha256"]:
                        raise ValueError("PreparedTransportPinMismatch")
                    prepared = read(path)
                    if prepared["admission_sha256"] != sha(args.admission):
                        raise ValueError("PreparedAdmissionMismatch")
                    history = frontier["history"] + [{"prepared_path": str(relative), "prepared_sha256": sha(path)}]
                    prediction = []
                    for item in history:
                        source = args.root / item["prepared_path"]
                        if sha(source) != item["prepared_sha256"]:
                            raise ValueError("CommittedHistoryPinMismatch")
                        old = read(source)
                        if sha(args.root / old["admission_path"]) != old["admission_sha256"]:
                            raise ValueError("HistoricalAdmissionPinMismatch")
                        prediction.append({"admission_path": str(args.root / old["admission_path"]),
                                           "drive_q24": old["drive_q24"], "prediction_q24": old["prediction_q24"]})
                    predict_path = args.root / "predictions" / f"sequence-{admission['sequence']:04}.json"
                    # Only the predictor input contains local absolute paths; it is not a protocol identity.
                    write(predict_path, prediction, immutable=False)
                    predicted = invoke([args.native, "predict", args.manifest, predict_path])
                    previous = predicted["anchors"][-2] if len(predicted["anchors"]) > 1 else ZERO
                    if previous != frontier["native_checkpoint"] or len(predicted["anchors"]) != admission["sequence"]:
                        raise ValueError("IndependentNativePrefixMismatch")
                    following = {"schema": frontier["schema"], "manifest_sha256": args.manifest_pin,
                        "sequence": admission["sequence"], "native_checkpoint": predicted["anchors"][-1],
                        "state_path": prepared["state_after_path"], "state_sha256": prepared["state_after_sha256"],
                        "history": history, "previous_frontier_sha256": args.frontier_pin}
                    proposal = {"schema": "rrsnn.v4.pending-joint-feature.v1", "manifest_sha256": args.manifest_pin,
                        "admission_sha256": sha(args.admission), "sequence": admission["sequence"],
                        "previous_frontier_sha256": args.frontier_pin, "previous_native_checkpoint": previous,
                        "prepared_path": str(relative), "prepared_sha256": sha(path),
                        "expected_native_checkpoint": predicted["anchors"][-1], "next_frontier": following,
                        "next_frontier_sha256": digest(following)}
                    if pending is None:
                        event("unconfirmed_prepared", prepared_sha256=sha(path),
                              state_after_sha256=prepared["state_after_sha256"])
                    write(pending_path, proposal)
                    if pending is not None and pending != proposal:
                        raise ValueError("RetryChangedPinnedProposal")
                    pending = proposal
                    event("prepared", pending_sha256=sha(pending_path),
                          expected_native_checkpoint=pending["expected_native_checkpoint"],
                          next_frontier_sha256=pending["next_frontier_sha256"],
                          backend_executed=backend["backend_executed"],
                          state_after_sha256=prepared["state_after_sha256"],
                          official_feature_receipt_digest=row["feature_receipt_digest"])
                    process.stdin.write("go\n"); process.stdin.flush()
                elif row["stage"] in ["before_witness", "after_witness"]:
                    if pending is None or row["checkpoint"] != pending["expected_native_checkpoint"]:
                        raise ValueError("WitnessBarrierCheckpointMismatch")
                    event(row["stage"], checkpoint=row["checkpoint"], sequence=row["sequence"])
                    process.stdin.write("go\n"); process.stdin.flush()
                elif row["stage"] == "committed":
                    if (pending is None or row["checkpoint"] != pending["expected_native_checkpoint"]
                            or row["sequence"] != pending["sequence"] or row["authority"] is not False
                            or row["abstain"] is not True):
                        raise ValueError("NativeCommittedResultMismatch")
                    publish(args, pending, process, backend_executed=row["backend_executed"])
                    return
                else:
                    raise ValueError("UnexpectedNativeProtocolStage")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("root", "manifest", "admission", "native", "backend", "python"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--manifest-pin", required=True)
    parser.add_argument("--frontier-pin", required=True)
    parser.add_argument("--pending-pin")
    parser.add_argument("--fault", default="none")
    arguments = parser.parse_args()
    try:
        run(arguments)
    except Exception as error:
        print(json.dumps({"error": type(error).__name__ + ": " + str(error)}), file=sys.stderr)
        raise SystemExit(2)
