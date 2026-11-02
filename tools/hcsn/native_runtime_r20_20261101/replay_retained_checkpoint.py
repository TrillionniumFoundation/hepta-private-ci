"""Resume retained paid-pending state with the exact restored research binary."""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import shutil
import subprocess
import time


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    binary = args.binary.resolve()
    assert sha(binary.read_bytes()) == "b30befcb76f00533029c60ce7a430a2b057bc152107625d7a5a4be3cd16f2798"
    args.output.mkdir(parents=True, exist_ok=False)
    for name in ("MODEL", "PLAN", "CATALOG"):
        shutil.copyfile(args.case / name, args.output / name)
    for role in ("owner", "provider"):
        shutil.copyfile(args.case / ("at_fault_" + role + ".state"), args.output / (role + ".state"))
    state = args.output.resolve()
    provider_cmd = [str(binary), "provider", str(state/"MODEL"), str(state/"PLAN"), str(state/"CATALOG"),
                    str(state/"provider.state"), str(state/"ENDPOINT"), "none", str(state/"provider.marker")]
    owner_cmd = [str(binary), "owner", str(state/"MODEL"), str(state/"PLAN"), str(state/"owner.state"),
                 str(state/"ENDPOINT"), "none", str(state/"owner.marker")]
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    with (state/"provider.stdout").open("wb") as out, (state/"provider.stderr").open("wb") as err:
        provider = subprocess.Popen(provider_cmd, stdout=out, stderr=err)
        try:
            while not (state/"ENDPOINT").exists():
                if provider.poll() is not None or time.monotonic()-started > 5:
                    raise RuntimeError("provider did not start")
                time.sleep(.003)
            owner = subprocess.run(owner_cmd, capture_output=True, timeout=10)
            (state/"owner.stdout").write_bytes(owner.stdout)
            (state/"owner.stderr").write_bytes(owner.stderr)
            assert owner.returncode == 0
        finally:
            if provider.poll() is None:
                provider.kill()
            provider.wait()
    hashes = {}
    for name in ("owner.state", "provider.state"):
        actual, expected = (state/name).read_bytes(), (args.expected/name).read_bytes()
        assert actual == expected
        hashes[name] = sha(actual)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = dict(passed=True, binary_sha256=sha(binary.read_bytes()), checkpoint=str(args.case),
                  expected_uninterrupted=str(args.expected), provider_command=provider_cmd, owner_command=owner_cmd,
                  state_sha256=hashes, native_child_cpu_seconds=(after.ru_utime+after.ru_stime)-(before.ru_utime+before.ru_stime),
                  scope="Delivery engineering replay of an existing formal world, not fresh confirmation or production qualification.")
    (state/"REPLAY.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
