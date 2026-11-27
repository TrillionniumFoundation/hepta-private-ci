"""V9 fixed-budget grounding: public-only forwards and trainer-only auxiliary labels.

Compact update records replay scalar reductions; fixed auxiliary diagnostics also
retain vectors/attentions for independent dot-product and span-CE replay.
"""
from collections import Counter
import math
import re
import time
from types import SimpleNamespace

import torch
from torch.nn import functional as F

from binding_training import (_digest, _failed, _finish, _optimizer_storage, _train_copy,
    evaluate_reader, paired_margin_loss, world_pairs)
from retention_v7_training import STREAMS, _validate
from token_reader_training import parameter_digest

ARMS = ("latent_chain", "grounded_chain", "grounded_reset", "latent_reset")
_FIELDS = (("fact", "graph_slot_attentions", "graph_slots"),
           ("question", "graph_q_attention", "graph_question"),
           ("candidate", "graph_c_attention", "graph_candidate"))


def _require(value, message):
    if not value:
        raise ValueError(message)


class _Targets:
    """Validate all immutable target rows before copying a model or making Adam."""
    def __init__(self, record, cases, data, *, role="training", require_all=True):
        self.record, self.sha256 = record, _digest(record)
        _require(record["schema"] == "hepta.grounding.train-spans.v9"
            and record["case_ids"] == [c.case_id for c in cases]
            and len(record["aux_available"]) == len(cases) and all(type(v) is bool for v in record["aux_available"])
            and (not require_all or all(record["aux_available"])) and record["role"] == role
            and record["answer_labels_read"] is False and record["support_annotations_read"] is False
            and record["trainer_only"] is (role == "training") and record["annotations_authorized_as_model_inputs"] is False
            and all(c.source_split in (("train",) if role == "training" else ("train","validation")) for c in cases),
            "complete aligned train-only controlled grounding targets required")
        self.values = {}
        for role, _, _ in _FIELDS:
            target = torch.tensor(record[role + "_attention_targets"], dtype=torch.float32)
            mask = torch.tensor(record[role + "_supervision_mask"], dtype=torch.bool)
            _require(target.ndim == (4 if role == "fact" else 2) and target.shape[:-1] == mask.shape
                and target.shape[0] == len(cases) and torch.isfinite(target).all() and (target >= 0).all()
                and torch.allclose(target.sum(-1), mask.to(torch.float32)), "normalized explicit grounding supervision required")
            selected = (target > 0).to(target.dtype)
            _require(torch.allclose(target,selected/selected.sum(-1,keepdim=True).clamp_min(1)), "uniform complete entity-subtoken targets required")
            self.values[role] = target, mask
        _require(self.values["fact"][0].shape[2] == 2, "exact two fact endpoint targets required")
        for start in range(0, len(cases), 16):
            self.take(list(range(start, min(start + 16, len(cases)))), data.take(list(range(start, min(start + 16, len(cases))))))

    def take(self, indices, batch):
        result = dict(source_targets_sha256=self.sha256, case_ids=[self.record["case_ids"][i] for i in indices])
        for role, _, _ in _FIELDS:
            public = batch.fact_mask if role == "fact" else getattr(batch, role + "_mask")
            target, mask = (v[indices] for v in self.values[role])
            if role == "fact":
                _require(not mask[:,public.shape[1]:].any(), "supervised fact targets cannot be cropped away")
                target, mask = target[:, :public.shape[1], :, :public.shape[2]], mask[:, :public.shape[1]]
                valid = public.unsqueeze(-2)
                entities = [self.record["mention_entity_keys"][i][:public.shape[1]] for i in indices]
                contexts = [self.record["mention_context_keys"][i][:public.shape[1]] for i in indices]
            else:
                target, valid = target[:, :public.shape[1]], public
                entities = [self.record[role + "_entity_keys"][i] for i in indices]
                contexts = [self.record[role + "_context_keys"][i] for i in indices]
            _require(target.shape[:-1] == mask.shape and target.shape[-1] == valid.shape[-1]
                and torch.allclose(target.sum(-1), mask.to(torch.float32))
                and not (target * (~valid).to(target.dtype)).any(), "grounding targets exceed actual public token/chunk masks")
            flat_entities = [v for row in entities for pair in row for v in pair] if role == "fact" else entities
            flat_contexts = [v for row in contexts for pair in row for v in pair] if role == "fact" else contexts
            _require(len(flat_entities) == mask.numel() == len(flat_contexts), "aligned mention identity geometry required")
            for supervised, entity, context in zip(mask.flatten().tolist(), flat_entities, flat_contexts):
                _require((isinstance(entity, str) and re.fullmatch(r"(?:object|person|color):[A-Za-z]+", entity)
                    and isinstance(context, str) and re.fullmatch(r"[0-9a-f]{64}", context)) if supervised
                    else entity is None and context is None, "typed canonical/public-context keys required only on supervised mentions")
            result[role] = dict(target=target, supervised=mask, valid=valid,
                entities=flat_entities, contexts=flat_contexts)
        return result


def mention_contrastive(vectors, entities, contexts, *, full=False):
    """Deduplicate context means, then positive-mass InfoNCE across all entity types."""
    _require(vectors.ndim == 2 and len(vectors) == len(entities) == len(contexts)
        and torch.isfinite(vectors).all(), "aligned finite mention vectors required")
    groups, owners = {}, {}
    for index, (entity, context) in enumerate(zip(entities, contexts)):
        _require(context not in owners or owners[context] == entity, "one canonical entity per public mention context required")
        owners[context] = entity
        groups.setdefault((context, entity), []).append(index)
    keys = sorted(groups)
    compact = dict(temperature=.1, reduction="mean_logsumexp_eligible_minus_logsumexp_positive_mass",
        normalization_epsilon=1e-8,
        negative_types="all_other_canonical_entities_including_other_types", duplicate_reduction="mean_then_L2_normalize",
        queries_require_positive_and_negative=True, raw_mentions=len(vectors), unique_contexts=len(keys),
        duplicate_mentions=len(vectors)-len(keys), context_identity_sha256=_digest([[c,e,len(groups[(c,e)])] for c,e in keys]),
        query_indices=[], positive_counts=[], negative_counts=[], numerator_logsumexp=[], denominator_logsumexp=[],
        retrieval_correct=0, retrieval_queries=0)
    loss = vectors.sum() * 0
    if keys:
        means = torch.stack([vectors[groups[key]].mean(0) for key in keys])
        normalized = F.normalize(means, dim=-1, eps=1e-8)
        scores = normalized @ normalized.T / .1
        eligible = ~torch.eye(len(keys), dtype=torch.bool)
        positive = torch.tensor([[a[1] == b[1] for b in keys] for a in keys]) & eligible
        valid = positive.any(-1) & (eligible & ~positive).any(-1)
        chosen = valid.nonzero().flatten()
        if len(chosen):
            denominator = scores.masked_fill(~eligible, -torch.inf).logsumexp(-1)[chosen]
            numerator = scores.masked_fill(~positive, -torch.inf).logsumexp(-1)[chosen]
            loss = (denominator - numerator).mean()
            nearest = scores.masked_fill(~eligible, -torch.inf).argmax(-1)
            compact.update(query_indices=chosen.tolist(), positive_counts=positive.sum(-1)[chosen].tolist(),
                negative_counts=(eligible & ~positive).sum(-1)[chosen].tolist(),
                numerator_logsumexp=numerator.detach().tolist(), denominator_logsumexp=denominator.detach().tolist(),
                retrieval_correct=sum(keys[i][1] == keys[nearest[i]][1] for i in chosen.tolist()), retrieval_queries=len(chosen))
        if full:
            compact.update(raw_mention_vectors=vectors.detach().tolist(), mention_entity_keys=entities,
                mention_context_keys=contexts, unique_context_keys=[c for c,e in keys],
                unique_entity_keys=[e for c,e in keys], duplicate_counts=[len(groups[key]) for key in keys],
                context_mean_vectors=means.detach().tolist(), normalized_context_vectors=normalized.detach().tolist())
    elif full:
        compact.update(raw_mention_vectors=[],mention_entity_keys=[],mention_context_keys=[],unique_context_keys=[],
            unique_entity_keys=[],duplicate_counts=[],context_mean_vectors=[],normalized_context_vectors=[])
    compact["loss"] = loss.detach().item()
    return loss, compact


def _auxiliary(trace, targets, *, full=False):
    zero = trace["logits"].sum() * 0
    if targets is None:
        return zero, zero, dict(span_loss=0., span_count=0, span_mention_ce=[], span_selected_probabilities=[],
            span_token_counts=[], contrastive=dict(loss=0., retrieval_correct=0, retrieval_queries=0), auxiliary_available=False)
    terms, vectors, entities, contexts, selected_probabilities, counts, addresses = [], [], [], [], [], [], []
    for role, attention_key, vector_key in _FIELDS:
        value, attention = targets[role], trace[attention_key]
        target, supervised = value["target"], value["supervised"]
        _require(attention.shape == target.shape and torch.isfinite(attention).all() and (attention >= 0).all()
            and torch.allclose(attention.sum(-1)[supervised], torch.ones_like(attention.sum(-1)[supervised]), atol=1e-5),
            "aligned normalized public attention distributions required")
        selected, gold = attention[supervised], target[supervised]
        terms.extend((-(gold * selected.clamp_min(1e-9).log()).sum(-1)).unbind())
        selected_probabilities.extend([a[t > 0].detach().tolist() for a,t in zip(selected,gold)])
        counts.extend((gold > 0).sum(-1).tolist())
        vector = trace[vector_key]
        _require(vector.shape[:-1] == supervised.shape, "aligned graph mention metric vectors required")
        vectors.append(vector[supervised])
        selected_indices = supervised.flatten().nonzero().flatten().tolist()
        entities.extend(value["entities"][i] for i in selected_indices)
        contexts.extend(value["contexts"][i] for i in selected_indices)
        addresses.extend([[role,*address] for address in supervised.nonzero().tolist()])
    span = torch.stack(terms).mean() if terms else zero
    alignment, contrastive = mention_contrastive(torch.cat(vectors), entities, contexts, full=full)
    result = dict(auxiliary_available=bool(terms), source_targets_sha256=targets["source_targets_sha256"],
        span_probability_floor=1e-9,span_reduction="mean_all_supervised_mentions_including_context_duplicates",
        span_loss=span.detach().item(), span_count=len(terms), span_mention_ce=[v.detach().item() for v in terms],
        span_selected_probabilities=selected_probabilities, span_token_counts=counts, contrastive=contrastive,
        per_update_audit_scope="selected_span_probabilities_CE_and_scalar_contrastive_reductions_not_every_dot_product")
    if full:
        result.update(slot_addresses=addresses, attention_distributions={r:trace[a].detach().tolist() for r,a,_ in _FIELDS},
            attention_targets={r:targets[r]["target"].tolist() for r,_,_ in _FIELDS},
            supervision_masks={r:targets[r]["supervised"].tolist() for r,_,_ in _FIELDS},
            public_token_masks={r:targets[r]["valid"].tolist() for r,_,_ in _FIELDS},
            full_auxiliary_audit_scope="all_saved_mention_vectors_dedup_cosine_masks_logsumexp_and_attention_span_CE")
    return span, alignment, result


def _observation(model, data, target_table, indices, depth, graph_depth):
    wall,cpu = time.perf_counter_ns(),time.process_time_ns()
    batch = data.take(indices)
    targets = target_table.take(indices,batch)
    with torch.no_grad():
        trace = model(*batch.features(),steps=depth,graph_depth=graph_depth,
                      graph_reset=model.graph_reset_default,return_attention=True)
        _,_,result = _auxiliary(trace,targets,full=True)
    result.update(case_ids=targets["case_ids"], indices=list(indices), logits=trace["logits"].tolist(),
        probabilities=trace["logits"].softmax(-1)[:,1].tolist(),
        graph_fact_attentions=[v.tolist() for v in trace["graph_fact_attentions"]],
        graph_states=[v.tolist() for v in trace["graph_states"]],graph_readouts=[v.tolist() for v in trace["graph_readouts"]],
        graph_grouped_counts=trace["graph_grouped_counts"], depth=depth,graph_depth=graph_depth,
        graph_reset=model.graph_reset_default, physical_forward_calls=1,candidate_observations=len(indices),
        labels_or_annotations_entered_forward=False,cpu_ns=time.process_time_ns()-cpu,wall_ns=time.perf_counter_ns()-wall)
    return result


def _observation_table(model,cases,bank,targets):
    cases = tuple(cases)
    data = bank.dataset(cases)
    role = targets.get("role")
    _require(role in ("training","frozen_diagnostic") and (role != "frozen_diagnostic"
        or not model.training and all(not p.requires_grad for p in model.parameters())),
        "frozen diagnostic auxiliary scoring requires an already frozen eval model")
    return data,_Targets(targets,cases,data,role=role,require_all=False)


def auxiliary_observation(model,cases,bank,targets,*,indices=None,depth=3,graph_depth=2):
    """One auditable forward, reused for class scoring and auxiliary localization."""
    cases = tuple(cases)
    data,table = _observation_table(model,cases,bank,targets)
    indices = list(range(len(cases))) if indices is None else list(indices)
    _require(0 < len(indices) <= 16 and len(set(indices)) == len(indices)
        and all(type(i) is int and 0 <= i < len(cases) for i in indices), "one bounded auxiliary observation batch required")
    return _observation(model,data,table,indices,depth,graph_depth)


def auxiliary_panel(model,cases,bank,targets,*,depth=3,graph_depth=2):
    """Validate one frozen table once, then retain every batch16 physical forward."""
    wall,cpu = time.perf_counter_ns(),time.process_time_ns()
    data,table = _observation_table(model,cases,bank,targets)
    observations = [_observation(model,data,table,list(range(start,min(start+16,len(data.targets)))),depth,graph_depth)
                    for start in range(0,len(data.targets),16)]
    return dict(observations=observations,probabilities=[p for o in observations for p in o["probabilities"]],
        logits=[p for o in observations for p in o["logits"]],case_ids=[c for o in observations for c in o["case_ids"]],
        physical_forward_calls=len(observations),candidate_observations=len(data.targets),target_table_validated_once=True,
        cpu_ns=time.process_time_ns()-cpu,wall_ns=time.perf_counter_ns()-wall,nested_observation_costs_additive=False)


def _step(model,optimizer,data,indices,cases,table,depth,graph_depth,grounded):
    wall,cpu = time.perf_counter_ns(),time.process_time_ns()
    batch = data.take(indices)
    targets = None if table is None else table.take(indices,batch)
    optimizer.zero_grad(set_to_none=True)
    trace = model(*batch.features(),steps=depth,graph_depth=graph_depth,
                  graph_reset=model.graph_reset_default,return_attention=True)
    logits = trace["logits"]
    ce = F.cross_entropy(logits,batch.targets)
    pair = paired_margin_loss(logits,batch.targets,world_pairs(cases)) if cases else ce*0
    span,alignment,auxiliary = _auxiliary(trace,targets)
    span_weight,identity_weight = (1.,.1) if grounded and targets is not None else (0.,0.)
    loss = ce + (.5 if cases else 0.)*pair + span_weight*span + identity_weight*alignment
    _require(torch.isfinite(loss), "finite complete grounding loss required")
    for state in (*trace["states"],*trace["graph_states"]):
        if state.requires_grad:
            state.retain_grad()
    loss.backward()
    gradients = [p.grad for p in model.parameters() if p.grad is not None]
    _require(gradients and all(torch.isfinite(g).all() for g in gradients), "finite nonempty grounding parameter gradients required")
    result = dict(indices=list(indices),exposures=len(indices),logits=logits.detach().tolist(),
        binary_cross_entropy=ce.item(),pair_loss=pair.item(),pair_weight=.5 if cases else 0.,
        span_weight=span_weight,identity_weight=identity_weight,total_loss=loss.item(),auxiliary=auxiliary,
        parameter_gradient_l2=math.sqrt(sum(g.double().square().sum().item() for g in gradients)),
        graph_grouped_counts=trace["graph_grouped_counts"],depth=depth,graph_depth=graph_depth,
        graph_reset=model.graph_reset_default,inference_feature_arguments=6,finite_gradients=True)
    for name,states in (("hop",trace["states"]),("graph",trace["graph_states"])):
        _require(len(states) == (depth if name == "hop" else graph_depth)
            and all(torch.isfinite(s).all() and s.detach().abs().max() <= 1.000001
                    and (s.grad is None or torch.isfinite(s.grad).all()) for s in states), "bounded finite old and graph states required")
        result[name+"_state_gradient_l2"] = [None if s.grad is None else s.grad.norm().item() for s in states]
        result[name+"_state_max_abs"] = [s.detach().abs().max().item() for s in states]
        result[name+"_state_saturation_fraction"] = [s.detach().abs().ge(.99).float().mean().item() for s in states]
    before = {n:p.detach().clone() for n,p in model.named_parameters()}
    for group in ("common","graph"):
        result[group+"_parameter_gradient_l2"] = math.sqrt(sum(p.grad.double().square().sum().item()
            for n,p in model.named_parameters() if p.grad is not None and n.startswith("grounding.") == (group=="graph")))
    optimizer.step()
    _require(all(torch.isfinite(p).all() for p in model.parameters()), "finite grounding parameters after update required")
    for group in ("common","graph"):
        result[group+"_parameter_update_l2"] = math.sqrt(sum((p.detach().double()-before[n].double()).square().sum().item()
            for n,p in model.named_parameters() if n.startswith("grounding.") == (group=="graph")))
    result.update(finite_parameters_after_update=True,cpu_ns=time.process_time_ns()-cpu,wall_ns=time.perf_counter_ns()-wall)
    return result


def continue_grounding(model,natural_data,binding_data,augmentation_data,binding_cases,augmentation_cases,*,
                       plan,natural_cases,grounding_targets,arm=None,depth=3,graph_depth=2,diagnostic_interval=100,
                       wall_time_ns=1_800_000_000_000,failure_receipt_fn=None):
    """Run every fixed natural→augmentation→old update; never select an early state."""
    wall,cpu = time.perf_counter_ns(),time.process_time_ns()
    arm = model.grounding_arm if arm is None else arm
    receipt = dict(schema="hepta.grounding.continuation.v9",status="started",arm=arm,plan_sha256=plan.get("plan_sha256"),
        requested_logical_updates=plan.get("updates"),completed_steps=0,updates=[],diagnostics=[],optimizer="Adam_foreach_false",
        learning_rate=.001,batch_size=plan.get("batch_size"),stream_order=list(STREAMS),depth=depth,graph_depth=graph_depth,
        stopping_rule="fixed_budget_diagnostics_do_not_select",teacher_calls=0,anchor_weight=0.,final_evaluation_authorized=False)
    for stream in STREAMS:
        receipt["completed_"+stream+"_updates"],receipt["actual_"+stream+"_exposures"] = 0,0
    try:
        binding_cases,augmentation_cases,natural_cases = map(tuple,(binding_cases,augmentation_cases,natural_cases))
        _validate(plan,natural_data,binding_data,augmentation_data,binding_cases,augmentation_cases,natural_cases,model.input_dim)
        _require(arm in ARMS and arm == model.grounding_arm and model.graph_reset_default is arm.endswith("_reset")
            and depth == 3 and graph_depth == 2 and plan["batch_size"] == 16 and plan["updates"] >= 1
            and type(diagnostic_interval) is int and diagnostic_interval > 0
            and type(wall_time_ns) is int and wall_time_ns > 0 and set(grounding_targets) == {"binding","augmentation"},
            "registered grounding arm, graph-only reset, fixed optimizer/depth and bounded schedule required")
        tables = {role:_Targets(grounding_targets[role],cases,data) for role,cases,data in
                  (("binding",binding_cases,binding_data),("augmentation",augmentation_cases,augmentation_data))}
        _require(min(len(binding_cases),len(augmentation_cases)) >= 16, "complete fixed first16 auxiliary groups required")
        initial = parameter_digest(model)
        trained = _train_copy(model)
        optimizer = torch.optim.Adam(trained.parameters(),lr=.001,foreach=False)
        receipt.update(seed=plan["seed"],initial_model_sha256=initial,auxiliary_targets_sha256={k:v.sha256 for k,v in tables.items()},
            natural_sequence_sha256=_digest(plan["natural_batches"]),binding_sequence_sha256=_digest(plan["binding_batches"]),
            augmentation_sequence_sha256=_digest(plan["augmentation_batches"]),graph_reset=model.graph_reset_default,
            latent_computes_auxiliary_diagnostics=True,annotations_enter_forward=False,auxiliary_temperature=.1,
            wall_time_budget_ns=wall_time_ns)
        def diagnose(cycle):
            receipt["diagnostics"].append(dict(logical_step=cycle,optimizer_steps=len(receipt["updates"]),
                binding=evaluate_reader(trained,binding_data,cases=binding_cases,depth=depth,batch_size=16),
                augmentation=evaluate_reader(trained,augmentation_data,cases=augmentation_cases,depth=depth,batch_size=16),
                auxiliary_binding=_observation(trained,binding_data,tables["binding"],list(range(16)),depth,graph_depth),
                auxiliary_augmentation=_observation(trained,augmentation_data,tables["augmentation"],list(range(16)),depth,graph_depth),
                auxiliary_subset_fixed_before_training=True,diagnostic_used_for_selection=False))
        diagnose(0)
        status = "completed"
        for cycle in range(1,plan["updates"]+1):
            for stream in STREAMS:
                if time.perf_counter_ns()-wall >= wall_time_ns:
                    status = "budget_stopped"
                    break
                role = {"natural":"natural","transfer":"augmentation","retention":"binding"}[stream]
                indices = plan[role+"_batches"][cycle-1]
                cases = None if stream == "natural" else [({"binding":binding_cases,"augmentation":augmentation_cases}[role])[i] for i in indices]
                receipt["attempted_step"] = len(receipt["updates"])+1
                row = _step(trained,optimizer,{"natural":natural_data,"binding":binding_data,"augmentation":augmentation_data}[role],
                    indices,cases,tables.get(role),depth,graph_depth,arm.startswith("grounded_"))
                ids = [plan[role+"_case_ids"][i] for i in indices]
                row.update(step=len(receipt["updates"])+1,logical_step=cycle,stream=stream,data_role=role,
                    case_ids=ids,sample_sha256=_digest(ids))
                receipt["updates"].append(row)
                receipt["completed_"+stream+"_updates"] += 1
                receipt["actual_"+stream+"_exposures"] += len(indices)
            if status != "completed":
                break
            receipt["completed_steps"] = cycle
            if cycle % diagnostic_interval == 0 or cycle == plan["updates"]:
                diagnose(cycle)
        receipt.update(status=status,actual_total_exposures=sum(receipt["actual_"+s+"_exposures"] for s in STREAMS),
            case_exposures={s:dict(Counter(c for r in receipt["updates"] if r["stream"]==s for c in r["case_ids"])) for s in STREAMS},
            actual_auxiliary_diagnostic_forwards=len(receipt["diagnostics"])*2,actual_auxiliary_diagnostic_candidates=len(receipt["diagnostics"])*32,
            raw_step_logits_recorded=True,full_auxiliary_trace_scope="fixed_first16_old_and_augmentation_every_diagnostic")
        sources = set(getattr(model,"training_source_groups",())) | set(natural_data.source_groups) | set(binding_data.source_groups) | set(augmentation_data.source_groups)
        receipt.update(_optimizer_storage(optimizer,trained))
        trained,receipt = _finish(model,trained,SimpleNamespace(source_groups=sources),initial,receipt)
        receipt.update(cpu_ns=time.process_time_ns()-cpu,wall_ns=time.perf_counter_ns()-wall,
            timing_scope="validate_copy_optimizer_all_updates_full_class_and_fixed_auxiliary_diagnostics_freeze_receipt")
        return trained,receipt
    except Exception as error:
        _failed(error,receipt,wall,cpu,failure_receipt_fn)
