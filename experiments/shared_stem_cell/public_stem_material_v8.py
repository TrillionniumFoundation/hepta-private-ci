"""Research-only public model acquisition and *physical* frozen-encoder canary.

`prepare` freezes the Hub's exact commit and enumerated files before any weight
transfer. `run` revalidates metadata at that immutable revision, downloads only
listed files, hashes their bytes and executes execution.LocalEncoder. No fallback,
automatic candidate choice, trained-head efficacy or independent provenance.
Weights stay local; only provenance/diagnostic summaries may be published.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import shutil
import sys
import tempfile
import time

SCHEMA = "hepta.public-stem-material-plan.v8"
RECEIPT = "hepta.public-stem-material-physical-receipt.v8"
PROBE_TEXTS = ("Birds migrate during winter.", "冬季有些鸟类迁徙。")

def probe_input_digest(texts: tuple[str, ...]) -> str:
    if (type(texts) is not tuple or not 1 <= len(texts) <= 32
            or any(type(t) is not str or not t or len(t.encode("utf-8")) > 8192 for t in texts)):
        raise AdmissionError("invalid fixed probe input census")
    return sha(canonical(["hepta.public-stem-probe-input.v9", list(texts)]))

SHA40 = re.compile(r"[a-f0-9]{40}\Z")
SHA64 = re.compile(r"[a-f0-9]{64}\Z")
WEIGHT = re.compile(r"model(?:-[0-9]{5}-of-[0-9]{5})?\.safetensors\Z")
ALLOWED_META = frozenset({
    "config.json", "tokenizer.json", "tokenizer_config.json",
    "special_tokens_map.json", "added_tokens.json", "model.safetensors.index.json",
    "tokenizer.model", "sentencepiece.bpe.model", "vocab.json", "merges.txt",
})
REQUIRED_META = frozenset({"config.json", "tokenizer.json", "tokenizer_config.json"})
MAX_BYTES = 2 * 1024**3
MAX_FILES = 32
MAX_ONE_FILE = 1200 * 1024**2
# Research-only provenance: both releases are immutable, not moving main.
# mmBERT's current main advertises only a pickle .bin, which this loader
# intentionally rejects. This published historical commit has safetensors.
# Granite's revision was physically executed in hosted run 38579723204.
PINNED_RELEASES = {
    "mmbert-small": "0eb3d056ec1d6333cf4e19b0966dfde342a41a3a",
    "granite-97m-r2": "835ad14087e140460703cf0fae09f97d469d65c2",
}
CATALOG = {
    "mmbert-small": {
        "repo_id": "jhu-clsp/mmBERT-small", "kind": "masked_lm",
        "pooling": "attention-mask-mean", "normalization": "none",
        "width": 384, "max_tokens": 256, "batch_size": 2,
    },
    "granite-97m-r2": {
        "repo_id": "ibm-granite/granite-embedding-97m-multilingual-r2",
        "kind": "encoder", "pooling": "cls-first-token",
        "normalization": "unit_l2", "width": 384,
        "max_tokens": 256, "batch_size": 2,
    },
}


class AdmissionError(ValueError):
    pass


def canonical(obj: object) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require(condition: bool, why: str):
    if not condition:
        raise AdmissionError(why)


def _selected(name: str) -> bool:
    return type(name) is str and (name in ALLOWED_META or bool(WEIGHT.fullmatch(name)))


def _metadata_files(info) -> list[dict]:
    """No bytes may be transferred before this finite inventory is fixed."""
    all_names = [getattr(row, "rfilename", None) for row in info.siblings]
    _require(len(all_names) == len(set(all_names)), "duplicate Hub entries")
    selected = {}
    for sibling in info.siblings:
        name = getattr(sibling, "rfilename", None)
        if not _selected(name):
            continue
        _require("/" not in name and "\\" not in name and ".." not in name,
                 "unsafe material filename")
        size = getattr(sibling, "size", None)
        _require(type(size) is int and 0 < size <= MAX_ONE_FILE,
                 "unmeasured or oversized remote file")
        lfs = getattr(sibling, "lfs", None)
        lfsha = lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None)
        if lfsha is not None:
            _require(type(lfsha) is str and SHA64.fullmatch(lfsha) is not None,
                     "invalid Hub LFS content identity")
        selected[name] = {"size": size, "hub_lfs_sha256": lfsha}
    _require(REQUIRED_META <= selected.keys(), "missing encoder/tokenizer essentials")
    weights = [n for n in selected if WEIGHT.fullmatch(n)]
    _require(weights and len(weights) <= 16, "missing or unbounded safe model weights")
    _require(not ("model.safetensors" in weights and len(weights) > 1),
             "mixed direct and sharded weights")
    if any(n.startswith("model-") for n in weights):
        _require("model.safetensors.index.json" in selected,
                 "sharded weights require manifest index")
        totals = {int(n.rsplit("-of-", 1)[1][:5]) for n in weights}
        _require(totals == {len(weights)} and set(weights) == {
            f"model-{i:05d}-of-{len(weights):05d}.safetensors"
            for i in range(1, len(weights)+1)
        }, "missing model shard or inconsistent shard index")
    _require(len(selected) <= MAX_FILES and sum(x["size"] for x in selected.values()) <= MAX_BYTES,
             "over-limit pinned material")
    return [{"name": n, **selected[n]} for n in sorted(selected)]


def make_plan(candidate: str, model_info) -> dict:
    _require(candidate in CATALOG, "not a registered research stem candidate")
    declaration = CATALOG[candidate]
    revision = getattr(model_info, "sha", None)
    _require(type(revision) is str and SHA40.fullmatch(revision) is not None,
             "Hub did not resolve immutable full commit")
    _require(getattr(model_info, "id", None) == declaration["repo_id"],
             "Hub model identity does not match fixed research catalog")
    return {"schema": SCHEMA, "candidate": candidate,
            "repo_id": declaration["repo_id"], "revision": revision,
            "profile": {k: v for k, v in declaration.items() if k != "repo_id"},
            "files": _metadata_files(model_info),
            "source_authority": "untrusted_public_hub_metadata_no_publisher_attestation",
            "production_accepted": False}


def plan_from_reviewed_release(candidate: str, model_info) -> dict:
    """Reject moving Hub main, unreviewed SHAs and unsafe .bin-only releases.

    Unit fixtures can still use make_plan for synthetic source-inventory tests;
    the real hosted prepare CLI must use this reviewed immutable source map.
    """
    _require(candidate in PINNED_RELEASES, "unknown reviewed public Stem")
    _require(getattr(model_info, "sha", None) == PINNED_RELEASES[candidate],
             "Hub revision differs from registered immutable public release")
    return make_plan(candidate, model_info)


def validate_plan(plan: object) -> dict:
    _require(type(plan) is dict and set(plan) == {
        "schema", "candidate", "repo_id", "revision", "profile", "files",
        "source_authority", "production_accepted"} and plan.get("schema") == SCHEMA,
        "invalid exact material plan schema")
    _require(plan["candidate"] in CATALOG and
             plan["repo_id"] == CATALOG[plan["candidate"]]["repo_id"] and
             plan["profile"] == {k:v for k,v in CATALOG[plan["candidate"]].items() if k!="repo_id"},
             "candidate's model or pooling identity changed")
    _require(type(plan["revision"]) is str and SHA40.fullmatch(plan["revision"]),
             "unversioned Hub revision is forbidden")
    _require(plan["source_authority"] == "untrusted_public_hub_metadata_no_publisher_attestation"
             and plan["production_accepted"] is False,
             "source plan cannot grant producer/promotion authority")
    _require(type(plan["files"]) is list and 0 < len(plan["files"]) <= MAX_FILES,
             "invalid material file inventory")
    names = []
    total = 0
    for part in plan["files"]:
        _require(type(part) is dict and set(part) == {"name", "size", "hub_lfs_sha256"},
                 "unknown or missing manifest field")
        name = part["name"]
        _require(_selected(name) and "/" not in name and "\\" not in name and ".." not in name,
                 "unapproved material path")
        names.append(name)
        sz = part["size"]
        _require(type(sz) is int and 0 < sz <= MAX_ONE_FILE, "unsafe pinned material size")
        total += sz
        digest = part["hub_lfs_sha256"]
        _require(digest is None or (type(digest) is str and SHA64.fullmatch(digest)),
                 "invalid pinned file hash")
    _require(names == sorted(set(names)) and total <= MAX_BYTES,
             "duplicate, noncanonical or excessive material inventory")
    _require(REQUIRED_META <= set(names), "essential model/tokenizer source absent")
    weights = [n for n in names if WEIGHT.fullmatch(n)]
    _require(0 < len(weights) <= 16, "missing or unbounded safe model weights")
    direct = "model.safetensors" in weights
    sharded = any(n.startswith("model-") for n in weights)
    _require(not (direct and sharded), "mixed direct and sharded weights")
    if sharded:
        expected = {f"model-{i:05d}-of-{len(weights):05d}.safetensors"
                    for i in range(1, len(weights) + 1)}
        _require(set(weights) == expected and "model.safetensors.index.json" in names,
                 "incomplete or inconsistent sharded model plan")
    else:
        _require(direct and "model.safetensors.index.json" not in names,
                 "inconsistent unsharded model plan")
    return plan


def require_reviewed_run_plan(plan: dict) -> dict:
    """Keep direct 'run --plan' as restricted as the immutable prepare phase.

    The plan's original file hashes and inventory are checked later against
    the exact same Hub commit. This gate only prevents a pre-written,
    otherwise valid plan from bypassing the research release allowlist.
    """
    validate_plan(plan)
    candidate = plan["candidate"]
    _require(candidate in PINNED_RELEASES
             and plan["revision"] == PINNED_RELEASES[candidate],
             "run plan is not the reviewed immutable public release")
    return plan


def strict_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise AdmissionError("missing or oversized plan")
    def pairs(p):
        out = {}
        for k,v in p:
            if k in out:
                raise AdmissionError("duplicate plan JSON key")
            out[k] = v
        return out
    with path.open("rb") as f:
        obj = json.loads(f.read(), object_pairs_hook=pairs,
                         parse_constant=lambda _:( _require(False,"nonfinite plan")))
    validate_plan(obj)
    _require(path.read_bytes() == canonical(obj), "plan is not canonical")
    return obj


def verify_hub_against_plan(plan: dict, remote_info) -> None:
    validate_plan(plan)
    current = make_plan(plan["candidate"], remote_info)
    _require(current == plan, "pinned remote revision or inventory changed")


def acquire(plan: dict, target: Path, *, model_info, downloader) -> dict:
    """Dependency-injected only so contracts can test invalid transfers offline."""
    verify_hub_against_plan(plan, model_info)
    _require(not target.exists() and not target.is_symlink() and
             target.parent.is_dir() and not target.parent.is_symlink(),
             "output must be a new directory with a safe parent")
    observed = {}
    with tempfile.TemporaryDirectory(prefix=".hepta-public-stem-", dir=target.parent) as tmp:
        stage = Path(tmp)
        for item in plan["files"]:
            name = item["name"]
            downloaded = Path(downloader(plan["repo_id"], name, plan["revision"]))
            _require(downloaded.is_file(), "Hub download missing")
            result = stage / name
            measured = 0
            h = hashlib.sha256()
            with downloaded.open("rb") as source, result.open("xb") as destination:
                for buf in iter(lambda: source.read(1024 * 1024), b""):
                    measured += len(buf)
                    _require(measured <= item["size"], "Hub material exceeds pinned size")
                    h.update(buf)
                    destination.write(buf)
                destination.flush()
                os.fsync(destination.fileno())
            _require(measured == item["size"], "Hub material byte count changed")
            digest = h.hexdigest()
            _require(item["hub_lfs_sha256"] is None or item["hub_lfs_sha256"] == digest,
                     "Hub file SHA-256 disagrees with previously declared LFS SHA")
            observed[name] = digest
        if "model.safetensors.index.json" in observed:
            # Verify the downloaded JSON declares precisely the pinned shard set.
            # Counting filenames alone does not prove the index references them.
            def unique_fields(pairs):
                found = {}
                for key, value in pairs:
                    _require(key not in found, "duplicate sharded index key")
                    found[key] = value
                return found
            try:
                index = json.loads((stage / "model.safetensors.index.json").read_bytes(),
                                   object_pairs_hook=unique_fields,
                                   parse_constant=lambda _: _require(False,"nonfinite index"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise AdmissionError("malformed safetensors shard index") from exc
            _require(type(index) is dict and type(index.get("weight_map")) is dict
                     and bool(index["weight_map"]), "missing safetensors shard weight_map")
            used = set()
            for tensor, filename in index["weight_map"].items():
                _require(type(tensor) is str and bool(tensor)
                         and type(filename) is str and bool(WEIGHT.fullmatch(filename)),
                         "unsafe tensor or shard reference")
                used.add(filename)
            declared = {name for name in observed if WEIGHT.fullmatch(name)}
            _require(used == declared, "shard index does not cover exact physical shards")
        shutil.move(tmp, target)
    return {"revision":plan["revision"], "file_sha256s":observed,
            "manifest": {"revision":plan["revision"],"kind":plan["profile"]["kind"],
                         "files":observed}}


def physical_probe(plan: dict, root: Path, material: dict) -> dict:
    """Not called by the offline unit tests; requires installed Transformers + real weights."""
    import torch
    from execution import LocalEncoder
    validate_plan(plan)
    _require(material["revision"] == plan["revision"], "source revision mismatch")
    torch.set_num_threads(2)
    started, cpu_start = time.perf_counter_ns(), time.process_time_ns()
    model = LocalEncoder(root, material["manifest"], maximum_tokens=plan["profile"]["max_tokens"])
    p = plan["profile"]
    phrases = list(PROBE_TEXTS)
    with torch.inference_mode():
        def encode():
            z = model.encode(phrases, pooling=p["pooling"])
            if p["normalization"] == "unit_l2":
                norms = torch.linalg.vector_norm(z, dim=1, keepdim=True)
                _require(bool((norms > 0).all()) and bool(torch.isfinite(norms).all()),
                         "zero/nonfinite embedding is forbidden")
                z = z / norms
            _require(z.ndim == 2 and tuple(z.shape) == (2,p["width"])
                     and z.dtype == torch.float32 and z.device.type == "cpu"
                     and bool(torch.isfinite(z).all()), "model feature contract mismatch")
            return z
        first = encode()
        second = encode()
    _require(model.forward_calls == 2 and torch.equal(first,second),
             "physical forward count or repeated-feature nondeterminism")
    _require(not torch.equal(first[0],first[1]),"distinct inputs produced identical vectors")
    if p["normalization"] == "unit_l2":
        _require(torch.allclose(torch.linalg.vector_norm(first,dim=1), torch.ones(2), atol=1e-5),
                 "missing model-native L2 normalization")
    model.close()  # Re-read all pinned weights/tokenizer bytes after both forwards.
    wall_ns = time.perf_counter_ns() - started
    cpu_ns = time.process_time_ns() - cpu_start
    return {"schema": RECEIPT,"candidate":plan["candidate"],"repo_id":plan["repo_id"],
            "revision":plan["revision"],"snapshot_digest":model.identity,
            "plan_sha256":sha(canonical(plan)),
            "probe_input_sha256":probe_input_digest(PROBE_TEXTS),
            "probe_count":len(PROBE_TEXTS),"pooling":p["pooling"],
            "normalization":p["normalization"], "feature_width":p["width"],
            "feature_sha256":sha(first.detach().contiguous().numpy().tobytes()),
            "forward_calls":model.forward_calls,"wall_ns":wall_ns,"cpu_ns":cpu_ns,
            "process_lifetime_peak_rss_bytes":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "pretrained_source_independently_attested":False,
            "matched_pair_completed":False,"heldout_efficacy_evaluated":False,
            "production_accepted":False,"authority":"DENY_ALL"}


def _write_new(path: Path, payload: object):
    with path.open("xb") as f:
        f.write(canonical(payload))
        f.flush()
        os.fsync(f.fileno())


def _hub_info(api, repo_id, revision):
    return api.model_info(repo_id, revision=revision, files_metadata=True)


def main(args=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="phase",required=True)
    p=sub.add_parser("prepare")
    p.add_argument("--candidate",choices=tuple(CATALOG),required=True)
    p.add_argument("--out",type=Path,required=True)
    p=sub.add_parser("run")
    p.add_argument("--plan",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    opts=parser.parse_args(args)
    try:
        from huggingface_hub import HfApi, hf_hub_download
        api=HfApi(token=False)
        if opts.phase=="prepare":
            release = PINNED_RELEASES[opts.candidate]
            model_info=_hub_info(api,CATALOG[opts.candidate]["repo_id"],release)
            plan=plan_from_reviewed_release(opts.candidate,model_info)
            _write_new(opts.out,plan) # Must persist immutable revision BEFORE transfer.
            print(f"PINNED_NO_WEIGHTS_TRANSFERRED {plan['repo_id']}@{plan['revision']}")
            return 0
        plan=require_reviewed_run_plan(strict_json(opts.plan))
        _require(not opts.output.exists() and opts.output.parent.is_dir(),"new output required")
        opts.output.mkdir()
        _write_new(opts.output/"pinned-plan.json",plan)
        try:
            info=_hub_info(api,plan["repo_id"],plan["revision"])
            material=acquire(plan,opts.output/"model",model_info=info,
                             downloader=lambda repo,name,rev:hf_hub_download(
                                 repo_id=repo,filename=name,revision=rev,token=False))
            _write_new(opts.output/"material-receipt.json",material)
            measured=physical_probe(plan,opts.output/"model",material)
            _write_new(opts.output/"physical-receipt.json",measured)
            print("PUBLIC_STEM_PHYSICAL_FORWARD_SUCCEEDED_NO_EFFICACY_OR_AUTHORITY",opts.output)
            return 0
        except Exception as exc:
            _write_new(opts.output/"failure.json",{
                "status":"RESEARCH_CANDIDATE_FAILED","exception":type(exc).__name__,
                "reason":str(exc)[:512],"production_accepted":False})
            raise
    except Exception as exc:
        print(f"V8 public stem rejected: {type(exc).__name__}: {str(exc)[:300]}",file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
