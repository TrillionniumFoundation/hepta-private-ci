"""Freeze the small terminal-numerics handoff; no research computation."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'terminal-numerics-final-evidence-v1'
provenance_path = OUT / 'PROVENANCE.json'
provenance = json.loads(provenance_path.read_bytes())
copies = [(ROOT / 'terminal-numerics-final-assembly-v1' / name, 'assembly/' + name)
          for name in ('EXECUTION.json', 'stdout', 'stderr')]
copies += [(ROOT / 'hcsn-terminal-numerics-collector-receipts-20261110-v1.zip', 'transport/ORIGINAL-RECEIPTS.zip'),
           (Path(__file__), 'assembly/freeze_terminal_numerics_small_v1.py')]
for source, relative in copies:
    raw = source.read_bytes()
    target = OUT / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.open('xb').write(raw)
    provenance[relative] = {'kind': 'exact_original_bytes', 'source': str(source)}
provenance_path.write_text(json.dumps(provenance, indent=2, sort_keys=True) + '\n')
items = []
for path in sorted(OUT.rglob('*')):
    if not path.is_file():
        continue
    raw = path.read_bytes()
    assert len(raw) <= 500000, path
    relative = str(path.relative_to(OUT))
    items.append({'source': str(path), 'relative_path': relative, 'bytes': len(raw),
                  'sha256': hashlib.sha256(raw).hexdigest(),
                  'kind': provenance.get(relative, {}).get('kind', 'derived_metadata_only')})
value = {'schema': 'terminal-numerics-small-originals-copy-list-v1', 'source_root': str(OUT),
         'files': items, 'file_count': len(items), 'sum_bytes': sum(r['bytes'] for r in items),
         'maximum_item_bytes': max(r['bytes'] for r in items), 'each_item_maximum_bytes': 500000,
         'scope': 'Copy each item unchanged under a new evidence prefix. COPY_LIST itself is also part of the handoff, with its digest supplied externally. No global index or CURRENT file modified.'}
path = OUT / 'COPY_LIST.json'
path.open('x').write(json.dumps(value, indent=2, sort_keys=True) + '\n')
print(json.dumps({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                  'file_count': len(items), 'sum_bytes': value['sum_bytes'], 'maximum_item_bytes': value['maximum_item_bytes']}))
