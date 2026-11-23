"""Read the native Bazel logs for the existing comparable Intel rolling-upgrade actions."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent
TARGET = b"//codex-rs/hepta-agentd:hepta-agentd-five_agent_rolling_upgrade-test"


def varint(data, i=0):
    result = shift = 0
    while True:
        byte = data[i]
        i += 1
        result |= (byte & 127) << shift
        if byte < 128:
            return result, i
        shift += 7


def fields(data):
    i = 0
    while i < len(data):
        tag, i = varint(data,i)
        wire = tag & 7
        if wire == 0:
            value, i = varint(data,i)
        elif wire == 2:
            n,i = varint(data,i)
            value,i = data[i:i+n],i+n
        else:
            n = {1:8,5:4}[wire]
            value,i = data[i:i+n],i+n
        yield tag >> 3,value


def inspect(artifact, expected):
    f = ROOT / f"{artifact}.zip"
    assert hashlib.file_digest(f.open("rb"),"sha256").hexdigest() == expected
    logs = {}
    matches = []
    files = {}
    with zipfile.ZipFile(f) as z:
        raw = subprocess.run(["zstd","-qdc"],input=z.read(next(n for n in z.namelist() if n.endswith(".zst"))), stdout=subprocess.PIPE,check=True).stdout
        for name in z.namelist():
            if "/files/" not in name or not name.endswith((".log",".xml")):
                continue
            contents=z.read(name)
            if b"runtime owner failure retained during shutdown: Broken pipe" in contents:
                logs[name.rsplit(".",1)[1]] = hashlib.sha256(contents).hexdigest()
    i = 0
    while i < len(raw):
        length,i=varint(raw,i)
        item,i=raw[i:i+length],i+length
        if b"hepta-agentd" not in item:
            continue
        for tag,payload in fields(item):
            if tag==3:
                f=dict(fields(payload));p=f[1].decode()
                if p.endswith(("/hepta-agentd","/codex-hepta-agentd","/hepta-agentd-five_agent_rolling_upgrade-test","/hepta-agentd-five_agent_rolling_upgrade-test-bin")):
                    h=dict(fields(f[2])); files[p]={"hash":h[1].decode(),"bytes":h[2]}
            if tag==7 and TARGET in payload:
                sp=dict(fields(payload))
                if sp.get(7)==TARGET and sp.get(8)==b"TestRunner":
                    args=[v.decode() for k,v in fields(payload) if k==1]
                    if args[0].endswith("test-setup.sh"):
                        matches.append({"runner":sp[11].decode(),"exit":sp.get(9,0),"args":args})
    assert len(matches)==1,matches
    return dict(artifact=artifact, execution=matches[0], native_failure_log_hashes=logs, binary_objects=files)


positive=inspect(14789902347,"97014fcfaba2f80541d9fe1e2c91d8ca19e36b0722733c632879371b5cc5474c")
negative=inspect(14791994823,"6f2a6b5ebf1cd9e559ab440da0cc94029a373933a72d4fd4fe0fa0df93c67d47")
print(json.dumps({"prior":positive,"current":negative},indent=2))
