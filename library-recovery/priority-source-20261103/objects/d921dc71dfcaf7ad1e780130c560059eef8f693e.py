"""Separate, standard-library-only rehash of original on-disk downloaded files.

No dependency on producer, model framework, network or automatic promotion.
The claims are limited to self-observed source bytes vs recorded Hub identities.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path

SCHEMA = "hepta.stem.equal-size.physical-source-bytes.v1"
REVIEW = "hepta.stem.equal-size.physical-byte-review.v1"

class Rejected(ValueError):
    pass


def check(ok, why):
    if not ok:
        raise Rejected(why)


def read_sealed(path):
    p=Path(path)
    check(p.is_file() and not p.is_symlink() and p.stat().st_size <= 256*1024,
          "invalid producer receipt")
    def pairs(kv):
        o={}
        for k,v in kv:
            check(k not in o,"duplicated JSON field")
            o[k]=v
        return o
    return json.loads(p.read_text(),object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(Rejected("nonfinite JSON")))


def audit(source, stage):
    check(type(source) is dict and source.get("schema") == SCHEMA and
          source.get("authority") == "DENY_ALL" and source.get("disposition") == "HOLD_NO_GO" and
          source.get("tensor_model_loaded") is False and source.get("torch_pickle_loaded") is False and
          source.get("real_model_forward_completed") is False and
          source.get("publisher_signature_verified") is False and
          source.get("production_promotion_permitted") is False,
          "producer claims unsupported authority")
    items=source.get("selected_source_inventory")
    result=source.get("files")
    check(type(items) is list and type(result) is list and len(items)==len(result)==source.get("file_count")
          and 0<len(items)<=512,"incomplete receipt list")
    root=Path(stage)
    check(root.is_dir() and not root.is_symlink(),"untrusted root")
    observed=[]
    seen=set()
    for meta,prior in zip(items,result):
        check(type(meta) is dict and type(prior) is dict and set(prior)=={"filename","sha256","size"},
              "invalid source entry")
        name=meta.get("filename")
        check(type(name) is str and 0<len(name)<=256 and "\\" not in name and
              all(x not in ("", ".", "..") and not x.startswith(".") for x in name.split("/")) and
              name not in seen, "invalid/duplicate source filename")
        seen.add(name)
        identity_type=meta.get("source_identity_type")
        identity=meta.get("source_identity")
        count=meta.get("published_size")
        check(type(count) is int and count>0 and count<=3*1024**3 and
              identity_type in ("lfs_sha256", "git_blob_sha1") and
              type(identity) is str and len(identity)==(64 if identity_type=="lfs_sha256" else 40) and
              all(c in "0123456789abcdef" for c in identity), "invalid original source metadata")
        p=root.joinpath(*name.split("/"))
        check(not any(a.is_symlink() for a in p.parents if a != root),"parent symlink")
        check(p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root.resolve()),
              "missing source or alias")
        fd=os.open(p, os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_NONBLOCK",0))
        try:
            st=os.fstat(fd)
            check(stat.S_ISREG(st.st_mode) and st.st_size==count,"size mismatch")
            sha=hashlib.sha256()
            blob=hashlib.sha1(b"blob "+str(count).encode()+b"\0")
            length=0
            while part:=os.read(fd,1024*1024):
                length+=len(part)
                check(length<=count,"oversized stream")
                sha.update(part);blob.update(part)
            fin=os.fstat(fd)
            check(length==count and (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)==
                  (fin.st_dev,fin.st_ino,fin.st_size,fin.st_mtime_ns),"changed during audit")
        finally:
            os.close(fd)
        actual=sha.hexdigest()
        check((actual if identity_type=="lfs_sha256" else blob.hexdigest())==identity and
              prior=={"filename":name,"sha256":actual,"size":count},"original independent checksum mismatch")
        observed.append({"filename":name,"sha256":actual,"size":count})
    check([a["filename"] for a in observed]==sorted(seen),"file order drift")
    return {"schema":REVIEW,"model":source.get("model"),"repo":source.get("repo"),
            "revision":source.get("revision"),"file_count":len(observed),
            "total_bytes_rehashed":sum(a["size"] for a in observed),
            "source_sha256_receipt":hashlib.sha256(json.dumps(source,sort_keys=True,separators=(",", ":"),
                                                         allow_nan=False).encode()).hexdigest(),
            "independently_rehashed_exact_physical_bytes":True,
            "actual_model_forward_verified":False,"issuer_signature_verified":False,
            "all_four_models_complete":False,"authority":"DENY_ALL",
            "production_promotion_permitted":False,"disposition":"HOLD_NO_GO"}


def main(argv=None):
    a=argparse.ArgumentParser(description="Independent original-source rehash, no model load")
    a.add_argument("--receipt",required=True)
    a.add_argument("--stage",required=True)
    a.add_argument("--out",required=True)
    args=a.parse_args(argv)
    result=audit(read_sealed(args.receipt),args.stage)
    dst=Path(args.out)
    check(dst.parent.is_dir() and not dst.parent.is_symlink() and not dst.exists(), "unsafe audit output")
    body=(json.dumps(result,sort_keys=True,separators=(",", ":"),allow_nan=False)+"\n").encode()
    fd=os.open(dst,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"wb") as f:
        f.write(body);f.flush();os.fsync(f.fileno())
    print("independent physical source-byte review PASS; no model forward or promotion")

if __name__=="__main__":main()
