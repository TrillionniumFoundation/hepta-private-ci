import hashlib
from pathlib import Path
import stat

path = Path('qualification/cell-e6-metrics-integration-20261119/mac-native5-complete/native5-and-cache-originals.tar.xz.part-002')
try:
    info = path.lstat()
except FileNotFoundError:
    print("Retained binary archive shard absent; check not applicable")
else:
    if not stat.S_ISREG(info.st_mode) or info.st_size != 150516:
        raise SystemExit("Retained binary archive shard type or length changed")
    with path.open("rb") as handle:
        raw = handle.read(150517)
    if len(raw) != 150516 or hashlib.sha256(raw).hexdigest() != '6ad85c1eb8adbe0f061f65b097df84b078851a90c495da5163596c540ae8b61c':
        raise SystemExit("Retained binary archive shard digest changed")
    print("Verified retained binary archive shard identity")
