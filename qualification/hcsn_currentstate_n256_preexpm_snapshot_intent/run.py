"""Single hosted entry for the frozen zero-exponential diagnostic."""

import json
import os
import shutil
from pathlib import Path

from qualification.hcsn_currentstate_n256_preexpm_snapshot_intent.snapshot import (
    UNIQUE_KEY,
    execute,
)


def main():
    output = Path("hcsn-n256-preexpm-snapshot-output")
    if output.exists():
        raise RuntimeError("output already exists")
    if os.environ.get("HCSN_UNIQUE_EXECUTION_KEY") != UNIQUE_KEY:
        raise RuntimeError("unique execution key")
    result = execute(output)
    if not result["scope"]["current_source_preexpm_inputs_byte_equal"]:
        raise RuntimeError("terminal pre-expm input mismatch")
    shutil.make_archive(str(output), "zip", root_dir=output)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
