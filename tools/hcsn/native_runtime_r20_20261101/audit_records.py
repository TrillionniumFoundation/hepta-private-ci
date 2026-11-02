"""Standard-library raw state/receipt/process review; imports no project helpers."""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def checksum(data):
    h = 0xCBF29CE484222325
    for byte in data:
        h = ((h ^ byte) * 0x100000001B3) & ((1 << 64) - 1)
    return h


def lines(path):
    raw = path.read_bytes()
    prefix, check = raw.rsplit(b"CHECK\t", 1)
    assert check == (f"{checksum(prefix):016x}\n").encode()
    return [x.split("\t") for x in prefix.decode().splitlines()]


def check_owner(path, reference, commands, model, plan):
    records = lines(path)
    h = records[0]
    assert h[:4] == ["OWNER", reference["run"], model, plan]
    cursor, time_ns, charged = map(int, h[4:7])
    assert 0 <= cursor <= len(commands)
    assert time_ns == sum(x[1] for x in commands[:cursor])
    assert charged == sum(x[2] for x in commands[:cursor])
    assert h[7] == "-" or (int(h[7]) == cursor and commands[cursor][2] > 0)
    values = [struct.unpack(">d", bytes.fromhex(v))[0] for v in records[1][1:]]
    assert records[1][0] == "STATE" and len(values) == 40
    expected = reference["reference"][cursor - 1] if cursor else reference["prior"]
    error = max(abs(a - b) for a, b in zip(values, expected, strict=True))
    assert error <= 2e-11 and abs(sum(values) - 1) <= 4e-11
    effects = records[2:]
    wanted = [i for i, x in enumerate(commands[:cursor]) if x[2]]
    assert [int(x[4]) for x in effects] == wanted
    return effects, error


def audit(directory):
    result = json.loads((directory / "RESULT.json").read_text())
    checks, maximum = 0, 0.
    for entry in result["cases_detail"]:
        world = entry["world"]
        number = [("none", "none"), ("owner_initialized", "none"), ("owner_prepared:1", "none"),
                  ("owner_received:1", "none"), ("owner_computed:1", "none"), ("owner_committed:1", "none"),
                  ("owner_committed:2", "none"), ("none", "provider_effect_committed:1"),
                  ("owner_received:1", "provider_reply_published:1")].index((entry["owner_fault"], entry["provider_fault"]))
        case = directory / "cases" / f"{world:02}_{number:02}"
        reference = json.loads((case / "REFERENCE.json").read_text())
        public = lines(case / "PLAN")
        identified = json.loads((directory / "worlds" / str(world) / "MODEL_IDENTIFY.json").read_text())
        assert identified["exit_code"] == 0 and identified["model_sha256"] == hashlib.sha256((case / "MODEL").read_bytes()).hexdigest()
        assert identified["binary_sha256"] == result["binary_sha256"]
        model_hash = identified["observed_model_id"]
        plan_hash = f"{checksum((case / 'PLAN').read_bytes()):016x}"
        assert public[0] == ["PLAN", reference["run"], model_hash]
        commands = [(x[2], int(x[3]), int(x[5])) for x in public[1:]]
        assert [list(x) for x in commands] == reference["commands"]
        effects, error = check_owner(case / "owner.state", reference, commands, model_hash, plan_hash)
        maximum = max(maximum, error)
        ph = lines(case / "provider.state")
        assert ph[0][:4] == ["PROVIDER", reference["run"], model_hash, plan_hash]
        assert ph[0][4] == f"{checksum((case / 'CATALOG').read_bytes()):016x}"
        assert list(map(int, ph[0][5:])) == [len(effects), sum(x[2] for x in commands)]
        assert ph[1:] == effects
        for ordinal, row in enumerate(effects, 1):
            i = int(row[4])
            assert row[:4] == ["EFFECT", reference["run"], model_hash, plan_hash]
            assert row[5:7] == [f"paid{i}", commands[i][0]]
            assert list(map(int, row[7:])) == [reference["tokens"][str(i)], commands[i][2], ordinal]
            checks += 6
        for name in ("owner.state", "provider.state"):
            expected = (directory / "cases" / f"{world:02}_00" / name).read_bytes()
            actual = (case / name).read_bytes()
            assert actual == expected and hashlib.sha256(actual).hexdigest() == entry[name.split('.')[0] + "_sha256"]
            checks += 2
        if (case / "at_fault_owner.state").exists():
            _, error = check_owner(case / "at_fault_owner.state", reference, commands, model_hash, plan_hash)
            maximum = max(maximum, error)
            checks += 6
        for role in ("owner", "provider"):
            fault = entry[role + "_fault"]
            if fault != "none":
                assert (case / (role + ".marker")).read_text().split("\t")[0] == fault
                checks += 1
        checks += 12
    processes = json.loads((directory / "PROCESS_RECORDS.json").read_text())
    assert len(processes) == result["native_owner_provider_processes"]
    for row in processes:
        assert row["child_cpu_seconds"] >= 0 and row["wall_seconds"] >= 0
        assert row["exit_code"] == -9 if row["killed"] else row["exit_code"] in (0, 2)
        args = row["command"]
        if args[1] == "owner":
            assert len(args) == 8 and not any(Path(x).name in ("CATALOG", "REFERENCE.json") for x in args)
        checks += 4
    for binary in {row["command"][0] for row in processes}:
        expected = (json.loads((directory / "negative/changed_executable/ALTERNATE_IDENTIFY.json").read_text())["binary_sha256"]
                    if Path(binary).name == "alternate_artifact" else result["binary_sha256"])
        assert hashlib.sha256(Path(binary).read_bytes()).hexdigest() == expected
        checks += 1
    identities = list(directory.rglob("*IDENTIFY.json"))
    assert len(identities) == result["native_identification_processes"]
    assert len(identities) + len(processes) == result["native_processes"]
    for path in identities:
        row = json.loads(path.read_text())
        assert row["exit_code"] == 0 and row["command"][1] == "identify"
        assert len(row["observed_model_id"]) == 16 and row["child_cpu_seconds"] >= 0
        checks += 3
    negative = json.loads((directory / "negative/RESULT.json").read_text())
    assert negative["passed"] and negative["case_count"] == len(negative["cases"]) == 15
    pending = lines(directory / "negative/zero_evidence_paid_pending/owner.state")[0]
    provider = lines(directory / "negative/zero_evidence_paid_pending/provider.state")[0]
    assert pending[4:] == ["1", "110000000", "0", "1"] and provider[5:] == ["1", "25"]
    alternate = directory / "negative/changed_actual_token"
    reference = json.loads((alternate / "ALTERNATE_REFERENCE.json").read_text())
    h = lines(alternate / "owner.state")[0]
    _, error = check_owner(alternate / "owner.state", reference, reference["commands"], h[2], h[3])
    maximum = max(maximum, error)
    checks += 20
    return dict(passed=True, checks=checks, cases=len(result["cases_detail"]), processes=len(processes),
                negative_and_intervention_cases=15, maximum_reference_error=maximum,
                imports_project_helpers=False, reference_scope="Saved independently computed SciPy states; full numeric reference regeneration is the separate harness.",
                source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = audit(args.directory)
    with args.output.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps(value, sort_keys=True))
