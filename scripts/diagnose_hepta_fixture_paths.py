#!/usr/bin/env python3
"""Record real temporary-root spelling and redirects without changing any path.

This is an observation helper, not a Rust test or permission-policy change. Run
it in the same runner context as the affected test. An observation on Linux
does not establish the path spelling or errno of an earlier macOS failure.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import sys
import tempfile


def observe(source, requested):
    path = Path(requested)
    if not path.is_absolute():
        path = Path.cwd() / path
    result = {"source": source, "requested": requested, "absolute_spelling": str(path)}
    try:
        canonical = path.resolve(strict=True)
        result["resolution"] = {
            "canonical": str(canonical),
            "same_spelling": str(path) == str(canonical),
        }
    except OSError as error:
        result["resolution"] = {
            "error_type": type(error).__name__,
            "errno": error.errno,
            "message": str(error),
        }
    except RuntimeError as error:
        result["resolution"] = {
            "error_type": type(error).__name__,
            "message": str(error),
        }

    ancestors = []
    for ancestor in reversed([path, *path.parents]):
        item = {"path": str(ancestor)}
        try:
            info = ancestor.lstat()
            item.update(
                {
                    "mode": oct(stat.S_IMODE(info.st_mode)),
                    "is_symlink": stat.S_ISLNK(info.st_mode),
                }
            )
            if stat.S_ISLNK(info.st_mode):
                item["symlink_target"] = os.readlink(ancestor)
        except OSError as error:
            item.update(
                {
                    "error_type": type(error).__name__,
                    "errno": error.errno,
                    "message": str(error),
                }
            )
        ancestors.append(item)
    result["ancestors"] = ancestors
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New JSON file; existing files are not overwritten",
    )
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="Additional exact path to inspect; repeatable",
    )
    args = parser.parse_args()
    selected = [("cwd", os.getcwd()), ("tempfile.gettempdir", tempfile.gettempdir())]
    for name in ("TMPDIR", "TMP", "TEMP", "TEST_TMPDIR"):
        value = os.environ.get(name)
        if value:
            selected.append((f"environment:{name}", value))
    selected.extend(("explicit", value) for value in args.path)
    receipt = {
        "schema": "hepta.fixture-path-observation.v1",
        "utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "command": sys.argv,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "Read-only requested/resolved path, ancestor symlink and actual errno observations; no Rust tests executed.",
        "observations": [observe(source, value) for source, value in selected],
    }
    with args.output.open("x") as output:
        json.dump(receipt, output, indent=2)
        output.write("\n")
    print(json.dumps({"output": str(args.output), "observations": len(selected)}))


if __name__ == "__main__":
    main()
