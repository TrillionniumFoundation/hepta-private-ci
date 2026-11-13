import base64, datetime, gzip, hashlib, json, os, pathlib, stat

PATH = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-cc57-v2/source-gates-records/source-closure/source-closure.json.ed0273f9133d43afa01c976f1501b2af.log')
EXPECTED = {'bytes': 111500, 'sha256': '372c9a6a3a9bb6431aa8113a1198992a15e151d669f24546387d334cd0ca6ec9', 'git_blob': 'f14a6b0634263946e08dec05d8416f3b6232fb3d'}

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def stamp(s):
    return {'device': s.st_dev, 'inode': s.st_ino, 'mode': s.st_mode,
            'uid': s.st_uid, 'gid': s.st_gid, 'nlink': s.st_nlink,
            'size': s.st_size, 'mtime_ns': s.st_mtime_ns, 'ctime_ns': s.st_ctime_ns}

assert os.getuid() == 1000, 'fixed original account'
for parent in reversed(PATH.parents):
    s = parent.lstat()
    assert stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode), 'real fixed log parents'
fd = os.open(PATH, os.O_RDONLY | os.O_NOFOLLOW)
with os.fdopen(fd, 'rb') as stream:
    before = os.fstat(stream.fileno())
    assert stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
    assert before.st_size == EXPECTED['bytes'] and stat.S_IMODE(before.st_mode) == 0o400
    raw = stream.read(EXPECTED['bytes'] + 1)
    after = os.fstat(stream.fileno())
outside = PATH.lstat()
assert stamp(before) == stamp(after) == stamp(outside), 'stable original log observation'
assert identity(raw) == EXPECTED, 'original retained receipt and manifest raw identity'
packed = gzip.compress(raw, compresslevel=9, mtime=0)
assert gzip.decompress(packed) == raw
print(json.dumps({'format': 'hepta-source-closure-original-log-readonly-capture-v1',
      'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'source_log_path': str(PATH), 'source_job_id': '1a1d23c92f3-2564-1cb4',
      'source_sha': 'cc57c7198db6293ccca562253c42fffbe2a04633',
      'scope': 'Read existing completed source-closure log only; this is not a gate execution or qualification.',
      'raw': identity(raw), 'stable_stat': stamp(after), 'gzip': identity(packed),
      'gzip_base64': base64.b64encode(packed).decode(), 'source_writes': False,
      'gate_or_cargo_commands_executed': False, 'qualification': False},
      sort_keys=True, separators=(',', ':')), flush=True)
