import base64,datetime,gzip,hashlib,json,os,sys
from pathlib import Path
p=json.load(sys.stdin)
root=Path("/home/qian-qi/hepta-utility-36fa-training-readback-overlay-v1")
if p["records"] != str(root):
    raise RuntimeError("unexpected external records path")
root.mkdir(exist_ok=False)
written=[]
for item in p["files"]:
    name=item["name"]
    if Path(name).name != name or name in {row["path"] for row in written}:
        raise RuntimeError("unsafe or duplicate preparation path")
    data=item["content"].encode("utf-8")
    if hashlib.sha256(data).hexdigest()!=item["sha256"]:
        raise RuntimeError("preparation byte identity mismatch: "+name)
    path=root/name
    with path.open("xb") as out:
        out.write(data);out.flush();os.fsync(out.fileno())
    if path.read_bytes()!=data:
        raise RuntimeError("create-only preparation readback mismatch: "+name)
    path.chmod(0o400)
    written.append({"path":name,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),"git_blob_sha":hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()})
for source,name,expected,expected_bytes in [
    ("overlay-packet.json.gz.b64","overlay.json","f6335dbb2100f15a6758654d60aed526b09a5ffe403d462dfb290d8dfa818222",451937),
    ("CALLERS.toml.gz.b64","CALLERS.toml","13b8b2d8d9fbe0768f0b8dd288ee8e147f5641a2affd99f7eed5b2647e107d74",1122002),
]:
    encoded=(root/source).read_bytes()
    data=gzip.decompress(base64.b64decode(encoded.strip(),validate=True))
    if len(data)!=expected_bytes or hashlib.sha256(data).hexdigest()!=expected:
        raise RuntimeError("decoded preparation identity mismatch: "+name)
    path=root/name
    with path.open("xb") as out:
        out.write(data);out.flush();os.fsync(out.fileno())
    if path.read_bytes()!=data:
        raise RuntimeError("decoded preparation readback mismatch: "+name)
    path.chmod(0o400)
    written.append({"path":name,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),"git_blob_sha":hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()})
record={"schema":"hepta.utility.training-readback-create-only-preparation.v1","at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"records":str(root),"created":written,"source_mutations":0,"source_full_gates_started":False}
with (root/"bootstrap-result.json").open("x") as out:
    json.dump(record,out,indent=2,sort_keys=True);out.write("\n");out.flush();os.fsync(out.fileno())
print(json.dumps(record,sort_keys=True),flush=True)
os.execv(sys.executable,[sys.executable,"-B",str(root/"wrapper.py")])
