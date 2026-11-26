"""Fetch only the exact public subject files described in the source manifest."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.request
import sys

folder=Path(sys.argv[1]); folder.mkdir(exist_ok=True,parents=True)
meta=json.loads(Path(__file__).with_name('SOURCE.json').read_text())
def fetch(rec):
    target=folder/Path(rec['path']).name
    url=f"https://raw.githubusercontent.com/{meta['repository']}/{meta['commit']}/{rec['path']}"
    def valid(v):return len(v)==rec['size'] and hashlib.sha1(f'blob {len(v)}'.encode()+bytes([0])+v).hexdigest()==rec['sha']
    if target.exists() and valid(target.read_bytes()):return target.name
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url,timeout=35) as src:v=src.read()
            if not valid(v):raise ValueError(target)
            target.write_bytes(v)
            return target.name
        except (OSError,ValueError):
            if attempt==2:raise
with concurrent.futures.ThreadPoolExecutor(8) as pool:
    for p in pool.map(fetch,meta['files']):print(p,flush=True)
