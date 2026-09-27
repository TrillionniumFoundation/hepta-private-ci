#!/usr/bin/env python3
"""One-time exact-byte repair of an interrupted source transport; no source rewrite."""
import base64
import hashlib
import json
from pathlib import Path
import zlib
p = Path('scripts/patches/memory_retrieval_runtime_v1.json')
raw = p.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '3749f44c460cbbfbb8ee7ee54877dbcb8176226d70387c913eb485e338a95121'
value = json.loads(raw)
s = value['patch_zlib_base64']
for begin, end, old, new in ((3304, 3307, 'YZh', 'l'), (1703, 1704, 'X', ''), (1166, 1167, 'Z', '')):
    assert s[begin:end] == old
    s = s[:begin] + new + s[end:]
patch = zlib.decompress(base64.b64decode(s, validate=True))
assert len(patch) == 41516
assert hashlib.sha256(patch).hexdigest() == '3f8b5962fcc66093f58eedc790ac7cf4178d48931c844872929717ab849f061c'
value['patch_zlib_base64'] = s
p.write_text(json.dumps(value, indent=2) + '\n')
