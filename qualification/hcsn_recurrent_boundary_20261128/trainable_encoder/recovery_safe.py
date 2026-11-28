"""Capture any original observation left between a write and its progress transaction."""
import hashlib
import json
import os
from pathlib import Path
import time


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f,"sha256").hexdigest()


def pre_resume(root,out):
    evidence=root/"before-restart"
    objects=evidence/"objects"
    objects.mkdir(parents=True,exist_ok=True)
    stamp=time.time_ns()
    recorded={}
    orphans={}
    for folder in sorted(out.iterdir()):
        if not folder.is_dir():
            continue
        progress=folder/"progress.json"
        known=set()
        if progress.exists():
            for row in json.loads(progress.read_bytes())["history"].values():
                known.update((row["file"],row["score_file"]))
        paths=set(folder.glob("step*.pt"))|set(folder.glob("step*-*.npz"))
        paths.update(p for p in (progress,folder/"resume.pt") if p.is_file())
        for path in sorted(paths):
            digest=sha(path)
            dest=objects/digest
            try:os.link(path,dest)
            except FileExistsError:pass
            if sha(dest)!=digest:raise ValueError("pre-restart snapshot inconsistent")
            key=str(path.relative_to(out))
            recorded[key]=digest
            if path.name.startswith("step") and path.name not in known and not (out/"terminal.json").exists():
                orphans[key]=digest
    info=dict(time_unix_ns=stamp,files=recorded,unbound_observations=orphans,
              attribution="Original clock endpoint unknown for any orphan without a contemporaneous registration.")
    with (evidence/f"before-{stamp}.json").open("x") as f:
        json.dump(info,f,indent=2)
