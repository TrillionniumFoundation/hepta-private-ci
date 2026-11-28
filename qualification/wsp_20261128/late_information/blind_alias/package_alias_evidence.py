"""Archive the sealed GPT-view follow-up without changing the initial archive."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile

ROOT = Path(__file__).resolve().parent
OUT = ROOT/"publish/late_information/blind_alias"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    OUT.mkdir(exist_ok=False)
    files = [(p,"neuron_experiments/"+str(p.relative_to(ROOT))) for p in sorted((ROOT/"blind_alias").rglob("*")) if p.is_file() and p.name != "native-bridge-frozen"]
    for name in ("BLIND_ALIAS_PROTOCOL.md","make_blind_alias_packet.py","evaluate_blind_alias.py","package_alias_evidence.py"):
        files.append((ROOT/name,"neuron_experiments/"+name))
    raw = io.BytesIO()
    members = []
    with tarfile.open(fileobj=raw,mode="w",format=tarfile.PAX_FORMAT) as archive:
        for path,name in sorted(files,key=lambda x:x[1]):
            data=path.read_bytes(); info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644;info.mtime=0
            archive.addfile(info,io.BytesIO(data))
            members.append({"path":name,"bytes":len(data),"sha256":sha(data),"mode":info.mode})
    plain=raw.getvalue(); compressed=gzip.compress(plain,compresslevel=9,mtime=0)
    (OUT/"evidence.parts").mkdir()
    chunks=[]
    for i,start in enumerate(range(0,len(compressed),450000)):
        part=compressed[start:start+450000];name=f"evidence.parts/{i:05}.bin"
        (OUT/name).write_bytes(part);chunks.append({"path":name,"bytes":len(part),"sha256":sha(part)})
    manifest={"schema":"hepta.alias-transfer-evidence.v1","files":members,"chunks":chunks,
        "archive_bytes":len(compressed),"archive_sha256":sha(compressed),"uncompressed_tar_bytes":len(plain),"uncompressed_tar_sha256":sha(plain),
        "dependency": {"initial_evidence_archive_sha256":"8408958e7e6340c51e47e695fb2c9add7eb20fbfeacdafa8b5d5b78eb91d778e",
                       "native_binary_sha256":"825e5200a83a6ff86485bfa161913440d1d3ea25c10cc4377d480c25c2ce660c",
                       "binary_original_path":"neuron_experiments/late_results/native-bridge-frozen"}}
    (OUT/"EVIDENCE_MANIFEST.json").write_text(json.dumps(manifest,indent=2)+"\n")
    for source,target in ((ROOT/"blind_alias/RESEARCH_RESULT.md","RESEARCH_RESULT.md"),(ROOT/"blind_alias/results/RESULT.json","RESULT.json"),
                         (ROOT/"BLIND_ALIAS_PROTOCOL.md","PROTOCOL.md"),(ROOT/"unpack_evidence.py","unpack_evidence.py"),
                         (ROOT/"make_blind_alias_packet.py","make_blind_alias_packet.py"),(ROOT/"evaluate_blind_alias.py","evaluate_blind_alias.py"),
                         (ROOT/"package_alias_evidence.py","package_alias_evidence.py")):
        shutil.copyfile(source,OUT/target)
    print(json.dumps({"files":len(members),"chunks":len(chunks),"archive_bytes":len(compressed),"archive_sha256":sha(compressed)}))


if __name__=="__main__":
    main()
