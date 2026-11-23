from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile
p=Path(sys.argv[1]);assert sha256(p.read_bytes()).hexdigest()=='e4af4f72012806d03c48902370639cef6983383426b8a8fc3998a40a58f193d4'
with ZipFile(p)as z:
 assert z.testzip() is None and z.read('source.txt').decode().strip()=='3dbf9f884e77fff4d0028d16fa306036e1af30a3'
 rows=json.loads(z.read('runs.json'));assert len(rows)==10 and sorted(r['pair']for r in rows)==list(range(1,11));counts=Counter()
 for row in rows:
  raw=z.read(f"{row['pair']:02d}-observation.log");assert sha256(raw).hexdigest()==row['sha256'];s=raw.decode();m=re.findall(r'queued original readback error after peer EOF: Some\(([^)]+)\)',s);assert m==row['marker'] and len(m)==1;ok=m[0]=='Unavailable';assert (row['exit']==0)==ok;assert ('test result: ok. 1 passed; 0 failed; 0 ignored;'in s)==ok;assert ('test result: FAILED. 0 passed; 1 failed; 0 ignored;'in s)==(not ok);counts[m[0]]+=1
 assert counts=={'QueueFull':5,'Unavailable':5};print(json.dumps({'errors':dict(counts),'wall_seconds_for_10':sum(row['wall_s']for row in rows),'ELF':z.read('elf.txt').decode().split()[0]},indent=2))
