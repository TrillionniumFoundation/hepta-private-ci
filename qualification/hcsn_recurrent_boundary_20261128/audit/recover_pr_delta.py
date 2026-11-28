"""Reconcile the frozen advertised Git blob roster against prior row hashes and fresh raw blob downloads."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time

ROOT = Path.home() / '.local/state/hepta-hcsn-1140569-audit/refs-namespace'
SOURCE = ROOT / 'delta/other'
OUT = ROOT / 'delta/recovery_9de7'
OUT.mkdir(exist_ok=True)
roster_bytes = gzip.decompress((SOURCE/'roster.tsv.gz').read_bytes())
meta = json.loads((SOURCE/'roster.json').read_bytes())
assert hashlib.sha256(roster_bytes).hexdigest() == meta['uncompressed_sha256']
roster = dict(row.split('\t') for row in roster_bytes.decode().splitlines())
original = sqlite3.connect(f'file:{SOURCE}/binary.sqlite?mode=ro', uri=True)
prior = {r[0]:r for r in original.execute('select oid,label,size,sha256,magic from blobs')}
oldsum = json.loads((SOURCE/'binary_summary.json').read_bytes())
table = ''.join('\t'.join(map(str,r))+'\n' for r in sorted(prior.values())).encode()
assert hashlib.sha256(table).hexdigest() == oldsum['uncompressed_table_sha256']
assert all(roster[oid]==row[1] for oid,row in prior.items())
errors = dict(original.execute('select oid,reason from errors'))
assert set(errors)==roster.keys()-prior.keys()
db = sqlite3.connect(OUT/'rows.sqlite')
db.execute('create table if not exists recovered (oid text primary key, label text, size integer, sha256 text)')
db.execute('create table if not exists failures (oid text primary key, reason text)')

def download(oid):
    for i in range(3):
        try:
            with tempfile.TemporaryFile() as f:
                result=subprocess.run(['gh','api','-H','Accept: application/vnd.github.raw+json','/repos/TrillionniumFoundation/hepta-private-ci/git/blobs/'+oid],stdout=f,stderr=subprocess.PIPE,timeout=75)
                if result.returncode:
                    raise RuntimeError('GitHub raw download exited '+str(result.returncode)+' '+result.stderr.decode(errors='replace')[:100])
                size=f.tell()
                h=hashlib.sha1(b'blob '+str(size).encode()+b'\0')
                s=hashlib.sha256()
                f.seek(0)
                for block in iter(lambda:f.read(1<<20),b''):
                    h.update(block)
                    s.update(block)
            if h.hexdigest()!=oid:
                raise ValueError('Git ID disagrees with streamed bytes')
            return (oid,roster[oid],size,s.hexdigest())
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            err=exc
            time.sleep(i+1)
    raise err

pending=sorted(set(errors)-{r[0] for r in db.execute('select oid from recovered')})
print('pending',len(pending),flush=True)
with ThreadPoolExecutor(max_workers=4) as pool:
    jobs={pool.submit(download,oid):oid for oid in pending}
    for i,f in enumerate(as_completed(jobs),1):
        oid=jobs[f]
        with db:
            try:
                db.execute('insert or replace into recovered values(?,?,?,?)',f.result())
                db.execute('delete from failures where oid=?',(oid,))
            except Exception as e:
                db.execute('insert or replace into failures values(?,?)',(oid,str(e)))
        if i%20==0 or i==len(jobs):
            print('completed',i,'of',len(pending),flush=True)
recovered={r[0]:r for r in db.execute('select oid,label,size,sha256 from recovered')}
assert set(prior).isdisjoint(recovered)
combined={o:r[:4] for o,r in prior.items()} | recovered
detail=''.join('\t'.join(map(str,r))+'\n' for r in sorted(combined.values())).encode()
(OUT/'verified_objects.tsv.gz').write_bytes(gzip.compress(detail,mtime=0))
failures=dict(db.execute('select oid,reason from failures'))
report={'utc':datetime.now(timezone.utc).isoformat(),'repo':'TrillionniumFoundation/hepta-private-ci','roster_sha256':hashlib.sha256(roster_bytes).hexdigest(),'source_first_pass_summary_sha256':hashlib.sha256((SOURCE/'binary_summary.json').read_bytes()).hexdigest(),'first_pass_rows_hash_verified':len(prior),'raw_api_recovered_rows':len(recovered),'raw_api_recovered_bytes':sum(r[2] for r in recovered.values()),'total_verified':len(combined),'total_payload_bytes':sum(r[2] for r in combined.values()),'missing':sorted(roster.keys()-combined.keys()),'failures':failures,'classification_counts':dict(Counter(meta['labels'][r[1]] for r in combined.values())),'merged_uncompressed_table_sha256':hashlib.sha256(detail).hexdigest()}
(OUT/'receipt.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report),flush=True)
assert not failures and len(combined)==len(roster)
