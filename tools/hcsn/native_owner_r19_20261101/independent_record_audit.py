"""Independent stdlib record audit; imports no campaign or project helper."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def checksum(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return value


def sealed(path):
    data = path.read_bytes()
    content, tail = data.rsplit(b"CHECK\t", 1)
    assert tail == f"{checksum(content):016x}\n".encode(), str(path)
    return [line.decode().split("\t") for line in content.splitlines()]


def main():
    root = HERE / "results/run02"
    summary = json.loads((root / "RESULT.json").read_text())
    rows = []
    checks = 0
    six = root / "six_original_cases"
    directories = [six / row["name"] for row in summary["cases"][:6]] + [root / "allocated_before_publish"]
    for case, directory in zip(summary["cases"], directories, strict=True):
        job = sealed(directory / "job")
        run, state = job[0][1:]
        expected = {}
        elapsed = fees = 0
        for i, frame in enumerate(job[1:]):
            assert frame[0] == "FRAME" and int(frame[1]) == i
            assert int(frame[8], 16) == checksum(state.encode())
            state = frame[9]
            elapsed += int(frame[5]); fees += int(frame[6])
            if frame[2].startswith("received:"):
                expected[frame[3]] = (frame[2].split(":")[1], int(frame[4]), int(frame[7]))
            checks += 3
        provider = sealed(directory / "provider.state")
        header = provider[0]
        assert header[0] == "PROVIDER" and header[1] == run
        assert int(header[2], 16) == checksum((directory / "job").read_bytes())
        effects = [line for line in provider[1:] if line[0] == "EFFECT"]
        assert len(effects) == int(header[4]) == case["count"]
        assert sum(int(line[5]) for line in effects) == int(header[5]) == case["charged_micros"]
        assert sorted(int(line[6]) for line in effects) == list(range(1, len(effects) + 1))
        assert len({line[2] for line in effects}) == len(effects)
        for effect in effects:
            assert effect[1] == run
            assert (effect[3], int(effect[4]), int(effect[5])) == expected[effect[2]]
            checks += 2
        if effects:
            assert set(expected) == {line[2] for line in effects}
            owner = sealed(directory / "owner.state")
            h = owner[0]
            assert h[0] == "OWNER" and h[1] == run and h[2] == header[2]
            assert int(h[3]) == int(header[3]) == case["generation"]
            assert list(map(int, h[4:])) == [len(job) - 1, elapsed, fees]
            assert owner[1] == ["STATE", state]
            assert sorted(owner[2:]) == sorted(effects)
            checks += 6
        replies = [line for line in provider[1:] if line[0] == "REPLY"]
        assert len({line[1] for line in replies}) == len(replies)
        for reply in replies:
            response = bytes.fromhex(reply[3]).decode()
            assert response.startswith(("LEASE\t", "OK", "EFFECT\t", "ERR\t"))
            checks += 1
        if case["name"] == "allocator_sigkill_before_publication":
            allocated = sealed(directory / "mailbox/client-sequence")
            assert allocated == [["9"]]
            assert sorted(reply[1] for reply in replies) == [f"0-{i:020}" for i in range(2, 10)]
            assert (directory / "allocator.marker").exists()
            checks += 3
        if case["name"] == "baseline_alias":
            assert "stale owner generation" in (directory / "owner.stderr").read_text()
            assert int(header[3]) == 2 and not effects
        if case["name"] == "candidate_alias":
            assert int(header[3]) == 3 and len(effects) == 2
        if case["name"] == "tcp_relay_after_effect":
            assert (directory / "relay.marker").exists()
        rows.append(dict(name=case["name"], effects=len(effects), fee=int(header[5]), generation=int(header[3]), replies=len(replies)))
        checks += 7
    records = json.loads((six / "PROCESS_RECORDS.json").read_text()) + json.loads((root / "SUPPLEMENT_PROCESS_RECORDS.json").read_text())
    assert len(records) == summary["processes"] == 19
    assert abs(sum(row["cpu_seconds"] for row in records) - summary["child_cpu_seconds"]) < 1e-12
    binaries = {}
    for row in records:
        binary = Path(row["command"][0])
        sha = hashlib.sha256(binary.read_bytes()).hexdigest()
        assert sha in (summary["binary_sha256"], summary["baseline_sha256"])
        binaries[str(binary)] = sha
        assert row["exit_code"] in (-9, 0, 2)
        checks += 2
    build = json.loads((HERE / "BUILD_V2.json").read_text())
    assert build["binary_sha256"] == summary["binary_sha256"]
    freeze = json.loads((HERE / "SOURCE_FREEZE_V2.json").read_text())
    source_bindings = []
    root_path = HERE.parents[2]
    for item in freeze["files"]:
        content = (root_path / item["path"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == item["sha256"]
        blob = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        assert blob == item["git_blob"]
        source_bindings.append(dict(path=item["path"], sha256=item["sha256"], git_blob=blob))
        checks += 2
    result = dict(passed=True, checks=checks, cases=rows, process_records=len(records), binaries=binaries,
                  remote_source_freeze_commit="1bcc1b2c9a1d3deaf7cfe9cdc928cfe8c28ee3fc",
                  source_bindings=source_bindings, source_freeze_sha256=hashlib.sha256((HERE / "SOURCE_FREEZE_V2.json").read_bytes()).hexdigest(),
                  declared_child_cpu_seconds=summary["child_cpu_seconds"],
                  summary_sha256=hashlib.sha256((root / "RESULT.json").read_bytes()).hexdigest(),
                  limits="Trusted local process/TCP loopback records only. No authentication, power-loss, partial-restore, native numerical callback or production adoption conclusion.")
    (HERE / "INDEPENDENT_RECORD_AUDIT_V2.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
