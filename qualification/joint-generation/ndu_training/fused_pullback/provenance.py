"""Future integration helper: CV-only file hashes belong to the two CV systems."""

from contextlib import nullcontext
import hashlib
from pathlib import Path


def cv_only(path):
    name = str(path)
    return (
        Path(name).name.startswith("base-reference-")
        or name.endswith("ndu_training/reinfer_d1/evidence/run-d1.txt")
        or name.endswith("runs/codex-cloud-ndu-TRAIN-reinference-d1/result.json")
    )


def verify_partitioned(identities, meter, root=Path("."), sha=None):
    """Frozen leaf hashes are already supplied; no eager read of every CV NPZ.

    The original bundle metadata is needed only at freeze time, not reread as
    an accidental common-runtime reference hash. Current data/base leaves are
    verified in their common phase and CV leaves in their two-recipient phase.
    """
    sha = sha or (lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest())
    partitions = {"common": {}, "CV": {}}
    for name, digest in identities.items():
        partitions["CV" if cv_only(name) else "common"][name] = digest
    for label, values in partitions.items():
        recipients = (
            ("A-CV", "N-CV")
            if label == "CV"
            else ("A-plain", "N-plain", "A-CV", "N-CV")
        )
        phase = (
            meter.phase(recipients, label + "_input_identity")
            if meter
            else nullcontext()
        )
        with phase:
            for name, expected in values.items():
                if sha(root / name) != expected:
                    raise ValueError(f"input identity mismatch: {name}")
    return {key: list(values) for key, values in partitions.items()}
