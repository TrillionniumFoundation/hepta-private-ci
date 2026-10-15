"""Torch-free numerical replay of archived V6 / future V7.1 Bridge weight bytes.

Only admits the frozen original V6 evidence ZIP and bounded CPU FP32
state_dict pickles with a three-global whitelist. It NEVER evaluates a model,
loads Granite Encoder weights or grants an NDU/CellSplit/effect permission.
This decoder is deliberately independent of the original V6 Torch producer.
"""
from __future__ import annotations

from collections import OrderedDict, Counter
from hashlib import sha256
import io
import json
import math
import os
import stat
from pathlib import Path, PurePosixPath
import pickle
import random
import re
import struct
import zipfile

V6_ZIP_SHA256 = "197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a"
V6_DESIGN_SHA256 = "5880398dd5cc15c59cf592477ef93968c16f513fdde9a98ef6d11af64dcc63e5"
V6_WARMUP_COMPLETION_SHA256 = "2a1a89e0f9f5ff405792fbb2df4ba2511b300903fb7a5696547913f42a48ac1e"
V6_WARMUP_WEIGHTS_SHA256 = {
    41:"15e47d24b3b08f37137e9222fc569001cc2112243b27439fc7b690d13bda62e0",
    47:"8c4b31ac0d632e7a2527cfe053975f18a91ab01fc7aa3e81ea0bb78604cb8602",
    53:"d5e059e57552e70225fe7727f713b61ee58193fd4d71995226a4f7ae07dbca04",
}
SEEDS = (41, 47, 53)
CONTINUATIONS = ("natural_only", "replay", "contrastive")
SHAPES = {
    "project.weight": (32,384), "query.weight": (32,128), "query.bias": (32,),
    "relation.weight": (32,256), "relation.bias": (32,),
    "token_score.weight": (1,32), "token_key.weight": (32,32),
    "fact_score.weight": (1,32), "fact_key.weight": (32,32),
    "state_query.weight": (32,64),
    "proposal.weight": (32,100), "proposal.bias": (32,),
    "update_gate.weight": (32,100), "update_gate.bias": (32,),
    "head.0.weight": (32,97), "head.0.bias": (32,),
    "head.2.weight": (2,32), "head.2.bias": (2,),
    **{f"fact_bridge.{n}.weight":(32,32) for n in ("query","key","value","output")},
}
OWN = re.compile(r"The (.+?) belongs to (.+?)\.\Z")
STORES = re.compile(r"(.+?) stores all their possessions in the (.+?) box\.\Z")
QUESTION = re.compile(r"Where is the (.+?) stored\?\Z")
CANDIDATE = re.compile(r"The (.+?) box\.\Z")


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha_file(path):
    h = sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_regular_file(path, *, maximum=8 * 1024 * 1024):
    """Read one bounded regular file from a single no-follow descriptor.

    The descriptor identity is checked before/after. On systems without
    O_NOFOLLOW, refuse visible symlinks before opening as a weaker fallback.
    A digest authenticates bytes relative to the stated source, not the host.
    """
    path=Path(path)
    require(not path.is_symlink(), "no symlink input permitted")
    flags=os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd=os.open(path, flags)
    try:
        before=os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum,
                "bounded regular original/tensor source required")
        with os.fdopen(fd,"rb",closefd=False) as f:
            data=f.read(maximum+1)
        after=os.fstat(fd)
        require(before.st_dev==after.st_dev and before.st_ino==after.st_ino
                and before.st_size==after.st_size==len(data)
                and before.st_mtime_ns==after.st_mtime_ns and len(data)<=maximum,
                "input changed during one-descriptor read")
        return data
    finally:
        os.close(fd)


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def parse_json(raw):
    return json.loads(raw, object_pairs_hook=unique_pairs,
                      parse_constant=lambda _: require(False, "nonfinite JSON"))


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


class _Storage:
    def __init__(self, key, count):
        self.key, self.count = key, count


class _Tensor:
    def __init__(self, storage, offset, shape):
        self.storage, self.offset, self.shape = storage, offset, shape


class _FloatStorage:
    pass


def decode_fp32_checkpoint(binary, shapes=SHAPES, *, include_tensor_bytes=False):
    """Independently reconstruct Torch's two model digests, without importing torch.

    Refuses arbitrary pickle globals, noncontiguous strides, device storage,
    aliasing/truncation, other dtypes, duplicate entries and non-finite data.
    """
    require(type(include_tensor_bytes) is bool, "boolean tensor-export policy required")
    require(isinstance(binary, bytes) and 0 < len(binary) <= 8*1024*1024,
            "bounded checkpoint bytes required")
    require(len(shapes) == 22 and sum(math.prod(x) for x in shapes.values()) == 42562,
            "exact V6 Bridge Reader tensor schema required")
    require(zipfile.is_zipfile(io.BytesIO(binary)), "Torch checkpoint must be valid ZIP")
    with zipfile.ZipFile(io.BytesIO(binary), "r") as arc:
        entries = arc.infolist()
        paths = [v.filename for v in entries]
        require(3 <= len(entries) <= 512 and len(paths) == len(set(paths))
                and sum(v.file_size for v in entries) <= 16*1024*1024
                and all(not PurePosixPath(n).is_absolute()
                        and ".." not in PurePosixPath(n).parts for n in paths),
                "bounded unique safe checkpoint ZIP members required")
        pickles = [n for n in paths if n.endswith("/data.pkl")]
        require(len(pickles) == 1, "single Torch state_dict pickle required")
        prefix = pickles[0][:-8]
        require(arc.read(prefix+"byteorder") == b"little", "little endian FP32 required")
        storages = {}
        def rebuild(storage, offset, size, stride, requires_grad, hooks, metadata=None):
            require(isinstance(storage, _Storage) and type(offset) is int and offset >= 0
                    and type(size) is tuple and type(stride) is tuple and 1 <= len(size) <= 4
                    and all(type(n) is int and 0 < n <= 8192 for n in size)
                    and requires_grad is False and isinstance(hooks, (OrderedDict,dict))
                    and not hooks and metadata is None,
                    "unregistered Torch tensor reconstruction")
            expected, count = [], 1
            for width in reversed(size):
                expected.append(count)
                count *= width
            require(tuple(reversed(expected)) == stride and offset + count <= storage.count,
                    "noncontiguous or out-of-storage tensor")
            return _Tensor(storage, offset, size)
        class Restricted(pickle.Unpickler):
            def find_class(self, module, name):
                permitted = {("collections", "OrderedDict"):OrderedDict,
                             ("torch", "FloatStorage"):_FloatStorage,
                             ("torch._utils", "_rebuild_tensor_v2"):rebuild}
                require((module, name) in permitted, "forbidden pickle global")
                return permitted[module, name]
            def persistent_load(self, key):
                require(type(key) is tuple and len(key)==5 and key[0]=="storage"
                        and key[1] is _FloatStorage and key[3]=="cpu"
                        and type(key[2]) is str and key[2].isascii()
                        and key[2].isdigit() and len(key[2])<=16
                        and type(key[4]) is int and 0 < key[4] <= 1_000_000,
                        "CPU FP32 storage signature required")
                require(key[2] not in storages or storages[key[2]]==key[4],
                        "duplicate storage id with different byte count")
                storages[key[2]]=key[4]
                return _Storage(key[2],key[4])
        raw=arc.read(pickles[0])
        require(len(raw) <= 1_048_576, "state pickle limit")
        stream=io.BytesIO(raw)
        state=Restricted(stream).load()
        require(stream.tell()==len(raw) and isinstance(state,(OrderedDict,dict))
                and set(state)==set(shapes), "complete known Reader tensors required")
        storage_paths={prefix+"data/"+key for key in storages}
        require({x for x in paths if x.startswith(prefix+"data/")}==storage_paths,
                "extra or missing storage blocks")
        payloads={k:arc.read(prefix+"data/"+k) for k in storages}
        require(all(len(payloads[k])==n*4 for k,n in storages.items()),
                "FP32 storage byte count differs")
        training, execution, n_parameters=sha256(),sha256(),0
        storage_intervals=[]
        tensor_bytes = {} if include_tensor_bytes else None
        for name,tensor in sorted(state.items()):
            require(isinstance(tensor,_Tensor) and tensor.shape==shapes[name],
                    "unregistered tensor dimensions")
            count=math.prod(tensor.shape)
            data=payloads[tensor.storage.key][4*tensor.offset:4*(tensor.offset+count)]
            require(len(data)==4*count and all(math.isfinite(v) for (v,) in struct.iter_unpack("<f", data)),
                    "truncated or nonfinite tensor values")
            storage_intervals.append((tensor.storage.key,tensor.offset,tensor.offset+count))
            if include_tensor_bytes:
                tensor_bytes[name] = data
            header=name.encode()+str(tensor.shape).encode()
            training.update(header+data)
            execution.update(header+b"torch.float32"+data)
            n_parameters+=count
        # Permit multiple views into storage only if nonoverlapping. State_dict
        # copies saved by this experiment use independent contiguous ranges.
        for ix, (key,a,b) in enumerate(storage_intervals):
            require(all(key!=other or b<=c or d<=a
                        for other,c,d in storage_intervals[ix+1:]),
                    "aliased checkpoint tensor storage forbidden")
        require(n_parameters==42562, "registered parameter count required")
        receipt = dict(training_parameter_sha256=training.hexdigest(),
                    execution_parameter_sha256=execution.hexdigest(),
                    parameter_count=n_parameters, tensor_count=len(state),
                    all_values_finite=True, torch_imported=False)
        if include_tensor_bytes:
            # Raw FP32 bytes are a private in-process optional result only. Never
            # put these weights in review JSON, logs or the repository.
            receipt["tensor_bytes"] = tensor_bytes
        return receipt


def _case_id(row):
    return json.dumps([row[k] for k in ("source_split","paragraph_id","question_id","answer_id")],
                      separators=(",", ":"))


def validate_original_plan(plan, original_binding, original_natural, seed):
    """Recompute registered TRAIN schedule from sealed original human+binding rows."""
    require(plan["schema"]=="hepta.binding.continuation-plan.v1"
            and plan["seed"]==seed and plan["updates"]==500 and plan["batch_size"]==16
            and plan["logical_update_order"]==["natural","binding"]
            and plan["plan_sha256"]==_digest({k:v for k,v in plan.items()
                                               if k!="plan_sha256"}),
            "V6 source plan/protocol changed")
    require(len(original_binding)==128 and len(original_natural)==3909,
            "original complete 128/3909 training source roster required")
    for stream, rows in (("binding",original_binding),("natural",original_natural)):
        require(plan[stream+"_case_ids"]==[_case_id(x) for x in rows]
                and plan[stream+"_targets"]==[x["label"] for x in rows]
                and plan[stream+"_source_groups"]==[x["source_hash"] for x in rows],
                "original public source/label/ID mismatch")
        require(all(x["source_split"]=="train" and type(x["label"]) is int
                    and x["label"] in (0,1) for x in rows),
                "unapproved future/label source")
    require(set(x["source_hash"] for x in original_binding).isdisjoint(
            x["source_hash"] for x in original_natural),
            "old/new source overlap")
    for i in range(0,len(original_binding),4):
        quad=original_binding[i:i+4]
        require([x["label"] for x in quad]==[1,0,0,1]
                and [x["answer_id"] for x in quad]==["0","1","0","1"]
                and len({x["question"] for x in quad})==1
                and quad[0]["facts"]==quad[1]["facts"]
                and quad[2]["facts"]==quad[3]["facts"]
                and Counter(" ".join(quad[0]["facts"]).split())==
                    Counter(" ".join(quad[2]["facts"]).split()),
                "incomplete or invalid original opposite-label four-row world")
        for row in quad:
            require(row["segmentation"]=="synthetic-ownership-storage-v1"
                    and row["sentence_ids"]==[1,2,3,4]
                    and sha256("\n".join(row["facts"]).encode()).hexdigest()==row["source_hash"],
                    "source sentence SHA/typed segmentation differs")
            owners,places={},{}
            for fact in row["facts"]:
                o=OWN.fullmatch(fact); p=STORES.fullmatch(fact)
                require(bool(o) != bool(p), "unknown original fact grammar")
                if o:
                    obj,person=o.groups()
                    require(obj not in owners,"duplicate ownership")
                    owners[obj]=person
                else:
                    person,box=p.groups()
                    require(person not in places,"duplicate storage")
                    places[person]=box
            q=QUESTION.fullmatch(row["question"])
            c=CANDIDATE.fullmatch(row["candidate"])
            require(q is not None and c is not None,"registered question/candidate grammar")
            obj=q.group(1)
            require(obj in owners and owners[obj] in places
                    and row["label"]==int(places[owners[obj]]==c.group(1)),
                    "label not derived from original evidence")
    natural_rng=random.Random(f"hepta-binding-natural-v5/{seed}")
    expected_natural=[natural_rng.sample(range(3909),16) for _ in range(500)]
    require(plan["natural_batches"]==expected_natural,
            "old original V6 natural sampler differs")
    rng=random.Random(seed)
    group_order=[]; pos=32; expected_binding=[]
    for _ in range(500):
        if pos==32:
            group_order=list(range(32))
            rng.shuffle(group_order)
            pos=0
        groups=group_order[pos:pos+4]
        expected_binding.append([4*g+j for g in groups for j in range(4)])
        pos+=4
    require(plan["binding_batches"]==expected_binding,
            "original paired-world epoch/group shuffle differs")
    return dict(seed=seed, original_binding_cases=128, original_natural_cases=3909,
                source_disjoint=True, original_train_targets_verified=True,
                independent_schedule_recomputed=True, official_validation_read=False)


def _read_original(archive, path):
    return parse_json(archive.read(path))


def audit_v6_archive(path):
    """Full actual original ZIP bytes, 3 warmups + 9 continuations, without model download."""
    path=Path(path)
    require(path.is_file() and not path.is_symlink()
            and path.stat().st_size <= 40_000_000
            and sha_file(path)==V6_ZIP_SHA256,
            "original SHA-pinned V6 ZIP required")
    with zipfile.ZipFile(path) as arc:
        members=arc.infolist()
        names=[x.filename for x in members]
        require(len(names)==len(set(names))==212 and len(members)<=256
                and sum(x.file_size for x in members)<=190_000_000
                and all(not PurePosixPath(n).is_absolute()
                        and ".." not in PurePosixPath(n).parts for n in names),
                "canonical bounded original V6 evidence entries required")
        manifest=_read_original(arc,"MANIFEST.json")
        entries=manifest["entries"]
        require(set(names)=={"MANIFEST.json"}|{e["path"] for e in entries}
                and len(entries)==211 and manifest["encoder_or_feature_cache_included"] is False
                and manifest["feedback_or_fresh_executed"] is False,
                "actual V6 canonical package role/entry mismatch")
        for e in entries:
            name=e["path"]
            require(e["size_bytes"]==arc.getinfo(name).file_size
                    and e["sha256"]==sha256(arc.read(name)).hexdigest(),
                    "original V6 ZIP entry SHA256/length mismatch")
        design=_read_original(arc,"reader-v6-bridge/design.json")
        warmup=_read_original(arc,"reader-v6-bridge/warmup-completion.json")
        continuation=_read_original(arc,"reader-v6-bridge/continuation-completion.json")
        require(warmup["primary_all_passed"] is True
                and continuation["contrastive_all_passed"] is False
                and continuation["fresh_scoring_authorized"] is False
                and len(design["runtime_source_sha256"])==52,
                "V6 result qualification condition mismatch")
        old=_read_original(arc,"reader-v6-bridge/all-cases.json")["reader_train"]
        natural=_read_original(arc,"reader-v5-independent-audit/natural-cases.json")["train"]
        checkpoints=[];plans=[]
        for seed in SEEDS:
            folder=f"reader-v6-bridge/seed-{seed}/bridge/"
            plan=_read_original(arc, folder+"continuation-plan.json")
            plans.append(validate_original_plan(plan,old,natural,seed))
            for slot in ("warmup", *CONTINUATIONS):
                manifest=_read_original(arc,folder+slot+"-model.json")
                binary=arc.read(folder+slot+".pt")
                result=decode_fp32_checkpoint(binary)
                require(manifest["seed"]==seed and manifest["architecture"]["arm"]=="bridge"
                        and sha256(binary).hexdigest()==manifest["file_sha256"]
                        and all(manifest[name]==result[name] for name in (
                            "training_parameter_sha256","execution_parameter_sha256","parameter_count")),
                        "original pretrained V6 Tensor numerical bytes/manifest mismatch")
                checkpoints.append(dict(seed=seed,arm=slot,checkpoint_sha256=manifest["file_sha256"],
                                        training_parameter_sha256=result["training_parameter_sha256"],
                                        parameter_count=result["parameter_count"],
                                        tensor_count=result["tensor_count"]))
        return dict(schema="hepta.v7.original-v6-byte-replay.v1",status="verified_original_historical",
                    auditor_source_sha256=sha_file(__file__),
                    archive_sha256=V6_ZIP_SHA256, original_entries_verified=len(entries),
                    original_source_panel_verified=len(old), original_natural_train_verified=len(natural),
                    checkpoints=checkpoints,plans=plans,
                    checkpoint_count=len(checkpoints),
                    pretrained_encoder_executed_this_review=False,
                    new_v7_1_gradient_training_executed=False,
                    original_feature_tensor_cache_present=False,
                    future_task_generalization_verified=False,
                    teacher_10t_100t_equivalence_verified=False,
                    production_authorized=False)


def audit_candidate_checkpoints(output, previous_v6, *, strict_original=True):
    """Validate all nine NEW V7.1 full model tensor bytes against saved manifests.

    This is a second, independent tensor check beyond the existing scalar-only
    review, and does not validate semantic efficacy or intermediate Adam states.
    """
    output, previous_v6 = Path(output), Path(previous_v6)
    require(output.is_dir() and previous_v6.is_dir(), "complete external V6/V7 trees required")
    if strict_original:
        require(sha_file(previous_v6/"design.json") == V6_DESIGN_SHA256
                and sha_file(previous_v6/"warmup-completion.json") == V6_WARMUP_COMPLETION_SHA256,
                "original V6 design/warmup SHA-pinned bytes required")
    checked=[]
    for seed in SEEDS:
        base=previous_v6/f"seed-{seed}"/"bridge"
        original=parse_json(read_regular_file(base/"warmup-model.json"))
        warmup_bytes=read_regular_file(base/"warmup.pt")
        if strict_original:
            require(sha256(warmup_bytes).hexdigest() == V6_WARMUP_WEIGHTS_SHA256[seed],
                    "original V6 pretrained Bridge warmup identity must be pinned")
        model=decode_fp32_checkpoint(warmup_bytes)
        require(all(original[k]==model[k] for k in
                    ("training_parameter_sha256","execution_parameter_sha256","parameter_count")),
                "V6 frozen warmup tensor bytes drifted")
        for arm in ("joint","protect_old","protect_old_guarded"):
            folder=output/f"seed-{seed}"/arm
            metadata=parse_json(read_regular_file(folder/"candidate-model.json"))
            receipt=parse_json(read_regular_file(folder/"candidate-training.json",
                                                  maximum=32_000_000))
            weights=read_regular_file(folder/"candidate.pt")
            digest=decode_fp32_checkpoint(weights)
            require(metadata["architecture"]["arm"]=="bridge"
                    and metadata["seed"]==seed
                    and metadata["initial_execution_parameter_sha256"]==original["execution_parameter_sha256"]
                    and receipt["initial_model_sha256"]==original["training_parameter_sha256"]
                    and receipt["final_model_sha256"]==digest["training_parameter_sha256"]
                    and sha256(weights).hexdigest()==metadata["file_sha256"]
                    and all(metadata[k]==digest[k] for k in
                            ("training_parameter_sha256","execution_parameter_sha256","parameter_count")),
                    "candidate actual Torch tensor content differs from model receipt")
            checked.append(dict(seed=seed,arm=arm,parameter_count=digest["parameter_count"],
                                tensor_count=digest["tensor_count"],
                                training_parameter_sha256=digest["training_parameter_sha256"]))
    require(len(checked)==9,"full nine-candidate tensor census required")
    return dict(schema="hepta.v7.candidate-checkpoint-replay.v1",
                auditor_source_sha256=sha_file(__file__),
                model_tensor_checkpoints=checked,model_tensor_count=9,
                independent_trained_weight_tensor_replay=True,
                original_v6_immutable_identity_verified=bool(strict_original),
                pretrained_encoder_forward_executed=False,task_success_verified=False,
                production_authorized=False)


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-v6-zip",type=Path)
    parser.add_argument("--previous-v6",type=Path)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--report",type=Path,required=True)
    args=parser.parse_args()
    if args.report.exists() or args.report.is_symlink():
        raise ValueError("report must be create-only")
    if args.original_v6_zip is None and (args.previous_v6 is None or args.output is None):
        raise ValueError("original-v6-zip or complete V7.1 candidate paths required")
    result=(audit_v6_archive(args.original_v6_zip) if args.original_v6_zip is not None
            else audit_candidate_checkpoints(args.output,args.previous_v6))
    with args.report.open("x",encoding="utf-8") as f:
        json.dump(result,f,sort_keys=True,indent=2,allow_nan=False)
        f.write("\n")
    print(json.dumps({"schema":result["schema"],"status":result.get("status","descriptive"),
                      "checkpoint_count":result.get("checkpoint_count",result.get("model_tensor_count"))},sort_keys=True))


if __name__=="__main__":
    main()
