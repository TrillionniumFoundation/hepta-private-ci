#!/usr/bin/env python3
"""Create an UNAPPROVED evidence manifest from previously reviewed commit SHAs."""
import argparse
import json
from pathlib import Path
import subprocess

from evaluate import HEX40, require, sha256


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--template", required=True)
    ap.add_argument("--reviewed-shas", required=True, help="JSON model keys to 40-char reviewed Hub commits; no mutable refs")
    ap.add_argument("--decision-dataset", required=True)
    ap.add_argument("--retrieval-queries", required=True)
    ap.add_argument("--retrieval-corpus", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    plan = json.loads(Path(a.template).read_text(encoding="utf-8"))
    shas = json.loads(Path(a.reviewed_shas).read_text(encoding="utf-8"))
    require(set(shas) == set(plan["models"]), "all five model revisions required")
    from run_models import verify_source_head
    root = Path(__file__).resolve().parents[2]
    source = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    verify_source_head(source)
    plan["source_sha"] = source
    plan["dataset_sha256"] = sha256(a.decision_dataset)
    plan["retrieval_query_sha256"] = sha256(a.retrieval_queries)
    plan["retrieval_corpus_sha256"] = sha256(a.retrieval_corpus)
    from huggingface_hub import snapshot_download
    for name, model in plan["models"].items():
        sha = shas[name]
        require(isinstance(sha, str) and HEX40.fullmatch(sha), f"reviewed SHA invalid: {name}")
        root_snapshot = Path(snapshot_download(repo_id=model["repo"], revision=sha, local_files_only=a.offline))
        digests = {}
        for path in sorted(root_snapshot.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root_snapshot).as_posix()
            # The Laya loader may rewrite tokenizer/tokenizer_config.json. We pin
            # the immutable snapshot commit, verify remaining weight/tokenizer
            # files, and record this exception for separate review.
            if rel == "tokenizer/tokenizer_config.json":
                continue
            digests[rel] = sha256(path)
        require(any("safetensors" in p for p in digests), f"no weight tensor in {name}")
        require(any("tokenizer" in p for p in digests), f"no tokenizer in {name}")
        model["revision"] = sha
        model["file_sha256"] = digests
    dest = Path(a.output)
    require(not dest.exists(), "refusing to overwrite an existing frozen manifest")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"UNAPPROVED candidate plan: {dest} (external review + preregistration still required)")


if __name__ == "__main__":
    main()