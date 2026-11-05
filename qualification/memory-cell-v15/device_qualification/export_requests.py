"""Read only this fixture's signed requests; never read or export key files."""
import hashlib
import json
from pathlib import Path
import resource
import sqlite3
import time

start = time.perf_counter()
context = json.loads(Path('context.json').read_bytes())
connection = sqlite3.connect('file:authority.sqlite?mode=ro', uri=True)
rows = {}
for table in ('receipts', 'rejections'):
    pairs = connection.execute('SELECT signed_request,response FROM ' + table).fetchall()
    rows[table] = [dict(request=json.loads(request), receipt=json.loads(response)) for request, response in pairs
                   if json.loads(request)['request_id'].startswith(context['run_id'] + '-')]
connection.close()
usage = resource.getrusage(resource.RUSAGE_SELF)
print(json.dumps(dict(ok=True, step='export_requests', run_id=context['run_id'],
    authority_sha256=hashlib.sha256(Path('authority.py').read_bytes()).hexdigest(),
    access='sqlite-readonly', keys_accessed=False, result=rows,
    measured=dict(body_elapsed_s=time.perf_counter()-start, user_cpu_s=usage.ru_utime, system_cpu_s=usage.ru_stime)),
    sort_keys=True, separators=(',', ':')))
