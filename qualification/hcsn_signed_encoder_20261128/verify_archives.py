"""Verify every first-run per-cell archive and its original weights and predictions in a Git checkout."""
import gzip,hashlib,io,json,tarfile
from pathlib import Path
def sha(b):return hashlib.sha256(b).hexdigest()
def unpack_index(root):
    value={}
    for name,row in json.loads((root/"archive_index.json").read_text()).items():
        data=bytearray()
        for p in row["parts"]:
            part=(root/p["path"]).read_bytes()
            if len(part)!=p["bytes"] or sha(part)!=p["sha256"]:raise ValueError(p["path"])
            data+=part
        if len(data)!=row["bytes"] or sha(data)!=row["sha256"]:raise ValueError(name)
        value[name]=data
    return value
def main(root):
    base=root/"results";reconstructed=unpack_index(base);manifest=json.loads((base/"original_manifest.json").read_text());stored={}
    for name,row in manifest.items():
        data=reconstructed[name] if name in reconstructed else (base/name).read_bytes()
        if sha(data)!=row["sha256"] or len(data)!=row["bytes"]:raise ValueError(name)
        with tarfile.open(fileobj=io.BytesIO(data),mode="r:gz") as archive:
            if set(archive.getnames())!=set(row["members"]):raise ValueError(name)
            for key,rec in row["members"].items():
                member=archive.extractfile(key);raw=member.read();digest=sha(raw)
                if len(raw)!=rec["bytes"] or digest!=rec["sha256"]:raise ValueError(key)
                stored[name,key]=digest
    print("Original native records verified:",len(stored))
    supplement=root/"interleaved/raw"
    if (supplement/"archive_index.json").exists():
        sup=unpack_index(supplement);rows=json.loads((supplement/"timing_manifest.json").read_text())
        for name,row in rows.items():
            loc=row["storage"]
            if "original_archive" in loc:
                if stored[loc["original_archive"],loc["member"]]!=row["sha256"]:raise ValueError(name)
            else:
                copy=loc["supplementary_archive"]
                data=sup[copy] if copy in sup else (supplement/copy).read_bytes()
                if sha(data)!=loc["compressed_sha256"]:raise ValueError(copy)
                orig=gzip.decompress(data)
                if len(orig)!=row["bytes"] or sha(orig)!=row["sha256"]:raise ValueError(name)
        print("Interleaved native records verified:",len(rows))
if __name__=="__main__":main(Path(__file__).resolve().parent)
