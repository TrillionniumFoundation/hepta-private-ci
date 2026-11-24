import hashlib
import io
import json
import re
import zipfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    receipt = json.loads((root / "receipt.json").read_text())
    contents = {}
    for kind in ("keyring", "matrix"):
        record = receipt[kind]
        data = (root / f"{kind}-artifact.zip").read_bytes()
        assert hashlib.sha256(data).hexdigest() == record["artifact_sha256"]
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            assert set(archive.namelist()) == set(record["members"])
            contents[kind] = {}
            for name, expected in record["members"].items():
                member = archive.read(name)
                assert len(member) == expected["bytes"], name
                assert hashlib.sha256(member).hexdigest() == expected["sha256"], name
                contents[kind][name] = member

    keyring = contents["keyring"]
    identity = json.loads(keyring["identity.json"])
    result = json.loads(keyring["result.json"])
    clients = json.loads(keyring["client-receipt.json"])
    server = json.loads(keyring["server-receipt.json"])
    assert identity["source_sha"] == result["source_sha"] == receipt["source_sha"]
    assert result["passed"] and result["session_exit_code"] == 0
    assert len(clients) == 11 and all(item["exit_code"] == 0 for item in clients)
    sessions = [e for e in server["events"] if e["operation"] == "open_session"]
    assert len(sessions) == 49
    assert all(e["algorithm"] == "dh-ietf1024-sha256-aes128-cbc-pkcs7" for e in sessions)
    assert server["synthetic_only"]
    log = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", keyring["secrets-tests.log"].decode())
    assert "9 tests run: 9 passed, 0 skipped" in log

    matrix = contents["matrix"]
    assert matrix["current-head.txt"].decode().strip() == receipt["source_sha"]
    assert matrix["baseline-head.txt"].decode().strip() == receipt["matrix"]["qualification"]["baseline_sha"]
    for name, marker in (
        ("baseline-create.log", "create_fixture_verified=true"),
        ("baseline-reopen.log", "verify_fixture_verified=true"),
        ("upgrade.log", "verify_fixture_verified=true"),
        ("upgraded-reopen.log", "verify_fixture_verified=true"),
        ("wrong-passphrase.log", "wrong_passphrase_rejected=true"),
    ):
        assert marker in matrix[name].decode(), name
    consumer = matrix["consumer-tests.log"].decode()
    assert "E0615" in consumer and "bundled_latest_thread_event" in consumer
    assert "tests run:" not in consumer
    print("PASS: exact archives, source bindings and scoped outcomes verified")


if __name__ == "__main__":
    main()
