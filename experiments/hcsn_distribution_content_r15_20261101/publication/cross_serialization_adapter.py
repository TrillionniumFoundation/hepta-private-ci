"""Post-failure JSON compatibility adapter for the frozen training/execution cross.

Only the cross module's JSON writer and worker module route are replaced in
memory. The registered source files, arrays, executors, comparisons, selection,
and statistical functions are not edited or replaced. This is an operational
repair after confirmation access, not a new prospective scientific protocol.

Use the original CLI through this module: launch, group, or index. The frozen
main function still owns parsing, configuration, execution, and exit status.
"""

import hashlib
import importlib
import json
from pathlib import Path

import numpy as np


MODULE = "experiments.hcsn_distribution_content_r15_20261101.publication.cross_serialization_adapter"
CROSS_MODULE = "experiments.hcsn_distribution_content_r15_20261101.train_execution_cross"
FROZEN_SOURCES = {
    "train_execution_cross.py": "59e21b69b977aee186f7e35d38fb3ff07dfce89274c22b2dcec103534ed6061a",
    "online_confirm.py": "c33fe176592042f408c305d477817c81823be43534c0a950bd26cbe70b91265e",
}


def numpy_scalar(value):
    """Convert supported NumPy scalars without casting arrays or other types."""
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        converted = value.item()
        if type(converted) in (float, int, bool):
            return converted
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write(path, value):
    """Preserve the frozen writer's behavior, adding only a scalar default."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False,
                  default=numpy_scalar)
        stream.write("\n")


def install():
    """Verify original bytes, then change only the writer and worker route."""
    root = Path(__file__).resolve().parents[1]
    for name, expected in FROZEN_SOURCES.items():
        observed = hashlib.sha256((root / name).read_bytes()).hexdigest()
        if observed != expected:
            raise ValueError("Frozen source identity changed: " + name)
    cross = importlib.import_module(CROSS_MODULE)
    cross.write = write
    cross.MODULE = MODULE
    return cross


def main():
    install().main()


if __name__ == "__main__":
    main()
