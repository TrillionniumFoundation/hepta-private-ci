"""Single-worker entry; supervision persists every termination independently."""

import argparse
import json
import os
import subprocess
import sys

from .supervision import supervise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--data")
    parser.add_argument("--out")
    args = parser.parse_args()
    if args.smoke:
        if args.data or args.out:
            parser.error("no-data smoke accepts no data/output target")
        from .run import smoke
        print(json.dumps(smoke(), sort_keys=True))
        return 0
    if not args.data or not args.out:
        parser.error("run requires local --data and new --out")
    from .run import preflight
    preflight(args.data, args.out)
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
               MKL_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
    process = subprocess.Popen([sys.executable, "-m", "fashion_research.run",
                                "--worker", "--data", args.data, "--out", args.out],
                               env=env, start_new_session=True)
    return supervise(args.out, process)["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
