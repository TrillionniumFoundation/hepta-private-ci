"""Protocol, durable-effect, private-scoring and real process-death checks."""

import hashlib
import json
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time

from ..support_retention_r16_20261101.execution import execute
from ..addressed_decision_r15_20261101.law import Law
from .provider import MAX_BODY, Provider, Rejected, canonical, seal, unseal


def snapshot(provider):
    return tuple(provider.db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                 for table in ("cursor", "replies", "effects", "scores"))


def worker(config, state, mailbox, stop, marker):
    process = subprocess.Popen([sys.executable, "-m", "tools.hcsn.native_numeric_r19_20261102.provider",
                                str(config), str(state), str(mailbox), stop, str(marker)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    select = selectors.DefaultSelector()
    select.register(process.stdout, selectors.EVENT_READ)
    if not select.select(10) or process.stdout.readline() != b"READY\n":
        process.kill()
        _, error = process.communicate()
        raise RuntimeError(f"Provider startup failed: {error!r}")
    select.close()
    return process


def wait_path(path):
    deadline = time.monotonic() + 10
    while not path.exists():
        if time.monotonic() > deadline:
            raise TimeoutError(path)
        time.sleep(.002)


def checks(output):
    started, count, process_rows = time.process_time(), 0, []
    with tempfile.TemporaryDirectory(prefix="hcsn-native-r19-provider-") as directory:
        root = Path(directory)
        config = dict(run=hashlib.sha256(b"r19-provider-check").hexdigest(),
                      model=Law().export(), seed=190610001, domain="iid", query_count=6)
        cfg = root / "config.json"
        cfg.write_text(canonical(config))
        run = config["run"]
        provider = Provider(root / "direct.sqlite", config)
        assert provider.apply("lease-one", f"LEASE\t{run}") == "LEASE\t1"
        provider.db.close()
        provider = Provider(root / "direct.sqlite", config)
        assert provider.apply("lease-one", f"LEASE\t{run}") == "LEASE\t1"
        count += 2
        before = snapshot(provider)
        try:
            provider.apply("lease-two", f"LEASE\t{run}", inject_storage_failure=True)
        except OSError:
            assert snapshot(provider) == before
            count += 1
        else:
            raise AssertionError("Injected storage failure returned success")
        assert provider.apply("lease-two", f"LEASE\t{run}") == "LEASE\t2"
        count += 1

        def rejected(name, request_id, text):
            nonlocal count
            before = snapshot(provider)
            try:
                provider.apply(request_id, text)
            except (ValueError, OverflowError):
                assert snapshot(provider) == before, name
                count += 1
            else:
                raise AssertionError(name)

        rejected("stale generation", "stale", f"CHECK\t{run}\t1")
        rejected("wrong run", "wrong", "CHECK\t" + "0" * 64 + "\t2")
        rejected("oversized body", "large", "x" * (MAX_BODY + 1))
        oracle = execute(Law(), provider.episode, policy="fixed", pattern="wait_read")
        for query, expected in enumerate(oracle["queries"]):
            opened = provider.apply(f"open-{query}", f"OPEN\t{run}\t2\t{query}").split("\t")
            assert opened[:3] == ["OPEN", str(query), str(expected["key"])]
            assert len(opened) == 9 and "target" not in "\t".join(opened).lower()
            assert float(opened[5]) == expected["deadline"]
            count += 3
            completed = 0
            for index, action in enumerate(expected["actions"]):
                opid = f"{run}:{query}:{index}"
                text = f"ACT\t{run}\t2\t{query}\t{completed}\t{action['action']}\t{opid}"
                reply = provider.apply(f"act-{query}-{index}", text)
                fields = reply.split("\t")
                assert int(fields[2]) == action["step"]
                assert int(fields[3]) == (-1 if action["token"] is None else action["token"])
                assert float(fields[4]) == action["time"]
                before = snapshot(provider)
                old_effects = provider._cursor()["effects"]
                assert provider.apply(f"act-{query}-{index}", text) == reply
                assert snapshot(provider) == before
                assert provider.apply(f"retry-{query}-{index}", text) == reply
                assert provider._cursor()["effects"] == old_effects
                count += 7
                completed = action["step"]
            response = provider.apply(f"submit-{query}",
                f"SUBMIT\t{run}\t2\t{query}\t{completed}\t{expected['answer']}\t{run}:{query}:submit")
            assert response == f"ACK\t{query}\t{run}:{query}:submit"
            score = json.loads(provider.db.execute("SELECT body FROM scores WHERE query=?", (query,)).fetchone()[0])
            assert {k: score[k] for k in ("target", "reward", "fee", "utility")} == {
                k: expected[k] for k in ("target", "reward", "fee", "utility")}
            count += 2
        first_text = f"ACT\t{run}\t2\t0\t0\tWAIT\t{run}:0:0"
        provider.apply("lease-three", f"LEASE\t{run}")
        rejected("cached old-generation act", "act-0-0", first_text)
        rejected("transport id content conflict", "lease-one", f"CHECK\t{run}\t3")
        old_count = provider._cursor()["effects"]
        retry = provider.apply("retry-new-generation", first_text.replace("\t2\t0\t0", "\t3\t0\t0", 1))
        assert retry.startswith("ACT\t0\t1\t-1\t") and provider._cursor()["effects"] == old_count
        rejected("semantic op conflict", "conflict", f"ACT\t{run}\t3\t0\t0\tREAD\t{run}:0:0")
        rejected("deadline overrun", "late", f"ACT\t{run}\t3\t5\t3\tREFRESH\tlate-op")
        count += 1
        for name, mode in (("lost-lease", "lease_committed"), ("storage-failure", "storage_failure")):
            case = root / name
            case.mkdir()
            mailbox = case / "mail"
            mailbox.mkdir()
            state, marker = case / "state.sqlite", case / "marker"
            process = worker(cfg, state, mailbox, mode, marker)
            request = seal(f"REQ\tlease-request\t{f'LEASE{chr(9)}{run}'.encode().hex()}\n")
            (mailbox / "lease-request.req").write_text(request)
            if mode == "lease_committed":
                wait_path(marker)
                assert not (mailbox / "lease-request.resp").exists()
                process.kill()
                _, error = process.communicate(timeout=10)
                assert process.returncode == -signal.SIGKILL
            else:
                _, error = process.communicate(timeout=10)
                assert process.returncode != 0 and not (mailbox / "lease-request.resp").exists()
            process_rows.append(dict(case=name, exit_code=process.returncode, stderr=error.decode()))
            restarted = worker(cfg, state, mailbox, "none", marker)
            wait_path(mailbox / "lease-request.resp")
            envelope = unseal((mailbox / "lease-request.resp").read_bytes()).rstrip("\n").split("\t")
            assert bytes.fromhex(envelope[2]).decode() == "LEASE\t1"
            restored = Provider(state, config)
            assert restored._cursor()["generation"] == 1
            restored.db.close()
            (mailbox / "STOP").write_text("")
            _, error = restarted.communicate(timeout=10)
            assert restarted.returncode == 0, error
            process_rows.append(dict(case=name + "-restart", exit_code=restarted.returncode))
            count += 4
        encoded = seal("REQ\tid\t4f4b\n").encode()
        assert unseal(encoded) == "REQ\tid\t4f4b\n"
        try:
            unseal(encoded.replace(b"4f4b", b"4f4c"))
        except Rejected:
            count += 1
        else:
            raise AssertionError("wire corruption accepted")
    result = dict(schema="hcsn-r19-provider-check-v1", all_passed=True, checks=count,
                  process_records=process_rows, cpu_internal_seconds=time.process_time() - started,
                  scope="Protocol/cursor/effect/scorer consistency plus real provider death and fail-stop; no numeric Rust claim")
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(all_passed=True, checks=count)))


if __name__ == "__main__":
    checks(Path(sys.argv[1]))
