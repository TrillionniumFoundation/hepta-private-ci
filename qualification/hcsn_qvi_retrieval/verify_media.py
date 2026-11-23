"""Check acquisition and actor partition receipts without scoring retrieval outcomes."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def validate(archive, shard_dir):
    rows = json.loads(archive.read_text())
    source = {row["recording"]: row for row in rows}
    erratum = json.loads(Path(__file__).with_name("data_manifest.json").read_text())["source_integrity_erratum"]
    by_hash = {}
    for row in rows:
        by_hash.setdefault(row["sha256"], []).append(row["recording"])
    duplicates = {k: sorted(v) for k,v in by_hash.items() if len(v)>1}
    if len(rows) != 192 or duplicates!={erratum["duplicate_sha256"]:sorted(erratum["duplicate_files"])}:
        raise ValueError("incomplete or duplicate source recordings")
    split_names = ("train","dev","retain","test")
    seen_actors = set()
    seen_clips = set()
    counts = {}
    for split in split_names:
        shard = shard_dir / f"{split}.npz"
        receipt = json.loads(shard.with_suffix(".receipt.json").read_text())
        if hashlib.sha256(shard.read_bytes()).hexdigest() != receipt["output_sha256"]:
            raise ValueError("shard identity mismatch")
        for name, digest in receipt["source_sha256"].items():
            if source[name]["sha256"] != digest or name in seen_clips:
                raise ValueError("source identity mismatch or split overlap")
            seen_clips.add(name)
        with np.load(shard,allow_pickle=False) as data:
            groups = set(data["group"])
            if seen_actors & groups or set(data["split"]) != {split}:
                raise ValueError("actor leakage")
            seen_actors.update(groups)
            quarantined = {tuple(v) for v in erratum["excluded_actor_emotion"]}
            expected = [name for name in receipt["source_sha256"] if
                        (source[name]["actor"], int(name.split("-")[2])) not in quarantined]
            if sorted(data["query_id"].tolist()) != sorted(expected):
                raise ValueError("missing or repeated query")
            for query, gallery, target, actor in zip(data["query_id"],data["gallery_id"],
                                                    data["target"],data["group"]):
                q = query[:-4].split("-")
                candidates = [name[:-4].split("-") for name in gallery]
                if not all(c[:4]==q[:4] and c[5]!=q[5] and c[6]==q[6] for c in candidates):
                    raise ValueError("mismatched actor, emotion, take or intensity")
                if not all(name in receipt["source_sha256"] for name in gallery):
                    raise ValueError("unknown reference recording")
                if {c[4] for c in candidates} != {"01","02"} or candidates[target][4]!=q[4]:
                    raise ValueError("ambiguous or incorrect retrieval label")
                if actor != "ravdess-actor-"+q[6]:
                    raise ValueError("incorrect group")
            counts[split] = [len(groups),len(data["query_id"])]
    if len(seen_actors) != 24 or seen_clips != set(source):
        raise ValueError("incomplete group or recording coverage")
    return {"actors_and_queries":counts, "recordings":len(source), "groups":len(seen_actors),
            "unique_recordings":len(by_hash),"queries":sum(v[1] for v in counts.values()),
            "downloaded_media_bytes":sum(row["bytes"] for row in source.values()),
            "scope":"Receipt identities, split membership and query/gallery construction only."}


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recordings",type=Path)
    parser.add_argument("shard_dir",type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.recordings,args.shard_dir),indent=2))
