"""Single-arm student-only worker, started in an empty Linux network namespace."""

import codecs
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from student import load_bundle, predict


def main():
    start, cpu = time.perf_counter(), time.process_time()
    bundle = Path(sys.argv[1]).resolve()
    arm = sys.argv[2]
    inputs = json.load(sys.stdin)
    if any(set(r) != {"id", "prompt", "domain"} for r in inputs):
        raise ValueError("Only blind query records are allowed")

    def interfaces():
        return {
            ln.split(":")[0].strip(): [int(n) for n in ln.split(":")[1].split()]
            for ln in Path("/proc/net/dev").read_text().splitlines()[2:]
        }

    # Zipfile reads CP437 member names lazily. Resolve its stdlib codec before locking reads.
    codecs.lookup("cp437")
    before = interfaces()
    if set(before) != {"lo"} or any(before["lo"]):
        raise RuntimeError("Cold worker requires empty network namespace")

    # After imports restrict file reads to the owned checkpoint and network counters.
    def audit(event, args):
        if (
            event == "open"
            and not isinstance(args[0], int)
            and os.path.abspath(args[0]) not in (str(bundle), "/proc/net/dev")
        ):
            raise PermissionError(f"Unexpected read: {args[0]}")
        if event in ("socket.connect", "socket.bind", "subprocess.Popen"):
            raise PermissionError(event)

    sys.addaudithook(audit)
    sha = hashlib.sha256(bundle.read_bytes()).hexdigest()
    vocab, weights, meta = load_bundle(bundle)
    loaded = time.perf_counter()
    rows = [
        {"id": r["id"], **predict(arm, r["prompt"], r["domain"], vocab, weights, meta)}
        for r in inputs
    ]
    after = interfaces()
    if before != after:
        raise ValueError("Network counters changed")
    print(
        json.dumps(
            {
                "arm": arm,
                "pid": os.getpid(),
                "bundle_sha256": sha,
                "rows": rows,
                "loopback_bytes": after["lo"][0] + after["lo"][8],
                "interfaces": list(before),
                "load_and_guard_wall_s": loaded - start,
                "wall_seconds": time.perf_counter() - start,
                "cpu_seconds": time.process_time() - cpu,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
