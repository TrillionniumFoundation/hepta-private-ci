"""Read-only independent OpenSSL HMAC and retained native-state byte audit."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    repo = Path(__file__).resolve().parents[3]
    result = json.loads((root/"RESULTS.json").read_text())
    assert result["passed"] and not result["development"]
    assert result["synthetic_contexts"] == 32 and result["negative_controls"] == 80
    assert all(row["rejected"] for row in result["controls"])
    key = hashlib.sha256(b"PUBLIC TEST FIXTURE ONLY HCSN AUTH V1").digest()
    count = 0
    def check(data, domain):
        nonlocal count
        parsed = json.loads(data)
        raw = json.dumps(parsed["body"], sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
        # This public fixture key is never a live deployment credential.
        command = ["openssl", "dgst", "-sha256", "-mac", "HMAC", "-macopt", "hexkey:"+key.hex()]
        proc = subprocess.run(command, input=domain.encode()+b"\0"+raw, capture_output=True, check=True)
        assert proc.stdout.decode().strip().split()[-1] == parsed["tag"]
        count += 1
        return parsed["body"]
    for row in result["pairs"]:
        file = root/row["checkpoint"]
        data = file.read_bytes()
        assert hashlib.sha256(data).hexdigest() == row["checkpoint_sha256"] == row["current"][1]
        body = check(data, "hcsn-native-checkpoint-pair-v1")
        assert body["context"] == row["context"] and body["seq"] == 1
    records = sorted((root/"witness-log").glob("*.record"))
    assert len(records) == 68
    previous = "0"*64
    tips = {}
    for index, record in enumerate(records):
        data = record.with_suffix(".before-tamper").read_bytes() if index == 0 else record.read_bytes()
        body = check(data, "hcsn-witness-log-v1")
        assert body["previous"] == previous
        assert body["seq"] == tips.get(body["context"], (-1, None))[0]+1
        tips[body["context"]] = body["seq"], body["digest"]
        previous = hashlib.sha256(data).hexdigest()
    assert len(result["native_replays"]) == 4
    for replay in result["native_replays"]:
        number = int(Path(replay["case"]).name.split("_")[0])
        for role in ("owner", "provider"):
            actual = (root/f"native-execution-{number}"/(role+".state")).read_bytes()
            expected = (repo/"tools/hcsn/native_runtime_r20_20261101/confirmation01/cases"/f"{number:02}_00"/(role+".state")).read_bytes()
            assert actual == expected
            assert hashlib.sha256(actual).hexdigest() == replay["final_states"][role]
            count += 1
        assert replay["paid_pending_provenance"] and replay["owner_exit"] == 0
    assert [x["exit_code"] for x in result["witness_processes"]] == [-9, -9, 1]
    receipt = {"passed": True, "openssl_hmac_records": 100, "native_final_state_byte_comparisons": 8,
               "checks": count, "witness_records": 68, "independent_numeric_imports": [],
               "scope": "Read-only OpenSSL implementation and original-R20 final bytes; not an independent security certification."}
    (root.parent/"INDEPENDENT_OPENSSL_AUDIT.json").write_text(json.dumps(receipt, indent=2)+"\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
