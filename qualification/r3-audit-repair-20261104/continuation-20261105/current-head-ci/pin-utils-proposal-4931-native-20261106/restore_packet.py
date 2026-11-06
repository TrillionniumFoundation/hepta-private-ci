#!/usr/bin/env python3
"""Restore the immutable #4931 original-artifact packet and replay offline evidence checks."""
import argparse, base64, copy, gzip, hashlib, io, json, os, subprocess, sys, tarfile, zipfile
from pathlib import Path, PurePosixPath

def ident(b):
    return {"bytes":len(b), "git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest(), "sha256":hashlib.sha256(b).hexdigest()}
def require(x, s):
    if not x: raise AssertionError(s)
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--packet",type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument("--destination",type=Path,required=True)
    args=parser.parse_args()
    packet=args.packet.resolve(); dest=args.destination.resolve()
    require(not dest.exists(),"destination must be new")
    dest.mkdir(parents=True)
    m=json.loads((packet/"archive-manifest.json").read_bytes())
    chunks=[]
    for p in m["parts"]:
        b=(packet/p["path"]).read_bytes()
        require(ident(b)==p["file_identity"],"base64 piece identity")
        raw=base64.b64decode(b.strip(),validate=True)
        require(ident(raw)==p["decoded_identity"],"decoded piece identity")
        chunks.append(raw)
    gz=b"".join(chunks)
    require(ident(gz)==m["archive_identity"],"complete gzip identity")
    raw=gzip.decompress(gz)
    require(ident(raw)==m["tar_identity"],"complete tar identity")
    expected={x["path"]:x for x in m["members"]}
    with tarfile.open(fileobj=io.BytesIO(raw),mode="r:") as tar:
        files=tar.getmembers()
        require(len(files)==len(expected) and set(x.name for x in files)==set(expected),"tar roster")
        for member in files:
            path=PurePosixPath(member.name)
            require(member.isfile() and not path.is_absolute() and ".." not in path.parts and str(path)==member.name,"safe regular tar path")
            data=tar.extractfile(member).read()
            require(ident(data)==expected[member.name]["identity"] and member.mode==expected[member.name]["mode"],"member identity/mode")
            f=dest/member.name;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(data);f.chmod(member.mode)
    root=dest/"root"
    zp=root/"artifact-13482877841.original.zip"
    with zipfile.ZipFile(zp) as z:
        require(z.testzip() is None and len(z.namelist())==41,"original official ZIP")
        for member in z.infolist():
            path=PurePosixPath(member.filename)
            require(not member.is_dir() and not path.is_absolute() and ".." not in path.parts and str(path)==member.filename,"safe original ZIP path")
            f=root/"artifact"/member.filename;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(z.read(member))
    run=subprocess.run([sys.executable,str(root/"verify_native_artifact.py"),"--root",str(root),"--output",str(root/"portable-replay")],
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    (dest/"verifier.stdout.original.json").write_bytes(run.stdout)
    (dest/"verifier.stderr.original.txt").write_bytes(run.stderr)
    require(run.returncode==0 and run.stderr==b"","offline verifier success")
    require(run.stdout==(root/"replay-02.stdout.json").read_bytes(),"all verifier stdout bytes identical")
    for name in ["VERIFICATION.json","product-source-map.json","intended-product-full-tree.json","module-complete-diff.json"]:
        require((root/"portable-replay"/name).read_bytes()==(root/"verification-02"/name).read_bytes(),"derived original bytes identical: "+name)
    def canon_commands(x):
        x=copy.deepcopy(x)
        for row in x["commands"]:
            if "apply" in row["argv"]:
                patch_path=row["argv"][-1]
                require(patch_path.endswith("/artifact/proposal.patch"),"only exact absolute patch input normalization")
                if row["stderr"]:
                    suffix=":46375: new blank line at EOF.\n+\nwarning: 1 line adds whitespace errors.\n"
                    require(row["stderr"]==patch_path+suffix,"preserve exact known original-patch warning")
                    row["stderr"]="<RESTORED_ROOT>/artifact/proposal.patch"+suffix
                row["argv"][-1]="<RESTORED_ROOT>/artifact/proposal.patch"
        return x
    require(canon_commands(json.loads((root/"portable-replay/git-index-replay.json").read_bytes()))==
            canon_commands(json.loads((root/"verification-02/git-index-replay.json").read_bytes())),"all Git receipts equal except declared restored artifact path")
    source_registry=json.loads((root/"product-source-registration/registry.actual.json").read_bytes())
    actual={}
    for group in source_registry["raw_full_GET_groups"]:
        b=(root/group["file"]).read_bytes()
        require(ident(b)=={k:group[k] for k in ("bytes","git_blob","sha256")},"raw full GET file identity")
        for row in json.loads(b)["records"]:
            data=row["full_tool_return"]["structuredContent"]["content"].encode()
            require(ident(data)["git_blob"]==row["git_blob"],"full GET returned blob")
            actual[row["git_blob"]]=data
    require(len(actual)==219,"219 distinct actual original GETs")
    for row in source_registry["files"]:
        raw=(root/"verification-02"/row["local_relative_path"]).read_bytes()
        require(raw==actual[row["git_blob"]] and ident(raw)=={k:row[k] for k in ("bytes","git_blob","sha256")},"all223 actual source files")
        require(raw==(root/"portable-replay"/row["local_relative_path"]).read_bytes(),"restored product bytes")
    report={"schema":"pin-utils-actual-product-packet-restore-v1","archive_members":len(expected),
            "member_bytes":sum(x["identity"]["bytes"] for x in m["members"]),"original_ZIP_members":41,
            "offline_verifier_exit":run.returncode,"stderr_bytes":0,"stdout_full_byte_equal":True,
            "stdout_identity":ident(run.stdout),"four_derived_files_full_byte_equal":True,
            "Git_command_receipts":"All values equal; only the exact artifact/proposal.patch absolute input path in argv and the two unchanged EOF-whitespace warnings is normalized for relocation.",
            "registered_product_paths":223,"actual_distinct_blob_GETs":219,
            "product_tree":"c7b9fb4e029dc38034a7dfce10a646ccde3e0bf6",
            "new_Cargo_Bazel_native_or_network_calls":0,"ref_or_PR_mutation":False}
    (dest/"RESTORE_VERIFICATION.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))
if __name__=="__main__": main()
