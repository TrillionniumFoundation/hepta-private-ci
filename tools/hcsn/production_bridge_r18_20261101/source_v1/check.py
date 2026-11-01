"""Process-death and binding checks over actual production journal/witness APIs."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
RUN = hashlib.sha256(b"hcsn-r18-bridge-owner").hexdigest()
OBJECTIVE = hashlib.sha256(b"hcsn-r18-bridge-objective").hexdigest()
ZERO = "0" * 64


def invoke(binary, root, receipt, sequence, before, *, run=RUN, objective=OBJECTIVE,
           generation=1, phase="ack"):
    args = [str(binary), str(root), run, objective, str(generation), str(sequence),
            before, str(receipt), phase]
    started = time.perf_counter()
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if phase == "after_append":
        import selectors
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        if not selector.select(10):
            process.kill()
            process.communicate()
            raise RuntimeError("Durable boundary handshake timed out")
        boundary = process.stdout.readline()
        if not boundary or json.loads(boundary)["phase"] != "after_append":
            _, error = process.communicate(timeout=10)
            raise RuntimeError(f"Worker did not reach append boundary: {error!r}")
        process.kill()
        output, error = process.communicate(timeout=10)
        output = boundary + output
    else:
        output, error = process.communicate(timeout=10)
    return dict(exit_code=process.returncode, stdout=output.decode(), stderr=error.decode(),
                wall_seconds=time.perf_counter() - started)


def state_hashes(root):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}


def run(binary, output, external_receipts=None):
    started = time.perf_counter()
    records, rejected = [], []
    with tempfile.TemporaryDirectory(prefix="hcsn-production-bridge-r18-") as temporary:
        base = Path(temporary)
        receipts = base / "receipts"
        receipts.mkdir()
        for index in range(1, 7):
            (receipts / str(index)).write_text(
                f"EFFECT\t{RUN}\top-{index}\tREAD\t{index % 5}\t25000\t{index}\n")
        root = base / "continuous"
        before, anchors = ZERO, []
        for sequence in range(1, 7):
            result = invoke(binary, root, receipts / str(sequence), sequence, before)
            assert result["exit_code"] == 0, result
            value = json.loads(result["stdout"])
            assert value["requires_calibration"] and value["authority"] == "DENY_ALL"
            assert value["receipt_sha256"] == hashlib.sha256((receipts / str(sequence)).read_bytes()).hexdigest()
            anchors.append(dict(before=before, after=value["checkpoint"]))
            before = value["checkpoint"]
            records.append(result)
        continuous_hashes = state_hashes(root)
        for sequence in range(1, 7):
            result = invoke(binary, root, receipts / str(sequence), sequence, anchors[sequence - 1]["before"])
            assert result["exit_code"] == 0, result
            assert json.loads(result["stdout"])["witness_sequence"] == 6
            assert state_hashes(root) == continuous_hashes
            records.append(result)
        for death_sequence in (1, 2, 4, 6):
            replay = base / f"death-{death_sequence}"
            before = ZERO
            for sequence in range(1, 7):
                if sequence == death_sequence:
                    result = invoke(binary, replay, receipts / str(sequence), sequence, before,
                                    phase="after_append")
                    assert result["exit_code"] == -signal.SIGKILL, result
                    records.append(result)
                result = invoke(binary, replay, receipts / str(sequence), sequence, before)
                assert result["exit_code"] == 0, result
                before = json.loads(result["stdout"])["checkpoint"]
                records.append(result)
            assert state_hashes(replay) == continuous_hashes

        def expect_rejected(name, candidate_root, candidate_receipt, sequence, predecessor, **kwargs):
            before_hashes = state_hashes(candidate_root)
            result = invoke(binary, candidate_root, candidate_receipt, sequence, predecessor, **kwargs)
            assert result["exit_code"] == 2, (name, result)
            assert state_hashes(candidate_root) == before_hashes, name
            rejected.append(dict(name=name, **result))

        changed = receipts / "changed"
        changed.write_text((receipts / "1").read_text().replace("op-1", "different-operation"))
        expect_rejected("conflicting_replay", root, changed, 1, ZERO)
        expect_rejected("wrong_predecessor", root, receipts / "2", 2, ZERO)
        expect_rejected("wrong_scope", root, receipts / "1", 1, ZERO,
                        run=hashlib.sha256(b"other").hexdigest())
        expect_rejected("wrong_objective", root, receipts / "1", 1, ZERO,
                        objective=hashlib.sha256(b"other-objective").hexdigest())
        expect_rejected("wrong_generation", root, receipts / "1", 1, ZERO, generation=2)
        for kind in ("journal", "witness"):
            damaged = base / f"damaged-{kind}"
            shutil.copytree(root, damaged)
            path = damaged / kind
            original = path.read_bytes()
            path.write_bytes(original[:-1])
            expect_rejected(f"truncated_{kind}", damaged, receipts / "6", 6, anchors[5]["before"])
        rollback = base / "rollback"
        shutil.copytree(root, rollback)
        # Substitute a complete valid earlier journal, keeping the independent frontier.
        first = base / "first"
        one = invoke(binary, first, receipts / "1", 1, ZERO)
        assert one["exit_code"] == 0
        (rollback / "journal").write_bytes((first / "journal").read_bytes())
        expect_rejected("acknowledged_suffix_rollback", rollback, receipts / "6", 6, anchors[5]["before"])
        oversized = receipts / "oversized"
        oversized.write_bytes(b"x" * 1048576)
        expect_rejected("oversized_provider_evidence", root, oversized, 1, ZERO)
        external = []
        if external_receipts:
            manifest = json.loads(Path(external_receipts).read_text())
            if isinstance(manifest, dict) and "lines" in manifest:
                lines = [text if text.endswith("\n") else text + "\n" for text in manifest["lines"]]
                manifest = [dict(run_sha=lines[0].split("\t")[1], receipt_lines=lines)]
            for case_index, item in enumerate(manifest):
                case_root, before = base / f"external-{case_index}", ZERO
                for sequence, text in enumerate(item["receipt_lines"], 1):
                    receipt = receipts / f"external-{case_index}-{sequence}"
                    receipt.write_text(text)
                    result = invoke(binary, case_root, receipt, sequence, before, run=item["run_sha"])
                    assert result["exit_code"] == 0, result
                    row = json.loads(result["stdout"])
                    assert row["receipt_sha256"] == hashlib.sha256(receipt.read_bytes()).hexdigest()
                    before = row["checkpoint"]
                    external.append(result)
    result = dict(schema="hcsn-r18-production-api-bridge-check-v1", all_passed=True,
                  process_records=records, negative_rejections=rejected,
                  external_provider_records=external, wall_seconds=time.perf_counter() - started,
                  production_activation=False, actual_journal_api=True,
                  external_provider_receipts_verified=len(external),
                  limits=["Receipt digest is not provider authentication", "No full analytic kernel Rust port",
                          "No calibrated model admission", "Process death is not power loss",
                          "Local files are assumed privately enrolled and separately trusted"])
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(all_passed=True, cases=len(records), negative_rejections=len(rejected),
                          external_receipts=len(external))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--external-receipts", type=Path)
    args = parser.parse_args()
    run(args.binary.resolve(), args.output, args.external_receipts)
