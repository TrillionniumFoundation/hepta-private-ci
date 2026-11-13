import base64,hashlib,json,stat,zlib
from pathlib import Path
p=Path("/home/qq/af52-learning-local-decision-20261111/ordinary-future-197-maintenance-v7/records/final.patch")
s=p.lstat()
assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and not p.is_symlink()
raw=p.read_bytes()
t=p.lstat()
assert (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)==(t.st_dev,t.st_ino,t.st_size,t.st_mtime_ns,t.st_ctime_ns)
assert len(raw)==756178
assert hashlib.sha256(raw).hexdigest()=="e776f38c799c1aee19828c33e8262963341990b6c936cfe0eed64841c4037cf0"
assert hashlib.sha1(b"blob "+str(len(raw)).encode()+bytes([0])+raw).hexdigest()=="7f8e1205d896062566a5f95fbdbe41195d714d9b"
encoder=zlib.compressobj(level=9,wbits=-15)
compressed=encoder.compress(raw)+encoder.flush()
assert zlib.decompress(compressed,wbits=-15)==raw
print(json.dumps({"schema_version":1,"classification":"READ_ONLY_ORIGINAL_EVIDENCE_BYTE_TRANSPORT_NOT_QUALIFICATION","original_path":str(p),"original_bytes":len(raw),"original_sha256":hashlib.sha256(raw).hexdigest(),"original_git_blob":"7f8e1205d896062566a5f95fbdbe41195d714d9b","original_version":[str(getattr(t,x)) for x in ("st_dev","st_ino","st_size","st_mtime_ns","st_ctime_ns")],"encoding":"raw-deflate-base64","compressed_bytes":len(compressed),"compressed_sha256":hashlib.sha256(compressed).hexdigest(),"python_roundtrip_exact":True,"data_base64":base64.b64encode(compressed).decode("ascii")},sort_keys=True),flush=True)
