#!/usr/bin/env python3
"""Verify acknowledged cross-process recovery for every fitted model/controller.

Uses existing validation worlds and autonomous frozen policies only. This is an
implementation qualification; it neither selects policies nor estimates utility.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
from tools.hcsn.digital_read_before_20261031.native.pack_evidence import collect, emit

LOGICAL_RECEIPT_FIELDS = (
    "sequence", "action", "action_name", "forced_control", "mode", "before", "after",
    "public_features", "representation_features", "q", "belief_logit", "belief", "legal",
    "cell_before", "cell_after", "cell_event", "draw", "due_source", "completion", "content",
    "content_error", "attempted_packet_paths", "opened_packet_paths", "read_audit",
    "actual_content_calls", "duration", "charges", "signals_q24",
)
LOGICAL_PAIR_FIELDS = ("schema", "identity", "sequence", "task", "cell", "content", "ledger")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+"\n")


def logical(value, keys):
    return {key: value[key] for key in keys}


def frontier(snapshot):
    return {suffix: sha(Path(str(snapshot)+suffix)) for suffix in ("", ".journal", ".witness")}


def valid_initial_packet(public_path, public):
    """Check availability and syntax only, never decode a target or inspect evaluator data."""
    packet = public_path.parent/public["packets"][0]
    if not packet.is_file() or packet.is_symlink() or sha(packet) != public["packet_sha256"][0]:
        return False
    try:
        data = json.loads(packet.read_text())
        symbols, dt = data["symbols"], data["dt"]
        return (data["schema"] == "hcsn.memory.packet.v1" and 2 <= len(symbols) <= 128
                and symbols[-1] == -1 and all(type(x) is int and 0 <= x < 4 for x in symbols[:-1])
                and len(dt) == len(symbols) and all(math.isfinite(x) and x > 0 for x in dt))
    except (KeyError, ValueError, TypeError):
        return False


class Qualification:
    def __init__(self, args):
        self.args = args
        self.work = args.work_dir.resolve()
        self.work.mkdir(parents=True, exist_ok=False)
        self.protocol = json.loads(args.protocol.read_text())
        self.build = json.loads(args.build_receipt.read_text())
        self.binary_sha256 = sha(args.binary)
        assert self.binary_sha256 == self.build["binary_sha256"], "binary differs from verified build"
        self.source_digest = self.build["source_digest"]
        self.content_sha256 = sha(args.content_model)
        self.models, self.worlds, self.runs, self.cases = [], [], [], []
        self.driver_sha256 = sha(Path(__file__))

    def choose_world(self, fit):
        candidates = []
        for path in sorted((self.args.training_root/f"fit_{fit}"/"data").glob(f"validation_fit{fit}_*/public.json")):
            public = json.loads(path.read_text())
            if public["read_delay"][0] == 2:
                candidates.append((path, public, valid_initial_packet(path, public)))
        if not candidates:
            raise ValueError(f"fit {fit}: no existing validation world with initial delay two")
        path, public, valid = next((x for x in candidates if x[2]), candidates[0])
        chosen = self.work/"validation_inputs"/f"fit_{fit}"
        chosen.mkdir(parents=True)
        shutil.copyfile(path, chosen/"public.json")
        packets = []
        for name, expected in zip(public["packets"], public["packet_sha256"], strict=True):
            packet = path.parent/name
            present = packet.is_file()
            row = dict(name=name, exists=present, expected_sha256=expected)
            if present:
                shutil.copyfile(packet, chosen/name)
                row.update(sha256=sha(packet), bytes=packet.stat().st_size)
            packets.append(row)
        selection = dict(fit=fit, public_path=str(path), public_sha256=sha(path), world=public["id"],
                         selection="first lexicographic existing validation world with initial delay two and valid initial packet, if available",
                         initial_packet_valid=valid, packets=packets,
                         candidate_initial_delays_two=len(candidates), no_evaluator_or_decoded_label_access=True)
        self.worlds.append(selection)
        return path, public

    def invoke(self, directory, public, policy, controller, seed, snapshot, steps, ack=None):
        directory.mkdir(parents=True)
        command = [str(self.args.binary), "--public", str(public), "--content-model", str(self.args.content_model),
                   "--policy", str(policy), "--controller", controller, "--snapshot", str(snapshot),
                   "--seed", str(seed), "--steps", str(steps), "--mode", "qualification"]
        if ack is not None:
            command += ["--ack", ack]
        before_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
        start = time.perf_counter()
        process = subprocess.run(command, capture_output=True, text=True, timeout=60)
        wall = time.perf_counter()-start
        after_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu = after_cpu.ru_utime+after_cpu.ru_stime-before_cpu.ru_utime-before_cpu.ru_stime
        stdout, stderr = directory/"stdout.json", directory/"stderr.txt"
        stdout.write_text(process.stdout)
        stderr.write_text(process.stderr)
        run = dict(command=command, returncode=process.returncode, stdout_sha256=sha(stdout),
                   stderr_sha256=sha(stderr), external_wall_seconds=wall, external_cpu_seconds=cpu,
                   output_directory=str(directory), requested_steps=steps, resume=ack is not None)
        save(directory/"invocation.json", run)
        self.runs.append(run)
        assert process.returncode == 0, (command, process.stderr)
        result = json.loads(process.stdout)
        assert result["actual_native"] and not result["production_activation"]
        assert result["source_digest"] == self.source_digest and result["authority"] == "DENY_ALL"
        assert result["mode"] == "qualification" and result["forced_control"] is False
        assert result["external_ack_verified"] == (ack is not None)
        assert result["acknowledged_sha256"] == sha(snapshot)
        assert json.loads(snapshot.read_text()) == result["after"]
        identity = result["after"]["identity"]
        assert identity["policy_sha256"] == sha(policy) and identity["public_sha256"] == sha(public)
        assert identity["content_model_sha256"] == self.content_sha256
        assert identity["controller"] == controller and identity["seed"] == seed
        for receipt in result["receipts"]:
            assert receipt["forced_control"] is False and receipt["mode"] == "qualification"
            assert receipt["actual_content_calls"] == receipt["read_audit"]["model_executions"]
            assert len(receipt["attempted_packet_paths"]) == receipt["read_audit"]["open_attempts"]
            assert len(receipt["opened_packet_paths"]) == receipt["read_audit"]["successful_opens"]
        return result

    def case(self, fit, family, controller, public, public_data, model):
        directory = self.work/"cases"/f"fit_{fit}"/family/controller
        full_snapshot, split_snapshot = directory/"continuous"/"owner.json", directory/"split_first"/"owner.json"
        seed = 918000+fit
        full = self.invoke(directory/"continuous", public, model, controller, seed, full_snapshot, 7)
        first = self.invoke(directory/"split_first", public, model, controller, seed, split_snapshot, 1)
        assert len(first["receipts"]) == 1
        first_frontier = frontier(split_snapshot)
        acknowledged = directory/"acknowledged_after_step1"
        acknowledged.mkdir()
        for suffix in ("", ".journal", ".witness"):
            shutil.copyfile(str(split_snapshot)+suffix, acknowledged/("owner.json"+suffix))
        resumed = self.invoke(directory/"split_resumed", public, model, controller, seed, split_snapshot, 6,
                              first["acknowledged_sha256"])
        assert resumed["before"] == first["after"], "cross-process checkpoint did not restore exactly"
        combined = first["receipts"]+resumed["receipts"]
        assert len(combined) == len(full["receipts"])
        for continuous, recovered in zip(full["receipts"], combined, strict=True):
            assert logical(continuous, LOGICAL_RECEIPT_FIELDS) == logical(recovered, LOGICAL_RECEIPT_FIELDS), (fit, family, controller)
        assert logical(full["after"], LOGICAL_PAIR_FIELDS) == logical(resumed["after"], LOGICAL_PAIR_FIELDS)
        content_calls = sum(r["actual_content_calls"] for r in full["receipts"])
        assert content_calls == sum(r["actual_content_calls"] for r in combined)
        assert full["after"]["task"]["terminal"] and resumed["after"]["task"]["terminal"]
        initial_terminal = first["after"]["task"]["terminal"]
        pending = first["after"]["task"]["pending"]
        classification = "initial_terminal_noop_recovery" if initial_terminal else "nonterminal_recovery"
        pending_disposition = None
        if initial_terminal:
            assert resumed["receipts"] == [] and resumed["after"] == first["after"]
            assert frontier(split_snapshot) == first_frontier
            assert resumed["persistence_bytes"] == 0
        elif pending is not None:
            classification = "pending_recovery"
            assert pending == dict(source_tick=0, due_tick=2)
            assert first["receipts"][0]["read_audit"] == dict(open_attempts=0, successful_opens=0, bytes_read=0, model_executions=0)
            next_receipt = resumed["receipts"][0]
            if next_receipt["action"] in (0, 4, 5):
                pending_disposition = "autonomous_cancel_without_open"
                assert next_receipt["actual_content_calls"] == 0 and next_receipt["read_audit"]["open_attempts"] == 0
            else:
                pending_disposition = "completed_once_at_due_boundary"
                assert next_receipt["before"]["tick"] == 1 and next_receipt["after"]["tick"] == 2
                assert next_receipt["due_source"] == 0 and next_receipt["read_audit"]["open_attempts"] == 1
                assert next_receipt["actual_content_calls"] == 1
                assert next_receipt["completion"].get("failure", False) is False
        report = dict(fit=fit, family=family, controller=controller, world=public_data["id"],
                      model_sha256=sha(model), public_sha256=sha(public), seed=seed, passed=True,
                      classification=classification, first_action=first["receipts"][0]["action_name"],
                      pending_disposition=pending_disposition, total_decisions=len(full["receipts"]),
                      actual_content_calls=content_calls, final_task=full["after"]["task"],
                      final_cell=full["after"]["cell"],
                      acknowledged_first_frontier=first_frontier,
                      continuous_final_ack=full["acknowledged_sha256"], resumed_final_ack=resumed["acknowledged_sha256"],
                      continuous_cost=dict(wall_nanos=full["wall_nanos"], cpu_nanos=full["cpu_nanos"], persistence_bytes=full["persistence_bytes"]),
                      split_cost=dict(wall_nanos=first["wall_nanos"]+resumed["wall_nanos"],
                                      cpu_nanos=first["cpu_nanos"]+resumed["cpu_nanos"],
                                      persistence_bytes=first["persistence_bytes"]+resumed["persistence_bytes"]))
        self.cases.append(report)
        save(directory/"case.json", report)

    def execute(self):
        start = time.perf_counter()
        for fit in self.protocol["fits"]:
            public, public_data = self.choose_world(fit)
            for family in self.protocol["families"]:
                model = self.args.training_root/f"fit_{fit}"/"models"/f"{family}.json"
                artifact = json.loads(model.read_text())
                assert artifact["fit"] == fit and artifact["family"] == family
                identity = dict(fit=fit, family=family, path=str(model), sha256=sha(model), bytes=model.stat().st_size)
                self.models.append(identity)
                for controller in self.protocol["controllers"]:
                    self.case(fit, family, controller, public, public_data, model)
                assert sha(model) == identity["sha256"], "model changed during qualification"
            print(json.dumps(dict(fit=fit, cases_completed=len(self.cases), process_invocations=len(self.runs))), flush=True)
        assert len(self.models) == 25 and len(self.cases) == 50 and len(self.runs) == 150
        assert sha(self.args.binary) == self.binary_sha256 and sha(self.args.content_model) == self.content_sha256
        for model in self.models:
            assert sha(model["path"]) == model["sha256"]
        report = dict(schema="digital-read-before-trained-ack-qualification-v1", passed=True,
                      scope="All 25 frozen fitted models and both autonomous controllers; existing validation worlds only; no efficacy inference or model selection",
                      driver_sha256=self.driver_sha256, binary_sha256=self.binary_sha256,
                      source_digest=self.source_digest, content_model_sha256=self.content_sha256,
                      protocol_sha256=sha(self.args.protocol), models=self.models, validation_worlds=self.worlds,
                      case_count=len(self.cases), process_invocations=len(self.runs),
                      classifications=dict(Counter(case["classification"] for case in self.cases)),
                      pending_dispositions=dict(Counter(case["pending_disposition"] for case in self.cases if case["pending_disposition"])),
                      every_action_autonomous=True, forced_control=False, Rust_source_modified=False,
                      compared_receipt_fields=list(LOGICAL_RECEIPT_FIELDS), compared_final_pair_fields=list(LOGICAL_PAIR_FIELDS),
                      equality="exact JSON numerical/logical equality, not tolerance; native checkpoint digests and timing differ legitimately because runtime receipts include measured latency",
                      wall_seconds=time.perf_counter()-start, cases=self.cases, runs=self.runs)
        save(self.args.receipt, report)
        save(self.work/"REPORT.json", report)
        archives = emit(collect(self.work, "trained_qualification"), "TRAINED_ACK_QUALIFICATION_RAW", self.args.receipt.parent)
        archive_manifest = dict(schema="digital-read-before-trained-ack-archive-v1", archives=archives,
                                byte_exact=True, gzip_mtime=0, maximum_archive_bytes=512000,
                                qualification_report_sha256=sha(self.args.receipt))
        save(self.args.receipt.parent/"TRAINED_ACK_ARCHIVES.json", archive_manifest)
        print(json.dumps({key: report[key] for key in ("passed", "case_count", "process_invocations", "classifications", "pending_dispositions", "wall_seconds")}, indent=2))
        print(json.dumps(archive_manifest, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--content-model", type=Path, required=True)
    parser.add_argument("--build-receipt", type=Path, default=HERE/"evidence/NATIVE_BUILD.json")
    parser.add_argument("--protocol", type=Path, default=HERE/"protocol.json")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, default=HERE/"evidence/TRAINED_ACK_QUALIFICATION.json")
    Qualification(parser.parse_args()).execute()
