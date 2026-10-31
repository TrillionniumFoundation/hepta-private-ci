"""Explicit restored paths and immutable writes for the next native study."""

import hashlib
import json
import os
from pathlib import Path


REPO = Path(__file__).resolve().parents[4]
WORK = REPO.parent
ASSETS = WORK / 'ndu-next-assets'
SHARED = ASSETS / 'shared'
NATIVE = ASSETS / 'native'
AREA = Path(__file__).parent
MODEL = SHARED / 'abc2-runs/training-001/seed-17/output_ndu/model.pt'
OBSERVER = SHARED / 'abc2-runs/base-recovery-001/reward-observer.pt'
SENSOR = SHARED / 'abc3-runs/public-sensor-001/sensor.pt'
TEACHER = SHARED / 'abc3-runs/controllers-001/seed-17/output_ndu/controller.pt'
OLD_HEAD = NATIVE / 'outer/inputs/abc4-native-runs/model-003'
OLD_VERIFICATION = NATIVE / 'outer/inputs/abc4-native-runs/prospective-verification-001/verification.json'
OLD_PACKET = NATIVE / 'outer/inputs/abc4-native-runs/future-packet-001/packet.json'
ALLOCATION = AREA.parent / 'SOURCE_ALLOCATION.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    raw = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b'\n'
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def pins(extra=()):
    files = [MODEL, OBSERVER, SENSOR, TEACHER, ALLOCATION,
             OLD_HEAD / 'weights.json', OLD_HEAD / 'calibration.json', OLD_VERIFICATION]
    files += [p for p in AREA.iterdir() if p.suffix in {'.py', '.rs', '.toml'}]
    files += [AREA.parent / 'sources.py', *extra]
    return {str(p.resolve()): sha(p) for p in files}
