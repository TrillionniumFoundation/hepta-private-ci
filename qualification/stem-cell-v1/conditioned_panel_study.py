"""Preregisterable two-fact, two-query conditional Reader *research* panel.

Synthetic balanced grammar (not natural QA). One frozen token-level Encoder per
source document, different question-conditioned readouts, matched Head parameter
counts, and explicit mean/no-evidence/no-query controls. A separate score call
consumes held-out labels only after sealed predictions. This is an interface and
falsification experiment, not an independent model capability certificate.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass

import torch
from torch import nn

from conditional_evidence import ConditionedReader, Evidence, TrainingCase, fit_reader, evidence_digest
from execution_meter import WorkLedger, validate_policy
from matrix_bank import state_digest
from next_round_matrix import _digest
from paired_execution import PHASES

OPTIONS = ('no', 'yes')
QUESTIONS = ('Is the amber lamp switched on?', 'Is the cobalt fan running?')
ARMS = ('conditioned', 'mean_pool', 'no_evidence', 'no_query')
SCHEMA = 'hepta.conditioned-facts-group-panel.v1'


@dataclass(frozen=True)
class PanelCase:
    case_id: str
    source_group: str
    evidence: Evidence
    task_ids: tuple[str, str]
    targets: tuple[int, int] | None
    label_observed_ns: int | None


def _facts(a, b, room):
    return (f'In lab {room}, the amber lamp is switched {"on" if a else "off"}. '
            f'The cobalt fan is {"running" if b else "stopped"}.')


def remove_premise(text, which):
    """Ablate exactly the requested fact, never fabricate a new target label."""
    if which == 0:
        new, count = re.subn(r'the amber lamp is switched (?:on|off)',
                             'the amber lamp status is not provided', text, count=1, flags=re.IGNORECASE)
    elif which == 1:
        new, count = re.subn(r'the cobalt fan is (?:running|stopped)',
                             'the cobalt fan status is not provided', text, count=1, flags=re.IGNORECASE)
    else:
        raise ValueError('only two registered premises')
    if count != 1 or new == text:
        raise ValueError('a required premise was absent from original evidence')
    return new


def build_panel(checkpoint_sha256, *, seed=7347, train_groups=8, eval_groups=4,
                cutoff_ns=10, evaluation_ns=20, include_labels=True):
    """Balanced four combinations per group; opaque IDs do not encode answers."""
    if (not isinstance(checkpoint_sha256, str) or len(checkpoint_sha256) != 64
            or any(x not in '0123456789abcdef' for x in checkpoint_sha256)
            or type(include_labels) is not bool
            or type(seed) is not int or seed < 1
            or type(train_groups) is not int or not 2 <= train_groups <= 32
            or type(eval_groups) is not int or not 1 <= eval_groups <= 32
            or type(cutoff_ns) is not int or not 1 < cutoff_ns < evaluation_ns
            or type(evaluation_ns) is not int):
        raise ValueError('bounded immutable study material required')
    train, evaluation, labels = [], [], {}
    for split, n in (('train', train_groups), ('eval', eval_groups)):
        for group in range(n):
            # No quality-dependent selection. Every source group has all four
            # label combinations; source-group count is NOT row count.
            for a in (0, 1):
                for b in (0, 1):
                    digest = hashlib.sha256(f'{seed}:{split}:{group}:{a}:{b}'.encode()).hexdigest()
                    cid = digest[:24]
                    room = f'{split}-{group}-{digest[24:30]}'
                    observed = 2 if split == 'train' else evaluation_ns
                    ev = Evidence('public-test-principal', cid, _facts(a, b, room),
                                  observed, checkpoint_sha256)
                    tasks = (cid+'-q0', cid+'-q1')
                    case = PanelCase(cid, f'{split}-group-{group}', ev, tasks,
                                     (a,b) if split == 'train' else None,
                                     5 if split == 'train' else None)
                    if split == 'train':
                        train.append(case)
                    else:
                        evaluation.append(case)
                        if include_labels:
                            labels.update({tasks[0]: a, tasks[1]: b})
    validate_panel(train, evaluation, cutoff_ns=cutoff_ns, evaluation_ns=evaluation_ns)
    return train, evaluation, labels


def validate_panel(train, evaluation, *, cutoff_ns, evaluation_ns):
    if (type(cutoff_ns) is not int or type(evaluation_ns) is not int
            or not 0 < cutoff_ns < evaluation_ns or not isinstance(train, list)
            or not isinstance(evaluation, list) or not train or not evaluation):
        raise ValueError('separate bounded training and heldout panels required')
    groups, content, case_ids, task_ids = [set(),set()], [set(),set()], set(), set()
    for split, rows in enumerate((train,evaluation)):
        if len(rows) > 128:
            raise ValueError('study panel is too large')
        for case in rows:
            if not isinstance(case,PanelCase) or not isinstance(case.case_id,str):
                raise ValueError('typed panel rows required')
            if (not isinstance(case.source_group,str) or not case.source_group
                    or not isinstance(case.task_ids,tuple) or len(case.task_ids)!=2
                    or any(not isinstance(v,str) or not v or v in task_ids for v in case.task_ids)
                    or case.case_id in case_ids):
                raise ValueError('duplicate, missing or reordered identities')
            task_ids.update(case.task_ids)
            case_ids.add(case.case_id)
            d = evidence_digest(case.evidence)
            if case.evidence.principal!='public-test-principal':
                raise ValueError('cross-principal panel')
            if split==0:
                if (not case.source_group.startswith('train-group-')
                        or not isinstance(case.targets,tuple) or len(case.targets)!=2
                        or any(type(z) is not int or z not in (0,1) for z in case.targets)
                        or type(case.label_observed_ns) is not int
                        or not case.evidence.available_at_ns <= case.label_observed_ns <= cutoff_ns):
                    raise ValueError('training label outside training cutoff')
            else:
                if (not case.source_group.startswith('eval-group-') or case.targets is not None
                        or case.label_observed_ns is not None
                        or case.evidence.available_at_ns < evaluation_ns):
                    raise ValueError('final-evaluation labels may not enter learning')
            groups[split].add(case.source_group)
            content[split].add(_digest(case.evidence.text))
            if d != evidence_digest(case.evidence):
                raise ValueError('unstable source identity')
    if groups[0]&groups[1] or content[0]&content[1]:
        raise ValueError('train/heldout source or exact-text overlap')
    # Each source group must be complete and balanced. Missing/hard-selected
    # examples do not silently shrink a denominator.
    for split, rows in enumerate((train,evaluation)):
        counts={g:0 for g in groups[split]}
        targets_by_group={g:set() for g in groups[split]}
        for r in rows:
            counts[r.source_group]+=1
            if split == 0: targets_by_group[r.source_group].add(r.targets)
        if any(v!=4 for v in counts.values()):
            raise ValueError('preregistered source-group denominator incomplete')
        if split == 0 and any(values!={(0,0),(0,1),(1,0),(1,1)}
                              for values in targets_by_group.values()):
            raise ValueError('training source group not class-pair balanced')
    return True


def _features(states, q, arm):
    if arm == 'conditioned':
        return states, q
    if arm == 'mean_pool':
        return states.mean(0,keepdim=True), q
    if arm == 'no_evidence':
        return states.new_zeros((1,states.shape[1])),q
    if arm == 'no_query':
        return states,torch.zeros_like(q)
    raise ValueError('unknown ablation profile')


def _validate_tensor(states, query, max_feature_bytes):
    if (not isinstance(states,torch.Tensor) or states.ndim != 2
            or not 1 <= len(states) <= 512 or not 2 <= states.shape[1] <= 8192
            or not isinstance(query,torch.Tensor) or query.shape != (states.shape[1],)
            or any(t.device.type!='cpu' or t.dtype!=torch.float32 or t.requires_grad
                   or not torch.isfinite(t).all().item() for t in (states,query))
            or states.untyped_storage().nbytes() > max_feature_bytes
            or query.untyped_storage().nbytes() > max_feature_bytes):
        raise ValueError('untrusted or over-budget frozen feature source')


def train_panel(train, evaluation, *, evidence_encoder, query_encoder, checkpoint_sha256,
                cutoff_ns=10, evaluation_ns=20, steps=96, seed=7347,
                policy, max_feature_bytes=8*1024*1024,
                max_retained_bytes=64*1024*1024, learning_rate=.01):
    """Model process: NO eval targets or evaluator callback in arguments.

    Returns trained Reader objects and sealed-candidate predictions, not scores.
    A real-world isolation boundary requires separate OS processes/owners.
    """
    validate_panel(train,evaluation,cutoff_ns=cutoff_ns,evaluation_ns=evaluation_ns)
    validate_policy(policy)
    if (type(max_feature_bytes) is not int or not 1024<=max_feature_bytes<=256*1024*1024
            or type(steps) is not int or not 1<=steps<=1024 or type(seed) is not int or seed<1):
        raise ValueError('bounded study resource profile required')
    if type(max_retained_bytes) is not int or not 4096 <= max_retained_bytes <= 256*1024*1024:
        raise ValueError('bounded total retained feature storage required')
    if any(x.evidence.checkpoint_sha256!=checkpoint_sha256 for x in train+evaluation):
        raise ValueError('mixed or changed frozen Encoder weights')
    caps=dict.fromkeys(PHASES,10**14)
    encoder_meter=WorkLedger(policy,caps)
    train_features=[]
    eval_features=[]
    all_cases=train+evaluation
    dimension=None
    unique_question_calls=0
    retained_bytes=0
    def materialize(rows,phase,into):
        nonlocal dimension,unique_question_calls,retained_bytes
        for case in rows:
            with encoder_meter.scope(phase,'encoder'),torch.inference_mode():
                states=evidence_encoder(case.evidence)
            if not isinstance(states,torch.Tensor) or states.ndim!=2:
                raise ValueError('invalid Encoder output geometry')
            if dimension is None:dimension=states.shape[1]
            with torch.inference_mode():
                for index,text in enumerate(QUESTIONS):
                    with encoder_meter.scope(phase,'material'):
                        query=query_encoder(text,OPTIONS)
                        _validate_tensor(states,query,max_feature_bytes)
                    unique_question_calls+=1
                    retained_bytes+=states.numel()*states.element_size()+query.numel()*query.element_size()
                    if retained_bytes>max_retained_bytes:
                        raise ValueError('retained evidence/query cache budget exceeded')
                    # Gradient-based Head training must not receive inference
                    # tensors; keep values frozen but materialize normal leaves.
                    with torch.inference_mode(False):
                        frozen_states=states.detach().clone()
                        frozen_query=query.detach().clone()
                    into.append((case,index,frozen_states,frozen_query))
    # Causal ordering matters: not even evaluation TEXT/embeddings reach the
    # Encoder before all candidate training has finished.
    materialize(train,'train',train_features)
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        base=ConditionedReader(dimension,2).eval()
    reader_states={}
    fit_receipts={}
    for arm in ARMS:
        prepared=[TrainingCase(*_features(s,q,arm),case.targets[index],
                               case.source_group,case.label_observed_ns)
                  for case,index,s,q in train_features]
        training_meter=WorkLedger(policy,caps)
        reader,receipt=fit_reader(base,prepared,cutoff_ns=cutoff_ns,steps=steps,
                                  seed=seed,learning_rate=learning_rate,meter=training_meter)
        reader_states[arm]=reader
        fit_receipts[arm]=dict(**receipt,weights_digest=state_digest(reader))
    # No final input was encoded during any fit_reader call above.
    materialize(evaluation,'inference',eval_features)
    encoder_observation=encoder_meter.report()
    predictions={arm:[] for arm in ARMS}
    eval_meter=WorkLedger(policy,caps)
    ablation_rows=[]
    for case,index,states,q in eval_features:
        for arm,reader in reader_states.items():
            token_states, question_vector=_features(states,q,arm)
            with eval_meter.scope('inference','bank'),torch.inference_mode():
                values=reader(token_states,question_vector)
            if values.shape!=(2,) or not torch.isfinite(values).all().item():
                raise ValueError('nonfinite Reader prediction')
            predictions[arm].append(dict(task_id=case.task_ids[index],source_group=case.source_group,
                question_slot=index,logits=[float(v) for v in values],
                weight_sha256=fit_receipts[arm]['weights_digest']))
    # Two distinct ablated evidence inputs per heldout source document. Each
    # omission is relevant to one registered question and irrelevant to the
    # other, so answer disappearance cannot be mistaken for an independent
    # future label. No training/parameter selection uses these diagnostics.
    ablation_meter=WorkLedger(policy,caps)
    eval_by_case={}
    for case,index,states,q in eval_features:
        eval_by_case.setdefault(case.case_id,{})[index]=(case,q)
    for case_id,slots in eval_by_case.items():
        if set(slots)!={0,1}:
            raise ValueError('incomplete paired heldout questions')
        case=slots[0][0]
        missing_states={}
        for omission in (0,1):
            modified=Evidence(case.evidence.principal,case.evidence.document_id+'-missing-'+str(omission),
                    remove_premise(case.evidence.text,omission),
                    case.evidence.available_at_ns,case.evidence.checkpoint_sha256)
            with ablation_meter.scope('evaluation','encoder'),torch.inference_mode():
                states=evidence_encoder(modified)
                _validate_tensor(states,slots[omission][1],max_feature_bytes)
            missing_states[omission]=states
        for index in (0,1):
            job,q=slots[index]
            reader=reader_states['conditioned']
            with ablation_meter.scope('evaluation','bank'),torch.inference_mode():
                relevant=reader(missing_states[index],q)
                irrelevant=reader(missing_states[1-index],q)
            if not torch.isfinite(relevant).all().item() or not torch.isfinite(irrelevant).all().item():
                raise ValueError('nonfinite ablation logits')
            ablation_rows.append(dict(task_id=job.task_ids[index],
                relevant_removed_logits=relevant.tolist(),
                irrelevant_removed_logits=irrelevant.tolist()))
    observation=dict(schema='hepta.conditioned-facts-predictions.v1',
        checkpoint_sha256=checkpoint_sha256,
        protocol=dict(train_source_groups=sorted({c.source_group for c in train}),
            eval_source_groups=sorted({c.source_group for c in evaluation}),
            train_case_ids=[c.case_id for c in train],eval_case_ids=[c.case_id for c in evaluation],
            seed=seed,steps=steps,learning_rate=learning_rate,
            training_cutoff_ns=cutoff_ns,evaluation_ns=evaluation_ns,
            training_group_count=len({c.source_group for c in train}),
            eval_group_count=len({c.source_group for c in evaluation}),
            question_names=QUESTIONS,options=OPTIONS),
        train_records=len(train_features),eval_records=len(eval_features),
        encoder_calls=len(all_cases),query_calls=unique_question_calls,
        retained_features_payload_bytes=retained_bytes,
        max_retained_features_bytes=max_retained_bytes,
        ablation_encoder_calls=2*len(evaluation),
        ablation_predictions=ablation_rows,
        ablation_work=ablation_meter.report(),
        initial_shared_encoder_parameters_not_counted_as_trainable=True,
        arm_parameter_counts={arm:sum(p.numel() for p in model.parameters()) for arm,model in reader_states.items()},
        fitting=fit_receipts,predictions=predictions,
        encoding_work=encoder_observation,
        prediction_work=eval_meter.report(),
        independent_source_authentication=False,
        independent_generalization_established=False,
        final_labels_read_during_training=False,
        identical_training_flops_claimed=False,
        production_authorized=False)
    observation['observation_id']=_digest(observation)
    return observation,reader_states


def _probabilities(logits):
    m=max(logits)
    ex=[math.exp(z-m) for z in logits]
    return [v/sum(ex) for v in ex]


def score_panel(observation, labels, *, expected_observation_id, expected_labels_sha256):
    """Evaluator-only: fixed sealed predictions, separately retained label map."""
    if not isinstance(observation,dict) or observation.get('schema')!='hepta.conditioned-facts-predictions.v1':
        raise ValueError('complete typed predictions required')
    if observation.get('observation_id')!=expected_observation_id or _digest({k:v for k,v in observation.items() if k!='observation_id'})!=expected_observation_id:
        raise ValueError('prediction identity changed after publication')
    if not isinstance(labels,dict) or _digest(labels)!=expected_labels_sha256:
        raise ValueError('evaluation label bytes/identity must be retained independently')
    arm_rows=observation.get('predictions')
    if not isinstance(arm_rows,dict) or set(arm_rows)!=set(ARMS):
        raise ValueError('four complete preregistered controls required')
    common=[p['task_id'] for p in arm_rows[ARMS[0]]]
    reference_rows=arm_rows[ARMS[0]]
    if (not common or len(set(common))!=len(common) or set(labels)!=set(common)
            or len(common)!=observation['eval_records']):
        raise ValueError('heldout label denominator or identity changed')
    summaries={}
    for arm,rows in arm_rows.items():
        if not isinstance(rows,list) or [r.get('task_id') for r in rows]!=common:
            raise ValueError('incomplete/reordered conditional predictions')
        seen_groups={}
        correct=0;brier=0.
        for i,r in enumerate(rows):
            # Every arm must retain the same opaque sample/group/question
            # identities, not merely have the same count and matching IDs.
            if (r.get('source_group')!=reference_rows[i].get('source_group')
                    or r.get('question_slot')!=reference_rows[i].get('question_slot')):
                raise ValueError('per-arm question/source attribution changed')
            label=labels[r['task_id']]
            if (type(label) is not int or label not in (0,1)
                or type(r.get('question_slot')) is not int or r['question_slot'] not in (0,1)
                or not isinstance(r.get('source_group'),str)
                or not isinstance(r.get('logits'),list) or len(r['logits'])!=2
                or any(type(v) not in (int,float) or not math.isfinite(v) for v in r['logits'])):
                raise ValueError('untrusted heldout label/prediction')
            if r['weight_sha256']!=observation['fitting'][arm]['weights_digest']:
                raise ValueError('prediction weights changed from frozen candidate')
            group=r['source_group']
            if group not in observation['protocol']['eval_source_groups']:
                raise ValueError('training source contaminated final panel')
            p=_probabilities(r['logits'])
            win=int(max(range(2),key=lambda i:r['logits'][i])==label)
            correct+=win
            brier+=sum((p[i]-int(i==label))**2 for i in range(2))
            stats=seen_groups.setdefault(group,dict(total=0,correct=0))
            stats['total']+=1;stats['correct']+=win
        if set(seen_groups)!=set(observation['protocol']['eval_source_groups']) or any(v['total']!=8 for v in seen_groups.values()):
            raise ValueError('preregistered independent source-group denominator incomplete')
        summaries[arm]=dict(correct=correct,total=len(rows),accuracy=correct/len(rows),
            brier=brier/len(rows),by_group=seen_groups,
            group_count=len(seen_groups),
            statistical_superiority_established=False)
    # Counterfactual premise removal has no determinate 'correct answer'.
    # Report probability movement versus the original, not ablation accuracy.
    normal=arm_rows['conditioned']
    ablation=observation.get('ablation_predictions')
    if (not isinstance(ablation,list) or len(ablation)!=len(normal)
            or [v.get('task_id') for v in ablation]!=common):
        raise ValueError('complete paired evidence-removal observations required')
    relevant_changes=[];irrelevant_changes=[]
    for original,removed in zip(normal,ablation,strict=True):
        p=_probabilities(original['logits'])
        variants=[]
        for field in ('relevant_removed_logits','irrelevant_removed_logits'):
            values=removed.get(field)
            if not isinstance(values,list) or len(values)!=2 or any(type(z) not in (int,float) or not math.isfinite(z) for z in values):
                raise ValueError('untrusted ablation prediction')
            variants.append(_probabilities(values))
        relevant_changes.append(sum(abs(a-b) for a,b in zip(p,variants[0],strict=True))/2)
        irrelevant_changes.append(sum(abs(a-b) for a,b in zip(p,variants[1],strict=True))/2)
    sensitivity=dict(relevant_premise_probability_shift=sum(relevant_changes)/len(normal),
                     irrelevant_premise_probability_shift=sum(irrelevant_changes)/len(normal),
                     selectivity_difference=(sum(relevant_changes)-sum(irrelevant_changes))/len(normal),
                     actual_missing_premise_answer_accuracy=None,
                     selective_evidence_use_established=False)
    return dict(schema='hepta.conditioned-facts-evaluation.v1',
        observation_id=expected_observation_id,labels_sha256=expected_labels_sha256,
        results=summaries,evidence_removal_sensitivity=sensitivity,independent_research_data=False,
        condition_reading_winner_selected=False,
        subgroup_uniform_retention_established=False,
        real_world_qa_established=False,production_authorized=False)
