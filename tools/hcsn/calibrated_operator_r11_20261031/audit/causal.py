"""Native recovery, content-access and identity audit on development data only.

The frozen owner selects every action. This audit never supplies an action,
changes the trained policy for an efficacy run, or accesses a heldout fixture.
Linux inotify records packet/label OPEN and ACCESS alongside native receipts.
"""
import argparse
import copy
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import tarfile
import time
import traceback

from ...task_native_loop_20261031.audit import NativeRunner, digest, process_costs, require, write
from ...task_native_loop_20261031.experiment import verify_build


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
DECISION_KEYS = ("sequence", "action", "before", "public_features", "cell_features",
                 "q", "legal", "driver", "horizon_micros", "signals_q24")
RECEIPT_KEYS = DECISION_KEYS + ("after", "event")


def semantic_pair(pair):
    """Physical/task state; native timing-dependent anchor bytes stay separate."""
    return {key: pair[key] for key in ("sequence", "task", "cell", "content")}


def semantic_receipt(receipt):
    return {key: receipt[key] for key in RECEIPT_KEYS}


def inventory(snapshot):
    return {p.name: digest(p) for p in sorted(snapshot.parent.glob(snapshot.name + "*"))
            if p.is_file()}


class FileAccess:
    """Kernel events scoped to copied packet and evaluator-label files.

    Files are watched before spawning the child, and no audit packet hashing or
    parsing runs while watches are active. IN_Q_OVERFLOW is a hard failure.
    Repeated ACCESS events may coalesce; this is access evidence, not byte count.
    """
    OPEN, ACCESS, CLOSE, OVERFLOW = 0x20, 0x01, 0x10, 0x4000

    def __init__(self, folder, names):
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.inotify_init1.argtypes = [ctypes.c_int]
        self.libc.inotify_init1.restype = ctypes.c_int
        self.libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self.libc.inotify_add_watch.restype = ctypes.c_int
        self.fd = self.libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1")
        self.names, self.events = {}, []
        try:
            for name in names:
                path = folder / name
                if not path.exists():
                    continue
                wd = self.libc.inotify_add_watch(self.fd, os.fsencode(path),
                    self.OPEN | self.ACCESS | self.CLOSE)
                if wd < 0:
                    raise OSError(ctypes.get_errno(), "inotify_add_watch", str(path))
                self.names[wd] = name
        except BaseException:
            os.close(self.fd)
            raise

    def finish(self):
        try:
            while True:
                try:
                    data = os.read(self.fd, 65536)
                except BlockingIOError:
                    break
                offset = 0
                while offset < len(data):
                    wd, mask, cookie, length = struct.unpack_from("iIII", data, offset)
                    offset += 16 + length
                    require(not mask & self.OVERFLOW, "inotify queue overflow invalidates access evidence")
                    self.events.append(dict(file=self.names.get(wd), mask=mask, cookie=cookie,
                        open=bool(mask & self.OPEN), access=bool(mask & self.ACCESS),
                        close=bool(mask & self.CLOSE)))
        finally:
            os.close(self.fd)
        return self.events


class ObservedRunner(NativeRunner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.meta = json.loads(self.public.read_text())
        self.names = [name for row in self.meta["packets"] for name in row]
        self.access_reports = []

    def run(self, steps, ack=None, expect_rejection=False):
        index = len(self.invocations)
        observer = FileAccess(self.public.parent, self.names + ["evaluator_labels.json"])
        result, error = None, None
        try:
            result = super().run(steps, ack, expect_rejection)
        except BaseException as exc:
            error = exc
        events = observer.finish()
        native = (json.loads(result["stdout"]) if expect_rejection else result) or {}
        expected = [self.meta["packets"][r["event"]["job"]][r["event"]["tick"]]
                    for r in native.get("receipts", []) if r["action"] == "READ"]
        opened = [e["file"] for e in events if e["open"]]
        accessed = sorted({e["file"] for e in events if e["access"]})
        report = dict(schema="hcsn.native.file-access.audit.r11.v1", events=events,
            expected_read_opens=expected, observed_opens=opened, observed_accessed_files=accessed,
            watched_files=self.names + ["evaluator_labels.json"],
            exact_open_order=opened == expected, exact_accessed_set=accessed == sorted(set(expected)),
            evaluator_label_access=False if "evaluator_labels.json" not in opened + accessed else True,
            scope="Linux inotify OPEN/ACCESS/CLOSE on isolated regular-file copies during one native process; ACCESS events can coalesce; not a syscall byte counter.")
        write(self.evidence / f"packet_access_{index:03d}.json", report)
        self.access_reports.append(report)
        if error:
            raise error
        require(report["exact_open_order"] and report["exact_accessed_set"],
                "observed packet I/O differs from the actions actually selected by native execution")
        require(not report["evaluator_label_access"], "native execution accessed evaluator labels")
        return result


def checked(runner, steps, source_digest, ack=None):
    result = runner.run(steps, ack)
    require(result["source_digest"] == source_digest, "native source identity differs from build receipt")
    require(result["policy_sha256"] == digest(runner.policy)
            and result["public_sha256"] == digest(runner.public)
            and result["content_model_sha256"] == digest(runner.content), "artifact identity mismatch")
    require(result["external_ack_verified"] == (ack is not None), "external acknowledgement mismatch")
    require(result["native_neuron_runtime"] and result["finite_kernel"]
            and not result["production_activation"] and result["authority"] == "DENY_ALL",
            "research runtime authority boundary differs")
    require(digest(runner.snapshot) == result["acknowledged_sha256"], "snapshot acknowledgement mismatch")
    require(json.loads(runner.snapshot.read_text()) == result["end"], "snapshot and returned pair differ")
    previous = result["start"]["task"]
    for receipt in result["receipts"]:
        require(receipt["before"] == previous, "task receipt chain differs")
        require(receipt["after"]["history"] == previous["history"] + [receipt["event"]],
                "acknowledged history did not append exactly once")
        previous = receipt["after"]
    require(result["end"]["task"] == previous, "final task differs from final receipt")
    return result


def audit(args):
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    findings, runners = {}, []
    report = dict(schema="hcsn.native-causal-recovery.audit.r11.v1", success=False,
                  findings=findings, production_activation=False, authority="DENY_ALL",
                  efficacy_claim=False, heldout_data_accessed=False)
    try:
        build = verify_build(args.binary.resolve(), args.build_report.resolve())
        freeze = json.loads(args.freeze.read_text())
        require(digest(args.freeze) == args.freeze_sha256, "frozen training identity changed")
        model_name = str(args.policy.resolve().relative_to(args.freeze.resolve().parent))
        require(freeze["models"][model_name]["sha256"] == digest(args.policy), "policy is not the frozen model")
        meta = json.loads(args.public.read_text())
        require(meta["id"].startswith(("train_", "validation_")), "audit requires an existing development fixture")
        packet_names = [name for row in meta["packets"] for name in row]
        source_names = ["public.json", "evaluator_labels.json"] + packet_names
        fixture_hashes = {name: digest(args.public.parent / name) for name in source_names}
        with tarfile.open(args.fixture_archive, "r:gz") as archive:
            for name, expected in fixture_hashes.items():
                member = archive.extractfile(meta["id"] + "/" + name)
                require(member is not None and hashlib.sha256(member.read()).hexdigest() == expected,
                        "fixture bytes differ from archived development data: " + name)
        inputs = dict(binary=str(args.binary.resolve()), binary_sha256=digest(args.binary),
            build_report_sha256=digest(args.build_report), source_digest=build["source_digest"],
            training_freeze_sha256=digest(args.freeze), policy_sha256=digest(args.policy),
            content_model_sha256=digest(args.content), public_sha256=digest(args.public),
            fixture_archive_sha256=digest(args.fixture_archive), fixture_id=meta["id"],
            fixture_file_sha256=fixture_hashes, audit_source_sha256=digest(__file__),
            imported_runner_sha256=digest(REPO / "tools/hcsn/task_native_loop_20261031/audit.py"),
            all_dependency_archives_verified=build["all_dependency_archives_verified"])
        write(output / "INPUTS.json", inputs)
        shutil.copyfile(__file__, output / "AUDIT_SOURCE.py")
        report["inputs"] = inputs

        def case(name, mutation=None):
            folder = output / name
            session = folder / "input"
            session.mkdir(parents=True)
            for filename in source_names:
                shutil.copyfile(args.public.parent / filename, session / filename)
            shutil.copyfile(args.public, session / "native_public.json")
            shutil.copyfile(args.policy, folder / "policy.json")
            if mutation:
                mutation(session)
            runner = ObservedRunner(args.binary, args.content, session / "native_public.json",
                                    folder / "policy.json", folder / "state.json", folder / "raw")
            runners.append(runner)
            return runner

        def run(runner, steps, ack=None):
            return checked(runner, steps, build["source_digest"], ack)

        baseline_runner = case("continuous")
        baseline = run(baseline_runner, 32)
        receipts = baseline["receipts"]
        require(baseline["end"]["task"]["terminal"] and len(receipts) >= 3,
                "development fixture must terminate after at least three actions")
        require(any(r["action"] == "READ" and r["event"]["error"] is None for r in receipts),
                "development fixture supplies no actual successful READ witness")
        baseline_trace = [semantic_receipt(r) for r in receipts]
        findings["baseline"] = dict(actions=[r["action"] for r in receipts],
            successful_reads=baseline["end"]["content"]["completed_reads"],
            task=baseline["end"]["task"], read_opens=baseline_runner.access_reports[0]["observed_opens"])

        restarted_runner = case("restarted")
        restarted, ack = [], None
        for _ in range(32):
            result = run(restarted_runner, 1, ack)
            require(len(result["receipts"]) == 1, "one-step recovery must perform exactly one action")
            if restarted:
                require(semantic_pair(result["start"]) == semantic_pair(restarted[-1]["end"]),
                        "resume changed the acknowledged state before its next action")
            restarted.append(result)
            ack = result["acknowledged_sha256"]
            if result["end"]["task"]["terminal"]:
                break
        require([semantic_receipt(r["receipts"][0]) for r in restarted] == baseline_trace,
                "fresh-process recovery changed the task/decision/content receipt trajectory")
        require(semantic_pair(restarted[-1]["end"]) == semantic_pair(baseline["end"]),
                "fresh-process recovery changed final exact task/cell/content state")
        # A complete-process output only contains the final cell snapshot. Fresh
        # uninterrupted prefixes establish exact cell/content equality at EVERY
        # acknowledged boundary, without inventing missing intermediate states.
        for length, resumed in enumerate(restarted, 1):
            prefix = baseline if length == len(restarted) else run(case(f"prefix_{length:02d}"), length)
            require([semantic_receipt(r) for r in prefix["receipts"]] == baseline_trace[:length],
                    "uninterrupted prefix diverged from complete run")
            require(semantic_pair(prefix["end"]) == semantic_pair(resumed["end"]),
                    "task/cell/content differs at an acknowledged action boundary")
        findings["recovery"] = dict(passed=True, boundaries=len(restarted),
            full_task_cell_content_exact_at_every_boundary=True,
            fresh_process_pids=[r["pid"] for r in restarted_runner.invocations],
            continuous_cost=process_costs(baseline_runner), restarted_cost=process_costs(restarted_runner),
            excluded_fields=["native timing", "native_checkpoint", "acknowledged_sha256", "journal byte cost"],
            scope="Acknowledged synchronous action boundaries; no mid-action crash/replay guarantee.")

        labels = json.loads((args.public.parent / "evaluator_labels.json").read_text())
        def flip_labels(folder):
            altered = copy.deepcopy(labels)
            altered["labels"] = [1 - int(v) for v in altered["labels"]]
            (folder / "evaluator_labels.json").write_text(json.dumps(altered) + "\n")
        changed_labels_runner = case("labels_changed", flip_labels)
        changed_labels = run(changed_labels_runner, 32)
        require([semantic_receipt(r) for r in changed_labels["receipts"]] == baseline_trace
                and semantic_pair(changed_labels["end"]) == semantic_pair(baseline["end"]),
                "evaluator labels changed actual native execution")
        findings["labels"] = dict(passed=True, original=labels,
            changed=json.loads((changed_labels_runner.public.parent / "evaluator_labels.json").read_text()),
            kernel_observed_accesses=0, exact_trajectory=True)

        future_index = next((i for i, r in enumerate(receipts)
                             if i > 0 and r["action"] == "READ"), None)
        require(future_index is not None, "fixture lacks a READ after an earlier acknowledged action")
        future = receipts[future_index]
        future_name = meta["packets"][future["event"]["job"]][future["event"]["tick"]]
        def corrupt(folder):
            (folder / future_name).write_bytes(b"undeclared audit payload; must not be opened before READ\n")
        corrupted_runner = case("future_packet_corrupted", corrupt)
        require(digest(corrupted_runner.public) == digest(baseline_runner.public),
                "future-packet intervention unexpectedly changed public identity")
        prefix = run(corrupted_runner, future_index)
        require([semantic_receipt(r) for r in prefix["receipts"]] == baseline_trace[:future_index],
                "unread payload influenced an earlier decision or task transition")
        require(future_name not in corrupted_runner.access_reports[-1]["observed_opens"],
                "future packet was opened before its selected READ")
        failed = run(corrupted_runner, 1, prefix["acknowledged_sha256"])
        challenged = failed["receipts"][0]
        require(all(challenged[k] == future[k] for k in DECISION_KEYS),
                "unread payload influenced its pre-read decision")
        require(challenged["event"]["error"] == "content packet digest mismatch"
                and challenged["event"]["observation"] is None
                and challenged["event"]["payload_sha256"] is None
                and challenged["event"]["payload_bytes"] == 0,
                "altered packet was not rejected at its selected READ")
        require(failed["end"]["content"] == prefix["end"]["content"]
                and failed["end"]["task"]["terminal"]
                and failed["end"]["task"]["counts"]["failed_read_attempts"]
                    == prefix["end"]["task"]["counts"]["failed_read_attempts"] + 1,
                "failed read committed an observation or failed to persist the failure")
        recovery = run(corrupted_runner, 0, failed["acknowledged_sha256"])
        require(semantic_pair(recovery["end"]) == semantic_pair(failed["end"]),
                "failed READ was not durable across a real process restart")
        findings["future_packet"] = dict(passed=True, target=future_name, read_sequence=future["sequence"],
            earlier_actions=future_index, identical_public_sha256=digest(corrupted_runner.public),
            changed_payload_sha256=digest(corrupted_runner.public.parent / future_name),
            expected_payload_sha256=meta["packet_sha256"][future["event"]["job"]][future["event"]["tick"]],
            earlier_kernel_opens=corrupted_runner.access_reports[0]["observed_opens"],
            challenged_kernel_opens=corrupted_runner.access_reports[1]["observed_opens"],
            error=challenged["event"]["error"], failed_read_recovery_exact=True,
            scope="Declared public hash held fixed: no speculative access, then rejection at actual READ; not a changed-known-metadata experiment.")

        opened = set(baseline_runner.access_reports[0]["observed_opens"])
        untouched_name = next(name for name in packet_names if name not in opened)
        untouched_runner = case("never_read_packet_corrupted", lambda folder:
            (folder / untouched_name).write_bytes(b"corrupt payload that the frozen policy never requests\n"))
        untouched = run(untouched_runner, 32)
        require([semantic_receipt(r) for r in untouched["receipts"]] == baseline_trace
                and semantic_pair(untouched["end"]) == semantic_pair(baseline["end"]),
                "never-read payload changed execution")
        findings["never_read_packet"] = dict(passed=True, target=untouched_name,
                                             kernel_opens=0, exact_trajectory=True)

        rejection_runner = case("identity_rejections")
        first = run(rejection_runner, 1)
        second = run(rejection_runner, 1, first["acknowledged_sha256"])
        require(not second["end"]["task"]["terminal"], "identity test needs an actionable nonterminal state")
        bound = inventory(rejection_runner.snapshot)
        stale = rejection_runner.run(1, first["acknowledged_sha256"], expect_rejection=True)
        require(json.loads(stale["stdout"])["error"] == "external acknowledged digest mismatch",
                "stale acknowledgement rejected for an unexpected reason")
        require(inventory(rejection_runner.snapshot) == bound, "stale acknowledgement modified persistent state")
        changed_policy = json.loads(args.policy.read_text())
        changed_policy["weights"]["c"][1] += 0.0001
        changed_path = rejection_runner.snapshot.parent / "altered_policy.json"
        write(changed_path, changed_policy)
        rejection_runner.policy = changed_path
        altered = rejection_runner.run(1, second["acknowledged_sha256"], expect_rejection=True)
        require(json.loads(altered["stdout"])["error"] == "checkpoint source/public/model/policy identity mismatch",
                "changed valid policy rejected for an unexpected reason")
        require(inventory(rejection_runner.snapshot) == bound, "changed policy modified persistent state")
        findings["identity"] = dict(passed=True, requested_steps=1, checkpoint_nonterminal=True,
            stale_ack_error=json.loads(stale["stdout"])["error"],
            policy_error=json.loads(altered["stdout"])["error"],
            packet_opens_after_rejections=0, snapshot_journal_witness_unchanged=True,
            bound_file_sha256=bound, altered_policy_sha256=digest(changed_path))
        report["success"] = True
    except Exception as exc:
        report["failure"] = dict(type=type(exc).__name__, reason=str(exc), traceback=traceback.format_exc())
    report["native_processes"] = sum(len(r.invocations) for r in runners)
    report["native_child_cpu_seconds"] = sum(process_costs(r)["cpu_seconds"] for r in runners)
    report["native_child_wall_seconds"] = sum(process_costs(r)["wall_seconds"] for r in runners)
    report["audit_parent_cpu_seconds"] = time.process_time() - started_cpu
    report["audit_wall_seconds"] = time.perf_counter() - started_wall
    report["energy_joules"] = None
    report["limitations"] = [
        "One pre-existing development fixture and one frozen analytic policy; no efficacy estimate or confidence interval.",
        "inotify observes regular-file OPEN/ACCESS during this isolated native execution; event coalescing is not a byte counter.",
        "Exact task/cell/content comparison excludes timing-dependent native checkpoint anchors, each individually verified against its acknowledged snapshot.",
        "Recovery scope is synchronous acknowledged action boundaries; incomplete-commit fault injection is outside this audit.",
        "Policy and stale-ack rejection may load public/model artifacts; the asserted zero access concerns task packet files and evaluator labels."]
    write(output / "SUMMARY.json", report)
    print(json.dumps(dict(success=report["success"], output=str(output),
                          processes=report["native_processes"], failure=report.get("failure", {}).get("reason"))))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("binary", "build-report", "freeze", "policy", "content", "public", "fixture-archive", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--freeze-sha256", required=True)
    raise SystemExit(audit(parser.parse_args()))
