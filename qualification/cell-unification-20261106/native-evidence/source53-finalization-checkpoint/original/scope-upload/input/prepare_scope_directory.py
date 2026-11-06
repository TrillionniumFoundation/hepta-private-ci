"""Create only the already authorized evidence input directory, never source."""
import json
import os
import stat
from pathlib import Path

TARGET = Path('/home/alex/work/hepta-cell-unified-20261106-a/evidence/native-source53-finalizer-input')
NAMES = ['EXPECTED-SELECTION.json', 'PACKAGE-ARGS.json', 'RUST-FILE-COMMANDS.json', 'PRIMARY-SOURCE-PINS.json']

for parent in reversed(TARGET.parents):
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RuntimeError('non-directory or symlink parent: ' + str(parent))
if str(TARGET.parent.resolve()) != str(TARGET.parent):
    raise RuntimeError('evidence parent realpath differs')

created = False
try:
    info = TARGET.lstat()
except FileNotFoundError:
    os.mkdir(TARGET, mode=0o700)
    created = True
    info = TARGET.lstat()
if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
    raise RuntimeError('target is not a real directory')
if str(TARGET.resolve()) != str(TARGET):
    raise RuntimeError('target realpath differs')
for name in NAMES:
    try:
        (TARGET / name).lstat()
    except FileNotFoundError:
        continue
    raise RuntimeError('create-only input already exists: ' + name)

fd = os.open(TARGET.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    os.fsync(fd)
finally:
    os.close(fd)
print(json.dumps({'schema': 'hepta.source53-finalizer-scope-directory-preparation.v1',
                  'target': str(TARGET), 'created': created, 'is_real_directory': True,
                  'mode': stat.S_IMODE(info.st_mode), 'all_four_targets_absent': True,
                  'source_Rust_metadata_fix_fmt_executed': False}, sort_keys=True), flush=True)
