"""Verify 42 source classifications and optionally replay all 40 file-level Rustfmt checks.

Use the repository checkout holding the pinned historical source records and CI evidence.
For replay supply --rustfmt VERSION=/path/to/rustfmt for each version named in the report.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
from zipfile import ZipFile

def sha(data):
    return hashlib.sha256(data).hexdigest()


def git_hash(kind, data):
    return hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).hexdigest()


def verify_trees(proof):
    commits, trees = {}, {}
    for line in proof.splitlines():
        kind, name, value = json.loads(line)
        if kind == "commit":
            commits[name] = value["tree"]
            assert name.rsplit("@",1)[1] == value["commit"]
            continue
        assert kind == "tree" and name not in trees
        fields = []
        lookup = {}
        for mode, filename, oid in value:
            key = filename.encode()
            assert b"/" not in key and b"\0" not in key
            assert filename not in lookup
            lookup[filename] = oid
            fields.append(mode.lstrip("0").encode() + b" " + key + b"\0" + bytes.fromhex(oid))
        assert git_hash("tree",b"".join(fields)) == name
        trees[name] = lookup
    return commits, trees


def resolve(commits, trees, repo, commit, path):
    oid = commits[repo+"@"+commit]
    for name in path.split("/"):
        oid = trees[oid][name]
    return oid


def replay(row, rec, tools, metadata, src):
    tool = tools[rec["toolchain"]]
    assert sha(tool.read_bytes()) == rec["rustfmt_elf_sha256"]
    version = subprocess.check_output([tool,"--version"],text=True).strip()
    assert version == rec["rustfmt_version"]
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        file = root / Path(row["path"]).name
        file.write_bytes(src); file.chmod(0o444)
        cfg = root / "rustfmt.toml"
        config = rec.get("config_blob")
        cfg.write_bytes(metadata.read("metadata/"+config) if config else b""); cfg.chmod(0o444)
        result = subprocess.run([tool,"--check","--edition",rec["edition"],"--config-path",cfg,
                   "--config","skip_children=true","--",file],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        assert result.returncode == rec["exit"]
        assert sha(file.read_bytes()) == row["sha256"]
        normalized = result.stdout.replace(str(root).encode(), b"{temporary-readonly-copy}")
        assert sha(normalized) == rec["output_replacing_ephemeral_root_sha256"], row["path"]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo",required=True,type=Path)
    parser.add_argument("--records",type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument("--rustfmt",action="append",default=[],metavar="VERSION=PATH")
    args=parser.parse_args()
    root=args.repo.resolve()
    rec=args.records
    fmt={v.split("=",1)[0]:Path(v.split("=",1)[1]).resolve() for v in args.rustfmt}
    if fmt: assert set(fmt)=={"1.88.0","1.95.0","1.96.0","nightly-2026-07-21"}
    report=json.loads((rec/"ownership42.json").read_text())
    rows=report["rows"]
    assert len(rows)==len({r["path"] for r in rows})==42
    original=rec/"original-probe.zip"
    assert sha(original.read_bytes())=="91ac631d663b8b25d75c2191533a0d90263c77b049d17ea9c4daadf08f9cd66c"
    with ZipFile(original) as z:
        assert z.testzip() is None
        rs=json.loads(gzip.decompress(z.read("rust-editions.json.gz")))
        paths=json.loads(gzip.decompress(z.read("paths.json.gz")))
        original_report=json.loads(z.read("probe.json"))
        assert len(paths)==46974 and len(rs)==4219 and original_report["original_exit"]==2
        sampled={x["path"] for x in rs if x["path"].startswith(("AUDIT/","qualification/","research/")) and "error" not in x}
        assert {r["path"] for r in rows}==sampled
        assert git_hash("blob",z.read("original-workspace-manifest.txt"))=="d2703b590935ab17316e6c258657c0ce5ab7412a"
        assert sha(z.read("fmt.log"))=="151b04b64f55954a2c333a4fd282155d858e1696590f90030a27fd8fe52f9c64"
    kinds=Counter();outs=Counter();origin_count=ran=0
    with ZipFile(rec/"source-ownership-metadata.zip") as z:
        assert z.testzip() is None
        commits, trees=verify_trees(z.read("git-tree-proof.ndjson").decode())
        for name in z.namelist():
            if name.startswith("metadata/"):
                assert git_hash("blob",z.read(name))==name.split("/")[1]
        for row in rows:
            data=(root/row["path"]).read_bytes()
            assert sha(data)==row["sha256"] and row["git_blob"]==git_hash("blob",data)
            for e in row["evidence_files"]:
                raw=(root/e["path"]).read_bytes()
                assert sha(raw)==e["sha256"] and git_hash("blob",raw)==e["frozen_git_blob"]
            if 'origin_repo' in row:
                origin_count+=1
                args=(commits,trees,row["origin_repo"],row["origin_commit"])
                assert resolve(*args,row["origin_path"])==row["git_blob"]
                for f in row["original_ancestor_metadata"]:
                    assert resolve(*args,f["path"])==f["sha"]
            kinds[row["classification"]]+=1
            saved=row.get("source_qualified_readonly_check") or row.get("current_comparator")
            if saved:
                outs[row["classification"]+" | "+saved["result"]]+=1
                if fmt:
                    replay(row,saved,fmt,z,data); ran+=1
            else:
                assert row["missing_input"]
    assert origin_count==33 and kinds=={"historical_snapshot":35,"maintained_source":7}
    assert outs=={"historical_snapshot | pass":32,"historical_snapshot | format-difference":1,
                  "maintained_source | pass":6,"maintained_source | format-difference":1}
    assert not fmt or ran==40
    print(json.dumps({"rows":42,"source_commits":len(commits),"independently_hashed_trees":len(trees),
                      "source_blobs_from_their_recorded_commits":origin_count,"classifications":dict(kinds),
                      "recorded_results":dict(outs),"replayed_checks":ran},indent=2))

if __name__=="__main__":
    main()
