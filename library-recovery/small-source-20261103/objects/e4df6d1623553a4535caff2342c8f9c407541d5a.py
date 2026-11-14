#!/usr/bin/env python3
import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parent
m=json.loads((root/'manifest.json').read_text())
missing=[p for p,d in m['source_files'].items() if not (root/p).is_file() or hashlib.sha256((root/p).read_bytes()).hexdigest()!=d['sha256']]
if missing:raise SystemExit('HOLD_NO_GO: source checksum mismatch: '+','.join(missing))
print('Research source/checksum verification:',len(m['source_files']),'files; this is not trusted third-party attestation')
