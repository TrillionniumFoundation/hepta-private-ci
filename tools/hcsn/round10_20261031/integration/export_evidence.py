"""Export scientific evidence as an artifact and chunked, verified text transport.

Only files beneath the explicitly supplied experiment evidence directory are
included. Working owner directories are reproducible from INPUTS and excluded.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import tarfile


def export(evidence, archive):
    entries = []
    with tarfile.open(archive, "w:gz") as bundle:
        for path in sorted(evidence.rglob("*")):
            relative = path.relative_to(evidence)
            if not path.is_file() or path.is_symlink() or "work" in relative.parts:
                continue
            raw = path.read_bytes()
            entries.append({"path":str(relative),"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()})
            bundle.add(path, arcname=str(relative), recursive=False)
    raw = archive.read_bytes()
    encoded = base64.b64encode(raw).decode()
    manifest = {"schema":"hepta.r10.ci-evidence-transport.v1","archive":archive.name,
                "bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"files":entries,
                "parts":(len(encoded)+59999)//60000}
    print("HCSN_EVIDENCE_MANIFEST "+json.dumps(manifest),flush=True)
    for index,offset in enumerate(range(0,len(encoded),60000)):
        print("HCSN_EVIDENCE_PART "+json.dumps({"index":index,"data":encoded[offset:offset+60000]}),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evidence",type=Path,required=True)
    p.add_argument("--archive",type=Path,required=True)
    args=p.parse_args()
    if args.evidence.is_dir():
        export(args.evidence,args.archive)
