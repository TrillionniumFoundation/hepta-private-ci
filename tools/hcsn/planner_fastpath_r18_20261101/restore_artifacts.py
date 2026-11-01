"""Restore exact logical artifacts from bounded transport parts; never overwrite."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

HERE=Path(__file__).resolve().parent


def safe_path(root,relative):
    path=PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:raise ValueError("Unsafe manifest path")
    return root.joinpath(*path.parts)


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--destination",type=Path,default=HERE)
    parser.add_argument("--receipt",type=Path);args=parser.parse_args()
    manifest=json.loads((HERE/"TRANSPORT_MANIFEST.json").read_text());rows=[]
    for entry in manifest["entries"]:
        chunks=[]
        for part in entry["parts"]:
            raw=safe_path(HERE,part["path"]).read_bytes()
            if len(raw)!=part["bytes"] or hashlib.sha256(raw).hexdigest()!=part["sha256"]:
                raise ValueError("Transport part mismatch")
            chunks.append(raw)
        raw=b"".join(chunks)
        if len(raw)!=entry["bytes"] or hashlib.sha256(raw).hexdigest()!=entry["sha256"]:
            raise ValueError("Logical artifact mismatch")
        target=safe_path(args.destination,entry["path"])
        if target.exists():
            if target.read_bytes()!=raw:raise FileExistsError("Existing artifact differs; refusing overwrite")
            status="already_verified"
        else:
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open("xb") as stream:stream.write(raw)
            status="restored"
        rows.append(dict(path=entry["path"],bytes=len(raw),sha256=entry["sha256"],status=status))
    result=dict(logical_artifacts=rows,all_exact=True)
    if args.receipt:
        with args.receipt.open("x") as stream:json.dump(result,stream,sort_keys=True,indent=2);stream.write("\n")
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":main()
