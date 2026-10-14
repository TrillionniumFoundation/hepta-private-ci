"""One scoped evidence Encoder forward, several distinct question-conditioned Readers.

Research-only, CPU FP32 eager profile. Evidence token states are kept only during
ONE call. Every question still gets its own fresh, charged query representation
and Reader forward. Unlike exact-view sharing, this *permits different questions*
but requires the identical immutable evidence, scope and frozen snapshot.

This provides an interface and a falsifiable sufficiency experiment; it does NOT
establish that a pooled/text Encoder contains enough information for every task.
No final labels, model loading, persistence, cross-scope cache or production grants.
"""
from __future__ import annotations

import hashlib
import math
import time
import contextlib
from dataclasses import dataclass

import torch
from torch import nn

from execution_meter import WorkLedger, validate_policy
from matrix_bank import state_digest
from next_round_matrix import _digest
from paired_execution import PHASES


@dataclass(frozen=True)
class Evidence:
    principal: str
    document_id: str
    text: str
    available_at_ns: int
    checkpoint_sha256: str


@dataclass(frozen=True)
class Question:
    task_id: str
    principal: str
    evidence_digest: str
    text: str
    options: tuple[str, ...]
    available_at_ns: int
    reader: nn.Module


def evidence_digest(evidence):
    if not isinstance(evidence, Evidence):
        raise ValueError("typed immutable evidence required")
    for value in (evidence.principal, evidence.document_id, evidence.text):
        if not isinstance(value, str) or not value or len(value.encode()) > 65536:
            raise ValueError("bounded nonempty evidence fields required")
    if (type(evidence.available_at_ns) is not int or evidence.available_at_ns < 1
            or not isinstance(evidence.checkpoint_sha256, str)
            or len(evidence.checkpoint_sha256) != 64
            or any(c not in "0123456789abcdef" for c in evidence.checkpoint_sha256)):
        raise ValueError("causal evidence time and pinned checkpoint required")
    return _digest(dict(principal=evidence.principal, document_id=evidence.document_id,
                        text=evidence.text, available_at_ns=evidence.available_at_ns,
                        checkpoint_sha256=evidence.checkpoint_sha256))


def admit_questions(evidence, questions, *, max_cells=4096, as_of_ns):
    digest = evidence_digest(evidence)
    if type(as_of_ns) is not int or as_of_ns < evidence.available_at_ns:
        raise ValueError("future evidence is not available")
    if not isinstance(questions, (list, tuple)) or not 1 <= len(questions) <= 128:
        raise ValueError("bounded, nonempty question group required")
    if type(max_cells) is not int or not 1 <= max_cells <= 4096:
        raise ValueError("bounded logical Cell ceiling required")
    seen, readers, storages, cell_count = set(), set(), set(), 0
    for job in questions:
        if not isinstance(job, Question):
            raise ValueError("typed query/Reader slot required")
        if (not isinstance(job.task_id, str) or not 1 <= len(job.task_id) <= 128
                or job.task_id in seen or job.principal != evidence.principal
                or job.evidence_digest != digest or not isinstance(job.text, str)
                or not job.text or len(job.text.encode()) > 8192):
            raise ValueError("duplicate task, cross-principal, mismatched evidence or invalid question")
        if (not isinstance(job.options, tuple) or not 2 <= len(job.options) <= 16
                or any(not isinstance(x, str) or not x or len(x.encode()) > 4096 for x in job.options)
                or type(job.available_at_ns) is not int
                or not evidence.available_at_ns <= job.available_at_ns <= as_of_ns):
            raise ValueError("ordered options or availability boundary invalid")
        if not isinstance(job.reader, ConditionedReader) or id(job.reader) in readers or job.reader.training:
            raise ValueError("one frozen-eval independent Reader per question required")
        for p in job.reader.parameters():
            if p.device.type != "cpu" or p.dtype != torch.float32 or not torch.isfinite(p).all().item():
                raise ValueError("finite CPU FP32 Reader weights required")
            identity = (str(p.device), p.untyped_storage().data_ptr())
            if identity in storages:
                raise ValueError('Reader parameters alias another question owner')
            storages.add(identity)
        if job.reader.classes != len(job.options):
            raise ValueError("Reader legal-option width mismatch")
        cell_count += 1
        if cell_count > max_cells:
            raise ValueError("logical Cell cap exceeded")
        seen.add(job.task_id)
        readers.add(id(job.reader))
    return digest


class ConditionedReader(nn.Module):
    """Trainable small query-to-token cross-attention over frozen evidence states.

    Token-level evidence is essential here: plain mean pooling can eliminate
    which fact belongs to which query even if it has equal output dimensionality.
    Identity initialization is merely a research starting point, not a claim of
    aligned pretrained question/key geometry or a trained cross-attention layer.
    """
    def __init__(self, width, classes):
        super().__init__()
        if type(width) is not int or not 2 <= width <= 8192 or type(classes) is not int or not 2 <= classes <= 16:
            raise ValueError("bounded Reader shape required")
        self.width, self.classes = width, classes
        self.query = nn.Linear(width, width, bias=False)
        self.keys = nn.Linear(width, width, bias=False)
        self.classifier = nn.Linear(width, classes)
        with torch.no_grad():
            nn.init.eye_(self.query.weight)
            nn.init.eye_(self.keys.weight)

    def forward(self, evidence_states, question_vector):
        if (not isinstance(evidence_states, torch.Tensor)
                or evidence_states.ndim != 2 or not 1 <= len(evidence_states) <= 4096
                or evidence_states.shape[1] != self.width
                or not isinstance(question_vector, torch.Tensor)
                or question_vector.shape != (self.width,)
                or any(x.device.type != 'cpu' or x.dtype != torch.float32
                       or not torch.isfinite(x).all().item()
                       for x in (evidence_states,question_vector))):
            raise ValueError("bounded CPU FP32 token states and query required")
        keys = self.keys(evidence_states)
        q = self.query(question_vector.unsqueeze(0))
        attention = torch.softmax(torch.mm(q, keys.t()), dim=1)
        pooled = torch.mm(attention, evidence_states)
        return self.classifier(pooled)[0]


@dataclass(frozen=True)
class TrainingCase:
    evidence: torch.Tensor
    question: torch.Tensor
    target: int
    source_group: str
    label_available_at_ns: int


def fit_reader(reader, cases, *, cutoff_ns, steps=128, learning_rate=.03, seed=7347, meter=None):
    """Train a candidate copy; never accept evaluation labels in this API.

    Source groups are retained to support later group-disjoint evaluation; a
    unique label timestamp before cutoff is required for every training row.
    This function does NOT issue a future-task generalization qualification.
    """
    import copy
    if (not isinstance(reader, ConditionedReader) or not isinstance(cases, list)
            or not 1 <= len(cases) <= 2048 or type(cutoff_ns) is not int or cutoff_ns <= 0
            or type(steps) is not int or not 1 <= steps <= 1024
            or type(seed) is not int or seed <= 0
            or type(learning_rate) not in (float,int)
            or not 0 < learning_rate <= .2):
        raise ValueError("admitted training contract required")
    groups=set()
    for case in cases:
        if (not isinstance(case, TrainingCase) or type(case.target) is not int
                or not 0 <= case.target < reader.classes
                or not isinstance(case.source_group,str) or not case.source_group
                or type(case.label_available_at_ns) is not int
                or not 0 < case.label_available_at_ns <= cutoff_ns
                or case.evidence.requires_grad or case.question.requires_grad):
            raise ValueError("training-only observations and frozen evidence required")
        if (not isinstance(case.evidence, torch.Tensor)
                or not isinstance(case.question, torch.Tensor)
                or case.evidence.ndim != 2 or not 1 <= len(case.evidence) <= 4096
                or case.evidence.shape[1] != reader.width or case.question.shape != (reader.width,)
                or case.evidence.device.type != 'cpu' or case.question.device.type != 'cpu'):
            raise ValueError("training geometry changed")
        if (case.evidence.dtype != torch.float32 or case.question.dtype != torch.float32
                or not torch.isfinite(case.evidence).all().item()
                or not torch.isfinite(case.question).all().item()):
            raise ValueError("nonfinite training features")
        groups.add(case.source_group)
    model=copy.deepcopy(reader).requires_grad_(True)
    generator=torch.Generator(device='cpu').manual_seed(seed)
    meter_scope = meter.scope('train', 'bank') if meter is not None else contextlib.nullcontext()
    with meter_scope:
        optimizer=torch.optim.AdamW(model.parameters(), lr=learning_rate)
        model.train()
        for _ in range(steps):
            index=int(torch.randint(len(cases),(1,),generator=generator).item())
            item=cases[index]
            optimizer.zero_grad(set_to_none=True)
            output=model(item.evidence,item.question).unsqueeze(0)
            target=torch.tensor([item.target],dtype=torch.long)
            loss=nn.functional.cross_entropy(output,target)
            if not torch.isfinite(loss).item():
                raise ValueError('nonfinite candidate loss')
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(),1.)
            optimizer.step()
    if any(not torch.isfinite(p).all().item() for p in model.parameters()):
        raise ValueError("nonfinite trained Reader")
    model.eval()
    trained_observation=meter.report() if meter is not None else None
    return model,dict(schema='hepta.conditioned-reader-training.v1',
                      steps=steps, examples_seen=steps, source_group_count=len(groups),
                      trainable_parameters=sum(p.numel() for p in model.parameters()),
                      retained_encoder_parameters=0,
                      observed_training_aten_formula_flops=(trained_observation['phase_flops']['train']
                          if trained_observation is not None else None),
                      meter_observation=trained_observation,
                      prospective_evidence_sufficiency_established=False,
                      independent_task_gain_established=False,production_authorized=False)


def _validate_states(states, *, width, limit):
    if (not isinstance(states,torch.Tensor) or states.ndim != 2
            or not 1 <= states.shape[0] <= 4096 or states.shape[1] != width
            or states.device.type != 'cpu' or states.dtype != torch.float32
            or states.requires_grad or not torch.isfinite(states).all().item()
            or states.untyped_storage().nbytes() > limit):
        raise ValueError("frozen token-level evidence exceeds source/size boundary")


def _run(evidence_encoder, query_encoder, evidence, questions, policy, caps, *, shared,
         max_evidence_bytes, checkpoint_sha, identity):
    meter=WorkLedger(policy,caps)
    reader_before=[state_digest(x.reader) for x in questions]
    outputs, encoder_calls, query_calls= [],0,0
    wall_started=time.perf_counter_ns()
    states=None
    with torch.inference_mode():
        for job in questions:
            if states is None:
                with meter.scope('inference','encoder'):
                    encoder_calls += 1
                    states=evidence_encoder(evidence)
                    _validate_states(states,width=job.reader.width,limit=max_evidence_bytes)
            with meter.scope('inference','material'):
                query_calls+=1
                q=query_encoder(job.text,job.options)
                if (not isinstance(q,torch.Tensor) or q.shape!=(job.reader.width,)
                    or q.dtype!=torch.float32 or q.device.type!='cpu'
                    or q.requires_grad or not torch.isfinite(q).all().item()
                    or q.untyped_storage().nbytes()>max_evidence_bytes):
                    raise ValueError('invalid bounded question representation')
            with meter.scope('inference','bank'):
                out=job.reader(states,q)
                if not torch.isfinite(out).all().item():
                    raise ValueError('nonfinite Reader output')
                outputs.append(out.detach().clone().tolist())
            if not shared:
                states=None
    if evidence_digest(evidence)!=identity or evidence.checkpoint_sha256!=checkpoint_sha:
        raise ValueError('Encoder source identity changed')
    if [state_digest(x.reader) for x in questions]!=reader_before:
        raise ValueError('question Reader parameters mutated')
    observed=meter.report()
    return dict(schema='hepta.conditioned-evidence-execution.v1',
                role='shared' if shared else 'repeat-evidence',
                encoder_calls=encoder_calls,query_calls=query_calls,
                reader_calls=len(questions),outputs=outputs,
                formula_flops=observed['phase_flops']['inference'],
                work_observation=observed,
                wall_ns_instrumented=time.perf_counter_ns()-wall_started)


def compare_conditioned(evidence_encoder, query_encoder, evidence, questions, *, policy, caps=None,
                        as_of_ns, max_evidence_bytes=8*1024*1024,
                        atol=1e-6,rtol=1e-6):
    validate_policy(policy)
    identity=admit_questions(evidence,questions,as_of_ns=as_of_ns)
    if (type(max_evidence_bytes) is not int or not 128 <= max_evidence_bytes<=256*1024*1024
        or type(atol) not in (int,float) or type(rtol) not in (int,float)
        or any(not math.isfinite(t) or not 0 <= t <= 1e-3 for t in (atol,rtol))):
        raise ValueError('bounded memory and numeric tolerances required')
    if caps is None:
        caps=dict.fromkeys(PHASES,10**13)
    if not isinstance(caps,dict) or set(caps)!=set(PHASES) or any(type(v) is not int or v<0 for v in caps.values()):
        raise ValueError('complete nonnegative phase budgets required')
    frozen=tuple(x.reader.training for x in questions)
    shared=_run(evidence_encoder,query_encoder,evidence,questions,policy,caps,
                shared=True,max_evidence_bytes=max_evidence_bytes,
                checkpoint_sha=evidence.checkpoint_sha256,identity=identity)
    repeated=_run(evidence_encoder,query_encoder,evidence,questions,policy,caps,
                  shared=False,max_evidence_bytes=max_evidence_bytes,
                  checkpoint_sha=evidence.checkpoint_sha256,identity=identity)
    if tuple(x.reader.training for x in questions)!=frozen:
        raise ValueError('Reader state changed across conditions')
    err=0.
    for left,right in zip(shared['outputs'],repeated['outputs'],strict=True):
        for a,b in zip(left,right,strict=True):
            err=max(err,abs(a-b))
            if abs(a-b)>atol+rtol*abs(b):
                raise ValueError('shared evidence changed question-conditioned logits')
    if shared['encoder_calls']!=1 or repeated['encoder_calls']!=len(questions):
        raise ValueError('incomplete actual Encoder call comparison')
    savings=(repeated['formula_flops']-shared['formula_flops']
            if repeated['formula_flops'] is not None and shared['formula_flops'] is not None else None)
    return dict(schema='hepta.conditional-evidence-shared-comparison.v1',
                evidence_sha256=identity,principal_sha256=hashlib.sha256(evidence.principal.encode()).hexdigest(),
                checkpoint_sha256=evidence.checkpoint_sha256,
                question_count=len(questions), task_ids=[x.task_id for x in questions],
                shared=shared,repeated=repeated,max_logit_abs_difference=err,
                formula_work_saved=savings,
                formula_work_saved_fraction=(savings/repeated['formula_flops']
                    if savings is not None and repeated['formula_flops'] else None),
                distinct_questions_allowed_same_evidence=True,
                stored_between_requests=False,
                cross_principal_reuse_allowed=False,
                conditional_reader_accuracy_established=False,
                independent_question_answering_established=False,
                target_device_latency_speedup_established=False,
                full_system_energy_established=False, production_authorized=False)
