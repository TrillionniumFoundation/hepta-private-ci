"""Constructed momentum-sign witness on training data, outside frozen field audit."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..field_bridge_20261027.run import setup, digest, write_json, object_hash
from ..field_bridge_20261027.adapters import local_state, local_hash, local_parameters, frozen_base_hash
from ..field_bridge_20261027.adaptation import fixed_output
from ..field_bridge_v2_20261027.learning import (P, make_model, new_optimizer, gradient_corpus, panel,
    hard_outputs, update, clone_optimizer_model, train_steps, observe_field, optimizer_hash, save_model)
from ..field_bridge_v2_20261027.field_bank import margin_features
from ..v6.data import make_batch, render_tokens
from ..v6.observer import write_bundle, read_bundle, observe_tensors

HERE = Path(__file__).resolve().parent
PROTOCOL_PATH = HERE / "MOMENTUM_WITNESS_PROTOCOL.json"


def restore(path, original, seed, recipe, expected_base):
    record = torch.load(path, map_location="cpu", weights_only=True)
    if (record["schema"] != "hepta.field-bridge.v2.adapter" or record["recipe"] != recipe
            or record["metadata"]["seed"] != seed or record["metadata"]["base_identity"] != expected_base):
        raise ValueError("Selected pilot checkpoint metadata differs from pinned identity")
    model = make_model(original, seed, recipe)
    parameters = dict(model.named_parameters())
    if set(record["parameters"]) != set(local_state(model)):
        raise ValueError("Incomplete or extra local parameter inventory")
    with torch.no_grad():
        for name, value in record["parameters"].items():
            if value.shape != parameters[name].shape or value.dtype != parameters[name].dtype or not torch.isfinite(value).all():
                raise ValueError("Invalid local parameter shape, dtype, or value")
            parameters[name].copy_(value)
    optimizer = new_optimizer(model, recipe)
    optimizer.load_state_dict(deepcopy(record["optimizer"]))
    if local_hash(model) != record["local_sha256"] or optimizer_hash(optimizer) != record["optimizer_sha256"]:
        raise ValueError("Complete optimizer or parameter restoration identity failed")
    return model, optimizer


def rich_field(model, optimizer, recipe, response, clean, observer, action, step, value):
    return (observe_field(model, optimizer, recipe, response, clean, action, step, value)
            + margin_features(model, response, observer, action))


def alignment(model, original, optimizer, data, recipe, seed, action):
    parameter_before, optimizer_before = local_hash(model), optimizer_hash(optimizer)
    step, trajectory = 288, 901
    batch_seed = seed*100003 + 600000 + trajectory*1009 + step
    batch = make_batch(data, "train", P["batch_size"], batch_seed, corruption=P["conditions"][step % 4])
    update(model, original, optimizer, batch, action, 0., 107+step, recipe)
    dot = gradient_square = momentum_square = 0.
    gradient_digest, momentum_digest = hashlib.sha256(), hashlib.sha256()
    for parameter in local_parameters(model):
        gradient = parameter.grad.detach().double()
        momentum = optimizer.state[parameter]["momentum_buffer"].detach().double()
        dot += float((gradient*momentum).sum())
        gradient_square += float(gradient.square().sum())
        momentum_square += float(momentum.square().sum())
        gradient_digest.update(gradient.numpy().tobytes())
        momentum_digest.update(momentum.numpy().tobytes())
    if local_hash(model) != parameter_before or optimizer_hash(optimizer) != optimizer_before:
        raise RuntimeError("Measuring the clipped gradient changed carried parameters/momentum")
    if momentum_square <= 0 or gradient_square <= 0:
        raise RuntimeError("A nonzero momentum/gradient witness was not available")
    return dict(dot=dot, cosine=dot/(gradient_square*momentum_square)**.5,
                gradient_l2=gradient_square**.5, momentum_l2=momentum_square**.5,
                gradient_sha256=gradient_digest.hexdigest(), momentum_sha256=momentum_digest.hexdigest(),
                batch_seed=batch_seed, source_ids=batch.source_ids,
                parameters_and_optimizer_unchanged=True)


@torch.inference_mode()
def media_readback(root, model, response, observer, action, expected):
    records, offset = [], 0
    for index, (condition, batch) in enumerate(response):
        output = fixed_output(model, batch, action, 91027+index)
        pixels = (output.image_logits.sigmoid()*255).round().to(torch.uint8)
        captions = [render_tokens(row) for row in output.token_ids]
        restored_pixels, restored_captions, local = [], [], []
        for item in range(2):
            paths = write_bundle(root/condition/f"case-{item}", captions[item], pixels[item].float()/255)
            reread, caption, hashes = read_bundle(paths)
            restored = (reread*255).round().to(torch.uint8)
            if not torch.equal(restored[0],pixels[item]) or caption != captions[item]:
                raise RuntimeError("Actual PNG/UTF8 readback differs from tensor output")
            combined = hashlib.sha256(restored[0].numpy().tobytes()+caption.encode()).hexdigest()
            if combined != expected["output_sha256"][offset+item]:
                raise RuntimeError("Regenerated full-batch media differs from hard-value record")
            restored_pixels.append(reread);restored_captions.append(caption)
            local.append(dict(condition=condition,index=item,source_ids=batch.source_ids[item],
                              paths=paths,sha256=hashes,combined_output_sha256=combined))
        scores = observe_tensors(observer,torch.cat(restored_pixels),restored_captions,
                                 batch.target.pixels[:2],batch.target.labels[:2])
        for item,row in enumerate(local):
            value=scores[item]["utility"]-P["charge"]*(1+(action!=0))
            row["readback_net_value"]=value
            row["value_difference"]=value-expected["values"][offset+item]
            if abs(row["value_difference"])>1e-12:
                raise RuntimeError("Actual readback scoring differs from hard-value calculation")
            records.append(row)
        offset+=len(batch.source_ids)
    return records


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets",required=True)
    parser.add_argument("--pilot",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--registered-commit",required=True)
    args=parser.parse_args()
    protocol=json.loads(PROTOCOL_PATH.read_text())
    frozen={name:digest(HERE.parent/"field_bridge_v2_20261027"/name) for name in protocol["sources"]}
    if frozen!=protocol["sources"] or digest(args.pilot/"PILOT_RESULT.json")!=protocol["pilot_result_sha256"]:
        raise ValueError("Scientific source or selected pilot identity changed")
    helper_sha=digest(__file__)
    args.out.mkdir(parents=True,exist_ok=False)
    write_json(args.out/"SOURCE_FREEZE.json",dict(protocol_sha256=digest(PROTOCOL_PATH),helper_sha256=helper_sha,
                                                original_source_sha256=frozen,registered_commit=args.registered_commit))
    pilot=json.loads((args.pilot/"PILOT_RESULT.json").read_text())
    recipe=P["candidates"][pilot["selected"]["index"]]
    if recipe["name"]!=protocol["selected_recipe"]:raise ValueError("Unexpected selected recipe")
    corpus,observers,originals,identities=setup(args)
    observer,data=observers["reward"],gradient_corpus(corpus)
    results={}
    started=time.perf_counter_ns()
    for seed in protocol["seeds"]:
        source=args.pilot/protocol["checkpoint_files"][str(seed)]["path"]
        if digest(source)!=protocol["checkpoint_files"][str(seed)]["sha256"]:raise ValueError("Pilot checkpoint bytes changed")
        original,action=originals[seed],pilot["results"][str(seed)]["action"]
        response,clean=panel(corpus,P["response_panel"],seed),panel(corpus,P["clean_probe"],seed)
        model,optimizer=restore(source,original,seed,recipe,identities[seed])
        base_hash=frozen_base_hash(model)
        reversed_model,reversed_optimizer=clone_optimizer_model(model,optimizer,recipe)
        with torch.no_grad():
            for fields in reversed_optimizer.state.values():
                if "momentum_buffer" in fields:fields["momentum_buffer"].neg_()
        pairs=(("original_momentum",model,optimizer),("reversed_momentum",reversed_model,reversed_optimizer))
        current=hard_outputs(model,response,observer,action)
        if hard_outputs(reversed_model,response,observer,action)!=current:raise RuntimeError("Sign flip changed current model output")
        directory=args.out/str(seed);directory.mkdir()
        state_records={}
        for label,parent,parent_optimizer in pairs:
            before=rich_field(parent,parent_optimizer,recipe,response,clean,observer,action,288,current["value"])
            checkpoint=directory/f"{label}-initial.pt"
            save_model(checkpoint,parent,parent_optimizer,recipe,dict(seed=seed,base_identity=identities[seed],
                phase="constructed_momentum_witness",learning_step=288,intervention=label))
            align=alignment(parent,original,parent_optimizer,data,recipe,seed,action)
            rows=[]
            for index,multiplier in enumerate(protocol["learning_actions"]):
                branch,branch_optimizer=clone_optimizer_model(parent,parent_optimizer,recipe)
                train_steps(branch,original,branch_optimizer,data,action,recipe,seed,901,288,8,multiplier)
                outcome=hard_outputs(branch,response,observer,action)
                after=rich_field(branch,branch_optimizer,recipe,response,clean,observer,action,296,outcome["value"])
                if frozen_base_hash(branch)!=base_hash:raise RuntimeError("Witness changed frozen generator parameters")
                if index==0 and (outcome!=current or local_hash(branch)!=local_hash(parent)
                                 or optimizer_hash(branch_optimizer)!=optimizer_hash(parent_optimizer)):
                    raise RuntimeError("Witness zero action changed carried state or output")
                state_path=directory/f"{label}-action-{index}.pt"
                save_model(state_path,branch,branch_optimizer,recipe,dict(seed=seed,base_identity=identities[seed],
                    phase="constructed_momentum_witness",learning_step=296,intervention=label,multiplier=multiplier))
                media=media_readback(directory/"media"/f"{label}-action-{index}",branch,response,observer,action,outcome)
                row=dict(action_index=index,multiplier=multiplier,model_sha256=local_hash(branch),
                    optimizer_sha256=optimizer_hash(branch_optimizer),checkpoint=str(state_path),
                    checkpoint_sha256=digest(state_path),outcome=outcome,rich_after=after,readback=media)
                rows.append(row)
            state_records[label]=dict(rich_before=before,field_before=before[:7],current=current,alignment=align,
                initial_model_sha256=local_hash(parent),initial_optimizer_sha256=optimizer_hash(parent_optimizer),
                initial_checkpoint=str(checkpoint),initial_checkpoint_sha256=digest(checkpoint),branches=rows,
                best_action=int(np.argmax([r["outcome"]["value"] for r in rows])))
        plus,minus=state_records["original_momentum"],state_records["reversed_momentum"]
        if plus["rich_before"]!=minus["rich_before"] or plus["initial_model_sha256"]!=minus["initial_model_sha256"]:
            raise RuntimeError("Constructed states do not share the exact registered observation")
        if plus["initial_optimizer_sha256"]==minus["initial_optimizer_sha256"]:raise RuntimeError("Sign intervention did not change optimizer state")
        if plus["alignment"]["gradient_sha256"]!=minus["alignment"]["gradient_sha256"]:raise RuntimeError("Common gradient differs between equal parameter states")
        comparisons=[]
        for a,b in zip(plus["branches"],minus["branches"],strict=True):
            comparisons.append(dict(action_index=a["action_index"],multiplier=a["multiplier"],
                value_original=a["outcome"]["value"],value_reversed=b["outcome"]["value"],
                reversed_minus_original=b["outcome"]["value"]-a["outcome"]["value"],
                output_hash_change_count=sum(x!=y for x,y in zip(a["outcome"]["output_sha256"],b["outcome"]["output_sha256"],strict=True)),
                semantic_change_count=sum(x!=y for x,y in zip(a["outcome"]["decisions"],b["outcome"]["decisions"],strict=True)),
                next_local_parameters_equal=a["model_sha256"]==b["model_sha256"],
                next_H7_equal=a["rich_after"][:7]==b["rich_after"][:7],next_rich25_equal=a["rich_after"]==b["rich_after"],
                next_H7_linf=float(np.max(np.abs(np.asarray(a["rich_after"][:7])-b["rich_after"][:7])))))
        results[str(seed)]=dict(source_checkpoint_sha256=digest(source),fixed_deployment_action=action,
            H7_equal=True,rich25_equal=True,rich_width=len(plus["rich_before"]),same_parameters=True,
            different_complete_optimizer=True,states=state_records,comparison=comparisons,
            best_action_original=plus["best_action"],best_action_reversed=minus["best_action"],
            best_action_differs=plus["best_action"]!=minus["best_action"],
            reachability_of_reversed_state_claimed=False,source_response_ids=response[0][1].source_ids)
        write_json(directory/"RESULT.json",results[str(seed)])
        print(json.dumps(dict(seed=seed,H7_equal=True,rich25_equal=True,best_actions=[plus["best_action"],minus["best_action"]],
                              gradient_momentum_cosines=[plus["alignment"]["cosine"],minus["alignment"]["cosine"]],comparison=comparisons)),flush=True)
    if {name:digest(HERE.parent/"field_bridge_v2_20261027"/name) for name in frozen}!=frozen or digest(__file__)!=helper_sha:
        raise RuntimeError("A frozen source changed during witness computation")
    write_json(args.out/"MOMENTUM_WITNESS_RESULT.json",dict(schema="hepta.field-bridge-v2.momentum-witness-result.v1",
        protocol_sha256=digest(PROTOCOL_PATH),registered_commit=args.registered_commit,helper_sha256=helper_sha,
        results=results,wall_ns=time.perf_counter_ns()-started,full_state_checkpoints=30,raw_media_pairs=192,
        test_retention_accessed=False,audit_observer_loaded=False,predictor_audit_labels_accessed=False,
        existing_controller_protocol_or_selection_changed=False,constructed_state_reachability_claimed=False))


if __name__=="__main__":main()
