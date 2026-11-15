#!/usr/bin/env python3
"""Audit entry before importing the admission/compiler implementation."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time


def main():
    started = False
    result = {"returncode": 74}
    try:
        directory = Path(os.environ["CODEX_HIA_POLICY_FIX_CONTEXT"]).parent
        stem = "bridge-" + str(os.getpid()) + "-" + str(time.time_ns())
        begin, end = directory / (stem + ".begin.json"), directory / (stem + ".end.json")
        with begin.open("x") as stream:
            json.dump({"schema": "codex.hia.fix-bridge-start.v1", "kind": 'workspace',
                       "arguments": sys.argv[1:]}, stream, indent=2)
            stream.write("\n")
        started = True
        from unified_policy_fix import bridge
        code, record = bridge('workspace', sys.argv[1:])
        result.update(returncode=code, result=record)
    except BaseException as error:
        result["exception"] = str(error)
        print("error: HIA fix bridge rejected: " + str(error), file=sys.stderr)
    finally:
        if started:
            try:
                result["start"] = {"path": str(begin.resolve()), "bytes": begin.stat().st_size,
                                   "sha256": hashlib.sha256(begin.read_bytes()).hexdigest()}
                with end.open("x") as stream:
                    json.dump(result, stream, indent=2)
                    stream.write("\n")
            except BaseException as error:
                result["returncode"] = 74
                print("error: HIA fix audit completion failed: " + str(error), file=sys.stderr)
    return result["returncode"]


if __name__ == "__main__":
    raise SystemExit(main())
