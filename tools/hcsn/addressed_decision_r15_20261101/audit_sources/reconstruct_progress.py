from pathlib import Path
import gzip, hashlib, json
base = Path("tools/hcsn/addressed_decision_r15_20261101/run_02")
output = base / "reconstructed_progress"
output.mkdir(exist_ok=True)
for source in sorted((base / "confirmation").glob("*.json.gz")):
    record = json.loads(gzip.decompress(source.read_bytes()))
    target = output / f"{record['seed']}_{record['domain']}.jsonl"
    digest = hashlib.sha256()
    with target.open("xb") as stream:
        for index, world in enumerate(record["world_tapes"]):
            row = dict(index=index, world=world, arms={
                name: arm["episodes"][index]
                for name, arm in record["arms"].items()})
            line = (json.dumps(row, sort_keys=True, separators=(",", ":"),
                               allow_nan=False) + "\n").encode("utf-8")
            stream.write(line)
            digest.update(line)
    assert digest.hexdigest() == record["progress_journal_sha256"]
    print(target.name, digest.hexdigest())
