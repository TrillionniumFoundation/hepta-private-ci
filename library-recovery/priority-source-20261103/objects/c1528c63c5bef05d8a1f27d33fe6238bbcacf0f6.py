"""Strict statistical/metadata diagnostic for preregistered HCSN comparisons.

Four primary contrasts, at least 10 independent paired seeds, exact two-sided
sign-flip tests with Holm multiplicity adjustment, conservative Bonferroni
lower bound and practical magnitude. Frozen utility weights; full measured
CPU/Joules; matched information, active parameters, training budgets and local
value/slope. No metadata assertion is cryptographic proof of preregistration.

Research artifact only. No production admission is returned by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import itertools
import math
import re
from statistics import mean, stdev
from typing import Mapping, Any

from scipy.stats import t as student_t

CONTRASTS = ("call_vs_gate", "risk_vs_gate", "margin_vs_gate", "joint_vs_gate")
REQUIRED = {"seed", "batch_sha256", "candidate_quality", "baseline_quality",
            "candidate_active_params", "baseline_active_params", "candidate_train_cpu_s",
            "baseline_train_cpu_s", "candidate_worker_cpu_s", "baseline_worker_cpu_s",
            "candidate_energy_j", "baseline_energy_j", "candidate_local_value",
            "baseline_local_value", "candidate_local_slope", "baseline_local_slope",
            "same_optimizer", "same_head", "same_tokens", "both_actual_trainable"}
HEX64 = re.compile(r"[0-9a-f]{64}\Z")

@dataclass(frozen=True)
class ContrastResult:
    contrast: str
    n_seeds: int
    mean_net_utility_gain: float
    two_sided_exact_p: float
    holm_adjusted_p: float
    bonferroni_lower_95: float
    wins_practical_gate: bool


class ContractError(ValueError):
    """Fail closed on missing, incomparable or non-finite evidence."""


def _real(v: Any, field: str) -> float:
    if type(v) not in (int,float) or not math.isfinite(v):
        raise ContractError(f"{field} must be finite float/int, not bool")
    return float(v)


def _nonneg(v: Any, field: str) -> float:
    v=_real(v,field)
    if v<0:
        raise ContractError(f"{field} negative")
    return v


def _sha(v: Any, field: str) -> str:
    if type(v) is not str or not HEX64.fullmatch(v):
        raise ContractError(f"{field} must be lowercase sha256")
    return v


def _validate_pair(pair: Mapping, cpu_penalty: float, joule_penalty: float,
                   params_rel_tol: float, budget_rel_tol: float,
                   anchor_rel_tol: float) -> tuple[int,float]:
    if not isinstance(pair,dict) or set(pair)!=REQUIRED:
        raise ContractError(f"invalid paired-record keys: {sorted(REQUIRED-set(pair))}")
    seed=pair["seed"]
    if type(seed) is not int or seed < 0:
        raise ContractError("seed must be nonnegative integer")
    _sha(pair["batch_sha256"],"batch_sha256")
    for key in ("same_optimizer","same_head","same_tokens","both_actual_trainable"):
        if pair[key] is not True:
            raise ContractError(f"{key}: require explicit True with external receipt")

    q1=_real(pair["candidate_quality"],"candidate_quality")
    q0=_real(pair["baseline_quality"],"baseline_quality")
    if not (0<=q0<=1 and 0<=q1<=1):
        raise ContractError("quality must be in [0,1]")
    n1,n0=pair["candidate_active_params"],pair["baseline_active_params"]
    if type(n1) is not int or type(n0) is not int or n1<=0 or n0<=0:
        raise ContractError("effective trainable parameter count invalid")
    if abs(n1-n0) > params_rel_tol * max(n1,n0):
        raise ContractError("active parameters are not budget-matched")

    train1=_nonneg(pair["candidate_train_cpu_s"],"candidate_train_cpu_s")
    train0=_nonneg(pair["baseline_train_cpu_s"],"baseline_train_cpu_s")
    if min(train1,train0)<=0 or abs(train1-train0)>budget_rel_tol * max(train1,train0):
        raise ContractError("training CPU budget not matched")
    worker1=_nonneg(pair["candidate_worker_cpu_s"],"candidate_worker_cpu_s")
    worker0=_nonneg(pair["baseline_worker_cpu_s"],"baseline_worker_cpu_s")
    if worker1<train1 or worker0<train0:
        raise ContractError("worker CPU cannot be less than its nested train CPU")
    energy1=_nonneg(pair["candidate_energy_j"],"candidate_energy_j")
    energy0=_nonneg(pair["baseline_energy_j"],"baseline_energy_j")
    v1=_real(pair["candidate_local_value"],"candidate_local_value")
    v0=_real(pair["baseline_local_value"],"baseline_local_value")
    s1=_real(pair["candidate_local_slope"],"candidate_local_slope")
    s0=_real(pair["baseline_local_slope"],"baseline_local_slope")
    if (abs(v1-v0) > anchor_rel_tol*max(1.,abs(v0)) or
            abs(s1-s0) > anchor_rel_tol*max(1.,abs(s0)) or abs(s0)<1e-8):
        raise ContractError("local value and signed derivative not matched")
    # full-worker CPU already INCLUDES training CPU: never sum both.
    net1=q1-cpu_penalty*worker1-joule_penalty*energy1
    net0=q0-cpu_penalty*worker0-joule_penalty*energy0
    if not all(map(math.isfinite,(net1,net0))):
        raise ContractError("nonfinite net utility")
    return seed,net1-net0


def _exact_sign_flip_p(differences: list[float]) -> float:
    """Exhaustive null sign flips; assumes paired symmetric/exchangeable errors."""
    total=sum(differences)
    threshold=abs(total)-1e-13*max(1,abs(total))
    extremal=0
    for signs in itertools.product((-1,1),repeat=len(differences)):
        signed=sum(s*x for s,x in zip(signs,differences))
        extremal += abs(signed)>=threshold
    return extremal/(1<<len(differences))


def analyze(data: dict) -> tuple[ContrastResult,...]:
    """Return four diagnostic contrasts, NEVER a production activation verdict."""
    if type(data) is not dict or set(data)!={"schema","protocol","contrasts"}:
        raise ContractError("invalid top-level P1 schema")
    if data['schema']!='hcsn-p1-paired-v1':
        raise ContractError("unsupported P1 schema")
    p=data['protocol']
    required={"source_sha","protocol_sha256","train_dataset_sha256","holdout_sha256",
              "cpu_penalty", "joule_penalty", "practical_gain", "frozen_before_holdout",
              "holdout_access_prohibited_pre_registration"}
    if type(p) is not dict or set(p)!=required:
        raise ContractError("missing P1 protocol fields")
    if type(p['source_sha']) is not str or not re.fullmatch(r'[0-9a-f]{40}',p['source_sha']):
        raise ContractError("source commit sha invalid")
    for key in ('protocol_sha256','train_dataset_sha256','holdout_sha256'):
        _sha(p[key],key)
    if (p['frozen_before_holdout'] is not True or
            p['holdout_access_prohibited_pre_registration'] is not True):
        raise ContractError("fresh preregistration declarations required")
    cpu_penalty=_nonneg(p['cpu_penalty'],'cpu_penalty')
    joule_penalty=_nonneg(p['joule_penalty'],'joule_penalty')
    practical=_real(p['practical_gain'],'practical_gain')
    if practical<=0:
        raise ContractError('positive practical gain required')
    c=data['contrasts']
    if type(c) is not dict or set(c)!=set(CONTRASTS):
        raise ContractError("exact four primary contrasts required")
    samples={}
    seed_set=None
    digest_set=None
    for key in CONTRASTS:
        cohort=c[key]
        if type(cohort) is not list or not 10<=len(cohort)<=16:
            raise ContractError("require 10..16 independent paired seeds per contrast")
        paired={}
        digests={}
        for pair in cohort:
            seed,gain=_validate_pair(pair,cpu_penalty,joule_penalty,.03,.01,1e-4)
            if seed in paired:
                raise ContractError(f"duplicate seed {seed}")
            paired[seed]=gain
            digests[seed]=pair['batch_sha256']
        if seed_set is not None and set(paired)!=seed_set:
            raise ContractError("four contrasts must use identical seed panel")
        if digest_set is not None and digests!=digest_set:
            raise ContractError("batch stream digest changes between contrast panels")
        seed_set=set(paired)
        digest_set=digests
        samples[key]=[paired[seed] for seed in sorted(paired)]

    pvals=[_exact_sign_flip_p(samples[k]) for k in CONTRASTS]
    # Holm step-down family-wise correction, monotonic adjusted p-values.
    adjusted=[None]*len(CONTRASTS)
    floor=0.
    for rank,index in enumerate(sorted(range(len(pvals)),key=pvals.__getitem__)):
        floor=max(floor, min(1.,(len(pvals)-rank)*pvals[index]))
        adjusted[index]=floor
    results=[]
    for i,key in enumerate(CONTRASTS):
        delta=samples[key]
        se=stdev(delta)/math.sqrt(len(delta))
        # Conservative simultaneous 95% one-sided lower bounds across four
        # contrasts (Bonferroni). Not a guarantee against dataset selection.
        lower=mean(delta)-float(student_t.ppf(1-.05/len(CONTRASTS),len(delta)-1))*se
        results.append(ContrastResult(
            contrast=key,n_seeds=len(delta),mean_net_utility_gain=mean(delta),
            two_sided_exact_p=pvals[i],holm_adjusted_p=adjusted[i],
            bonferroni_lower_95=lower,
            wins_practical_gate=bool(adjusted[i]<=.05 and lower>practical)))
    return tuple(results)
