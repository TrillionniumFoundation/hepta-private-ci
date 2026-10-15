"""Rehydrate an original V6 Bridge cohort on a different machine, without path spoofing.

V6 stored historical absolute workspace paths. Never rewrite its signed/pinned
byte graph to impersonate the original run. Admit only original ZIPs and genuine
externally supplied pinned Granite material. Reencoding becomes a NEW V7.4
experiment, even when the frozen V6 model and source rows are identical.

No permission to activate a Cell or modify current production state is granted.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import time
import zipfile

V4_SHA = "4fcfaa5a266fa3779b4c8af361570d959ea9f5880efb99fe99787bff81b6922c"
V5_SHA = "0f3ef2cd1f80d4c8bf65b6da70c56ea8513d5a933db8c02e7db21a91ff168191"
V6_SHA = "197a5c68eb892970e6a7c7da4030fd2f468a3bf78a5cedfaf4c2667d3e54c58a"
ZIPS = {"v4": V4_SHA, "v5": V5_SHA, "v6": V6_SHA}
SEEDS = (41, 47, 53)
ARMS = ("joint", "protect_old", "protect_old_guarded")
MODEL_ID = "ibm-granite/granite-embedding-97m-multilingual-r2"
REVISION = "835ad14087e140460703cf0fae09f97d469d65c2"
SCHEMA = "hepta.bridge.portable-v74.original-source-new-run.shadow.v1"
MAX_ARCHIVE_FILE = 64 * 1024 * 1024
MAX_TEXT = 16 * 1024 * 1024


def require(ok, why):
    if not ok:
        raise ValueError(why)


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


def sha(data):
    return sha256(data).hexdigest()


def file_sha(path, max_size=100_000_000):
    path = Path(path)
    require(not path.is_symlink(), "symlinked source refused")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as handle:
        st = os.fstat(handle.fileno())
        require(stat.S_ISREG(st.st_mode) and 0 < st.st_size <= max_size,
                "bounded regular source file required")
        digest = sha256()
        for part in iter(lambda: handle.read(1 << 20), b""):
            digest.update(part)
        after = os.fstat(handle.fileno())
        require((st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
                "source mutated during byte verification")
        return digest.hexdigest()


def source_id(row):
    return json.dumps([row[k] for k in ("source_split", "paragraph_id", "question_id", "answer_id")],
                      separators=(",", ":"), ensure_ascii=False)


def _unpack_rows(rows, expected, name):
    require(type(rows) is list and len(rows) == expected, name + ": source row count changed")
    ids = [source_id(r) for r in rows]
    require(len(set(ids)) == expected, name + ": duplicate source case ID")
    for row in rows:
        require(type(row) is dict and set(row) == {"answer_id", "candidate", "evidence_sentence_indices",
                 "facts", "label", "paragraph_id", "question", "question_id", "segmentation",
                 "sentence_ids", "source_hash", "source_split"}, "unregistered case fields")
        require(type(row["label"]) is int and row["label"] in (0, 1)
                and type(row["source_hash"]) is str and len(row["source_hash"]) == 64
                and type(row["facts"]) is list and bool(row["facts"])
                and all(type(v) is str and bool(v) for v in row["facts"]),
                "source/label/public fact form required")
    return ids


def _checked_archive(path, wanted, *, size_limit=150_000_000, return_bytes=False):
    """Hash and inspect a held FD snapshot, never reopen a potentially swapped path."""
    path = Path(path)
    require(not path.is_symlink(), "archive symlink refused")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        st = os.fstat(stream.fileno())
        require(stat.S_ISREG(st.st_mode) and 0 < st.st_size <= size_limit,
                "bounded regular archive required")
        blob = stream.read(size_limit+1)
        end = os.fstat(stream.fileno())
        require(len(blob) == st.st_size and
                (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) ==
                (end.st_dev, end.st_ino, end.st_size, end.st_mtime_ns),
                "archive changed during read")
    require(sha(blob) == wanted, "immutable full original archive SHA changed")
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = z.namelist()
        require(names and len(names) <= 1000 and len(set(names)) == len(names),
                "bounded unique ZIP member paths required")
        require(sum(i.file_size for i in z.infolist()) <= 800_000_000,
                "unbounded source ZIP expansion")
        for info in z.infolist():
            components = PurePosixPath(info.filename).parts
            require(components and not info.filename.startswith("/") and ".." not in components
                    and info.file_size <= MAX_ARCHIVE_FILE and not info.is_dir()
                    and not ((info.external_attr >> 16) & 0o170000) == 0o120000,
                    "invalid unsafe ZIP member")
        if wanted == V6_SHA:
            manifest=_zjson(z,"MANIFEST.json")
            entries=manifest["entries"]
            require(len(entries)+1 == len(names) and {x["path"] for x in entries} == set(names)-{"MANIFEST.json"},
                    "complete original V6 ZIP member inventory required")
            for item in entries:
                payload=z.read(item["path"])
                require(len(payload)==item["size_bytes"] and sha(payload)==item["sha256"],
                        "V6 member original hash/size changed")
        meta={"sha256":wanted, "member_count":len(names),
              "uncompressed_bytes":sum(i.file_size for i in z.infolist()),
              "fully_byte_verified":True,"v6_manifest_entries_verified":len(entries) if wanted==V6_SHA else None}
        return (meta,blob) if return_bytes else meta


def _zjson(archive, member):
    require(member in archive.namelist(), "missing original archive member: " + member)
    b = archive.read(member)
    require(0 < len(b) <= MAX_TEXT, "bounded JSON source length required")
    return json.loads(b, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
                      object_pairs_hook=_no_dups)


def _no_dups(pairs):
    d = {}
    for k, v in pairs:
        require(k not in d, "duplicate JSON property rejected")
        d[k] = v
    return d


def originals(v4, v5, v6):
    """Read only byte-fixed provenance and original TRAIN rows. No model calls."""
    inputs = {"v4": v4, "v5": v5, "v6": v6}
    snapshots={key:_checked_archive(inputs[key],ZIPS[key],return_bytes=True) for key in inputs}
    receipts={key:snapshots[key][0] for key in inputs}
    with zipfile.ZipFile(io.BytesIO(snapshots["v4"][1])) as a, \
         zipfile.ZipFile(io.BytesIO(snapshots["v5"][1])) as b, \
         zipfile.ZipFile(io.BytesIO(snapshots["v6"][1])) as c:
        prev_v4 = a.read("reader-v4-main/design.json")
        prev_v5 = b.read("experiment/design.json")
        copy_v5 = c.read("reader-v5-binding/design.json")
        require(prev_v5 == copy_v5, "V6 bundled V5 design differs from original V5 archive")
        design = _zjson(c, "reader-v6-bridge/design.json")
        source = _zjson(c, "reader-v6-bridge/all-cases.json")
        natural = _zjson(c, "reader-v5-independent-audit/natural-cases.json")
        gate = _zjson(c, "reader-v6-bridge/warmup-completion.json")
        source_v4 = _zjson(a, "reader-v4-prepared/encoder.json")
        design_v5 = _zjson(b, "experiment/design.json")
        require(design["membership"]["source_files_sha256"]["v4-design"] == sha(prev_v4),
                "original V4 ancestry does not match immutable V6")
        require(design["previous_v5_design_sha256"] == sha(prev_v5),
                "original V5 design SHA changed")
        require(design["schema"] == "hepta.bridge.campaign.v6"
                and gate["primary_all_passed"] is True
                and gate["fresh_scoring_authorized"] is False
                and design["production_authorized"] is False,
                "qualified V6 old baseline only")
        require(set(source) == {"reader_train", "internal_tune", "fresh_combinations",
                   "fresh_vocabulary", "verifier_fit"}, "V6 partition roster changed")
        require(set(natural) == {"train", "tune"}, "original natural data scope changed")
        old_ids = _unpack_rows(source["reader_train"], 128, "binding TRAIN")
        _unpack_rows(source["internal_tune"], 64, "binding tune")
        new_ids = _unpack_rows(natural["train"], 3909, "natural TRAIN")
        _unpack_rows(natural["tune"], 827, "natural tune")
        require(design["natural_case_ids"]["train"] == new_ids and
                design["natural_case_ids"]["tune"] == [source_id(r) for r in natural["tune"]],
                "original natural source ordering drift")
        require(set(r["source_hash"] for r in natural["train"]).isdisjoint(
                r["source_hash"] for r in source["reader_train"]),
                "natural/binding source overlap")
        model = source_v4["model_material"]
        require(model["model_id"] == MODEL_ID and model["revision"] == REVISION
                and set(model["files"]) == set(model["sha256"]),
                "wrong original Granite model revision")
        warmup = {}
        plans = {}
        for seed in SEEDS:
            path = f"reader-v6-bridge/seed-{seed}/bridge/"
            m = _zjson(c, path + "warmup-model.json")
            original_bytes = c.read(path + "warmup.pt")
            require(sha(original_bytes) == m["file_sha256"] and
                    m["architecture"]["arm"] == "bridge" and
                    m["parameter_count"] == 42562 and m["seed"] == seed and
                    m["execution_parameter_sha256"] == gate["gates"][str(seed)]["bridge"].get("model_sha256", m["execution_parameter_sha256"]),
                    "wrong authentic V6 warmup weight/seed")
            warmup[seed] = {"model_file_sha256":sha(original_bytes),
                             "execution_parameter_sha256":m["execution_parameter_sha256"],
                             "training_parameter_sha256":m["training_parameter_sha256"]}
            plan = _zjson(c, path + "continuation-plan.json")
            require(plan["seed"] == seed and plan["updates"] == 500 and
                    plan["binding_case_ids"] == old_ids and plan["natural_case_ids"] == new_ids and
                    len(plan["binding_batches"]) == len(plan["natural_batches"]) == 500 and
                    plan["plan_sha256"] == sha(canonical({k:v for k,v in plan.items() if k != "plan_sha256"})),
                    "original sample plan/identity changed")
            plans[seed] = plan
        receipts["v4_design_sha256"] = sha(prev_v4)
        receipts["v5_design_sha256"] = sha(prev_v5)
        receipts["v6_design_sha256"] = sha(c.read("reader-v6-bridge/design.json"))
        receipts["binding_train_ids_sha256"] = sha(canonical(old_ids))
        receipts["natural_train_ids_sha256"] = sha(canonical(new_ids))
        return {"archive":receipts, "source":source, "natural":natural,
                "model":model, "warmup":warmup, "plans":plans,
                "v5_cache_sha256":design_v5["prepared_cache_files_sha256"],
                "original_preprocess_sha256":source_v4["preprocess_sha256"],
                "original_feature_set_sha256":source_v4["feature_set_sha256"],
                "design":design}


def material_preflight(snapshot, model):
    """Actual file checks; model absent is BLOCKED, never a virtual model."""
    snapshot = Path(snapshot)
    missing, present = [], {}
    expected = model["files"]
    for name in sorted(expected):
        path = snapshot / name
        if not path.is_file() or path.is_symlink():
            missing.append(name)
            continue
        if path.stat().st_size != expected[name] or file_sha(path, 512_000_000) != model["sha256"][name]:
            raise ValueError("pinned actual Granite file differs: " + name)
        present[name] = dict(size=expected[name], sha256=model["sha256"][name])
    material = snapshot / "material.json"
    if material.is_file():
        require(not material.is_symlink(), "material provenance symlink refused")
        manifest = json.loads(material.read_text())
        require(manifest == model, "local material.json is not the original V4 model identity")
    else:
        missing.append("material.json")
    return dict(ready=not missing, missing=missing, checked=present,
                registered_model_revision=model["revision"],
                issuer_signature_verified=False, production_authorized=False)


def cache_preflight(cache, original_cache_sha):
    """Cache bytes may be reused only if exact original V5 SHA matches."""
    cache = Path(cache)
    expected = {"metadata.json", "tokens.pt"}
    require(set(original_cache_sha) == expected, "unregistered historical cache file list")
    missing=[]
    for name in sorted(expected):
        path=cache/name
        if not path.is_file() or path.is_symlink():
            missing.append(name)
            continue
        require(file_sha(path, 2_000_000_000) == original_cache_sha[name],
                "provided TokenBank differs from original V5 pinned cache: " + name)
    return dict(exact=not missing, missing=missing, original_historical_cache_verified=not missing,
                regenerated_cache_same_as_historical=False)


def preflight(v4,v5,v6, snapshot, cache=None, *, original_data=None):
    data = originals(v4,v5,v6) if original_data is None else original_data
    model = material_preflight(snapshot, data["model"])
    previous = cache_preflight(cache, data["v5_cache_sha256"]) if cache else None
    return dict(schema=SCHEMA, status="READY_TO_EXECUTE" if model["ready"] else "BLOCKED_MODEL_MATERIAL",
                old_pretrained_encoder_present=model["ready"], archive=data["archive"],
                input_case_counts=dict(binding_train=128, natural_train=3909, natural_tune=827),
                original_seed_warmup_models={str(k):v for k,v in data["warmup"].items()},
                material=model, cache=previous,
                experiment_identity="new_source_locked_reencoding" if not previous or not previous["exact"]
                                    else "original_byte_identical_cache",
                retained_original_v6_design=False, legacy_absolute_paths_rewritten=False,
                original_trained_weights_modified=False, new_v74_training_performed=False,
                production_authorized=False, cell_split_authorized=False)


def _cases(rows):
    from multirc_data import ReaderCase
    def case(r):
        r=dict(r)
        for k in ("facts", "sentence_ids", "evidence_sentence_indices"):
            r[k]=tuple(r[k])
        return ReaderCase(**r)
    return tuple(case(r) for r in rows)


def _pretrained_run(args, evidence, data):
    """Only called after model files and original ZIPs have passed preflight."""
    actual_run_wall, actual_run_cpu = time.perf_counter_ns(), time.process_time_ns()
    import torch
    import numpy as np
    from bridge_numpy_forward import weights_from_checkpoint, bridge_forward
    from bridge_campaign_utils import build_reader, save_model, reader_identity, write, source_inventory
    from bridge_gradient_guard import ARMS as actual_arms, continue_candidate
    from binding_continuation import continuation_plan
    from binding_protocol import retention_gate
    from token_features import TokenBank
    from token_campaign_utils import infer
    from binding_campaign_utils import binding_panel, natural_panel
    from token_reader_training import parameter_digest
    from group_loop import parameter_digest as typed_digest
    from bridge_gradient_archive_replay import decode_fp32_checkpoint, SHAPES

    require(actual_arms == ARMS, "original candidate algorithm arms changed")
    require(source_inventory() == data["design"]["runtime_source_sha256"],
            "original V6 source runtime has changed; portable preflight refused")
    torch.set_num_threads(1)
    binding = _cases(data["source"]["reader_train"])
    natural = _cases(data["natural"]["train"])
    tune = _cases(data["natural"]["tune"])
    bank = TokenBank.from_snapshot(args.snapshot, batch_size=16, chunk_tokens=64)
    # The exact historical cache is not guaranteed to be available; a genuine
    # new encoder forward is never mislabeled as a historical cached forward.
    if args.cache and evidence["cache"] and evidence["cache"]["exact"]:
        bank.restore_local(args.cache)
        cache_kind = "exact_historical_v5"
    else:
        bank.register((*binding, *natural))
        cache_kind = "new_pretrained_physical_encoding"
    require(bank.preprocess_sha256 == data["original_preprocess_sha256"],
            "original token preprocessing ABI differs")
    with zipfile.ZipFile(args.v6) as z:
        original_models={}
        original_reports={}
        numpy_weights={}
        for seed in SEEDS:
            directory=f"reader-v6-bridge/seed-{seed}/bridge/"
            raw=z.read(directory+"warmup.pt")
            decoded=decode_fp32_checkpoint(raw, SHAPES)
            require(decoded["execution_parameter_sha256"] == data["warmup"][seed]["execution_parameter_sha256"],
                    "original warmup numeric identity changed")
            model=build_reader("bridge",seed)
            model.load_state_dict(torch.load(io.BytesIO(raw),map_location="cpu",weights_only=True),strict=True)
            model.eval().requires_grad_(False)
            require(reader_identity(model)["parameter_count"] == 42562
                    and typed_digest(model)==decoded["execution_parameter_sha256"]
                    and parameter_digest(model)==decoded["training_parameter_sha256"],
                    "original warmup tensor import differs from independent decoder")
            original_models[seed]=model
            numpy_weights[seed], numpy_meta = weights_from_checkpoint(raw)
            require(numpy_meta["execution_parameter_sha256"]==decoded["execution_parameter_sha256"],
                    "independent Torch-free weight import changed")
            original_reports[seed]=_zjson(z,directory+"warmup-binding-train.json")

    # Source matching is required *before* the next optimizer step. The original
    # class scores are sealed historical TRAIN predictions, not held-out labels.
    old_parity={}
    for seed,model in original_models.items():
        actual,_=infer(model,binding,bank,depth=3,batch_size=16,prefix=f"v74/old/{seed}")
        independently=[]
        for start in range(0,len(binding),16):
            subset=bank.batch(binding[start:start+16])
            tensors=subset.features()
            data_triplet=tuple(t.detach().cpu().numpy().astype(np.float32,copy=True)
                               for t in tensors[:3])
            mask_triplet=tuple(t.detach().cpu().numpy().astype(np.bool_,copy=True)
                               for t in tensors[3:])
            recheck=bridge_forward(numpy_weights[seed],data_triplet,mask_triplet,steps=3)
            recheck=np.exp(recheck.astype(np.float64)-recheck.max(axis=1,keepdims=True))
            independently.extend((recheck[:,1]/recheck.sum(axis=1)).tolist())
        numerical_max=max(abs(a-b) for a,b in zip(actual,independently))
        numerical_flips=sum((a>.5)!=(b>.5) for a,b in zip(actual,independently))
        require(len(independently)==128 and numerical_max <= .0015 and numerical_flips==0,
                f"pretrained TokenBank independent NumPy numeric parity blocked seed {seed}: {numerical_max}/{numerical_flips}")
        observed=original_reports[seed]
        require(observed["case_ids"] == [x.case_id for x in binding]
                and len(actual)==len(observed["probabilities"])==128,
                "historical original-input prediction source mismatch")
        maximum=max(abs(a-b) for a,b in zip(actual,observed["probabilities"]))
        flips=sum((a > .5)!=(b > .5) for a,b in zip(actual,observed["probabilities"]))
        # Single-token differences cause prediction drifts; class matches alone
        # cannot certify comparable representations.
        require(maximum <= .001 and flips == 0,
                f"frozen V6 original TRAIN prediction parity blocked seed {seed}: {maximum:.6g}/{flips}")
        old_parity[str(seed)]=dict(n=128,max_absolute_probability_difference=maximum,
                                  class_flips=flips,independent_numpy_max_abs=numerical_max,
                                  independent_numpy_class_flips=numerical_flips,
                                  actual_granite_features=True,
                                  historical_training_only_not_future=True,
                                  semantic_provenance_claim=False)

    args.output.mkdir(parents=True, exist_ok=False)
    write(args.output,"start.json",dict(schema=SCHEMA, status="started", archive=evidence["archive"],
        old_input_parity=old_parity, cache_kind=cache_kind,
        original_preprocess_sha256=data["original_preprocess_sha256"],
        research_control_only=True, not_original_v6_identical_execution=True,
        original_model_sha256={str(k):v["model_file_sha256"] for k,v in data["warmup"].items()},
        learning_pretrained_model_frozen=True, production_authorized=False))
    results={}
    for seed in SEEDS:
        parent=original_models[seed]
        parent.training_source_groups=tuple(sorted({x.source_hash for x in binding}))
        plan=continuation_plan(natural,binding,seed=seed,updates=500)
        require(plan==data["plans"][seed], "old V6 update plan changed")
        write(args.output / f"seed-{seed}","plan.json",plan)
        old_batch=bank.batch(binding)
        natural_data=bank.dataset(natural)
        for arm in ARMS:
            dest=args.output / f"seed-{seed}" / arm
            dest.mkdir(parents=True,exist_ok=False)
            write(dest,"attempt.json",dict(arm=arm,seed=seed,plan_sha256=plan["plan_sha256"],
                original_model_file_sha256=data["warmup"][seed]["model_file_sha256"],
                original_probability_parity=old_parity[str(seed)],
                production_authorized=False))
            try:
                candidate,receipt=continue_candidate(parent,natural_data,old_batch,binding,
                    plan=plan,arm=arm,original_natural_cases=natural)
                require(receipt["attempted_optimizer_steps"]==500 and receipt["actual_reader_forwards"]==1500
                        and receipt["actual_backward_calls"]==1000,
                        "incomplete original-geometry real training work")
                save_model(dest,"candidate",candidate,receipt,seed=seed,
                           initial_digest=typed_digest(parent))
                old_metrics=binding_panel(dest,"old-binding-train",candidate,binding,bank)
                retain=retention_gate(old_metrics,original_reports[seed]["metrics"])
                results[f"{seed}/{arm}"]=dict(retained_old_training_cases=retain["passed"],
                    training_cpu_ns=receipt["cpu_ns"], accepted=receipt["accepted_optimizer_steps"],
                    rejected=receipt["rejected_optimizer_steps"],future_retention_verified=False)
                write(dest,"descriptive.json",dict(arm=arm,seed=seed,
                    old_training_retention=retain,old_training_metrics=old_metrics,
                    source_disjoint_future_not_evaluated=True,production_authorized=False))
            except BaseException as exc:
                write(dest,"failed.json",dict(type=type(exc).__name__,message=str(exc)[:400],
                    effect_denied=True, production_authorized=False))
                raise
    # Only a diagnostic, not a model-selection criterion. Pretrained features
    # are genuinely computed for this cohort, and are included in the cost.
    bank.register(tune)
    for seed in SEEDS:
        for arm in ARMS:
            # Already saved model after training. Evaluate and record separately.
            path=args.output / f"seed-{seed}"/arm
            record=json.loads((path/"candidate-model.json").read_text())
            model=build_reader("bridge",seed)
            model.load_state_dict(torch.load(path/record["file"],map_location="cpu",weights_only=True),strict=True)
            model.eval().requires_grad_(False)
            natural_panel(path,"new-natural-internal-tune",model,tune,bank)
    write(args.output,"completed.json",dict(schema=SCHEMA,status="completed",seeds=list(SEEDS),
        physical_encoder_forward_batches=bank.forward_batches,
        physical_encoder_sequence_count=bank.encoded_sequences,
        encoder_cpu_ns=bank.cpu_ns, encoder_wall_ns=bank.wall_ns,
        actual_run_cpu_ns=time.process_time_ns()-actual_run_cpu,
        actual_run_wall_ns=time.perf_counter_ns()-actual_run_wall,
        nested_costs_additive=False,
        arms=list(ARMS),results=results,cache_kind=cache_kind,
        three_original_pretrained_warmups_replayed=True,full_candidate_grid_completed=True,
        material_sha256=sha(canonical(data["model"])),
        cache_regenerated=cache_kind != "exact_historical_v5",
        complete_lifecycle_cost_measured=False, source_disjoint_future_windows=0,
        old_future_retention_verified=False, independent_new_task_verified=False,
        model_selected=False, cell_split_authorized=False, production_authorized=False))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("phase",choices=("audit","train"))
    for name in ("v4","v5","v6","snapshot","cache","output"):
        ap.add_argument("--"+name,type=Path,required=name in ("v4","v5","v6","snapshot","output"))
    args=ap.parse_args()
    # Validate ALL archives before taking even partial output authority.
    data=originals(args.v4,args.v5,args.v6)
    report=preflight(args.v4,args.v5,args.v6,args.snapshot,args.cache,original_data=data)
    if args.output.exists() or args.output.is_symlink():
        raise ValueError("write-once output location already exists")
    if args.phase=="audit":
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open("x") as f:
            json.dump(report,f,sort_keys=True,indent=2,allow_nan=False)
            f.write("\n")
        return
    require(report["material"]["ready"], "real pretrained material absent; training denied")
    require(args.cache is None or report["cache"]["exact"],
            "explicit TokenBank cache requested but not exact original SHA; training denied")
    _pretrained_run(args,report,data)


if __name__=="__main__":
    main()
