"""Capture a bounded actual tool result from local stdin, without interpreting it."""
from pathlib import Path
import hashlib
import json
import os
import sys
import tty

target=Path(sys.argv[1]).absolute()
length=int(sys.argv[2])
if not 0 < length <= 8*1024*1024 or target.parent.resolve(strict=True)!=target.parent:
    raise ValueError('invalid bounded capture destination')
with target.open('xb') as output:
    if os.isatty(0):tty.setraw(0)
    print('READY',flush=True)
    remaining=length;digest=hashlib.sha256()
    while remaining:
        block=os.read(0,min(remaining,1024*1024))
        if not block:raise ValueError('truncated actual tool response')
        if output.write(block)!=len(block):raise ValueError('short capture write')
        digest.update(block);remaining-=len(block)
    output.flush();os.fsync(output.fileno())
raw=target.read_bytes()
if len(raw)!=length or hashlib.sha256(raw).hexdigest()!=digest.hexdigest():
    raise ValueError('persisted actual RPC changed')
print(json.dumps({'result':'SAVED_ACTUAL_RPC','path':str(target),'bytes':length,'sha256':digest.hexdigest()}),flush=True)
