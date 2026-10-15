"""Strict retrospective paired accuracy and calibration diagnostics, no authority.

Identical IDs and public retrospective groups are not independent future NDU.
Unadjusted exact McNemar p-values never independently select a Stem.
"""
from __future__ import annotations

import math


class Invalid(ValueError):
    pass


def _prob(v):
    if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1:
        raise Invalid("invalid original per-case probability")
    return float(v)


def paired(rows: list[dict], left: dict, right: dict) -> dict:
    if (type(rows) is not list or not 1<=len(rows)<=100000
            or type(left) is not dict or type(right) is not dict):
        raise Invalid("missing bounded original case population")
    ids=[];groups=set()
    for row in rows:
        if type(row) is not dict:
            raise Invalid("malformed source row")
        cid=row.get("case_id")
        label=row.get("label")
        if (type(cid) is not str or not cid or len(cid)>128
                or type(label) is not int or label not in (0,1)):
            raise Invalid("nonbinary source or invalid ID")
        ids.append(cid)
        group=row.get("source_group",row.get("group_id"))
        if type(group) is not str or not group:
            raise Invalid("missing source group declaration")
        groups.add(group)
    if len(ids)!=len(set(ids)) or set(left)!=set(ids) or set(right)!=set(ids):
        raise Invalid("paired original source coverage mismatch")
    lonly=ronly=both=neither=0
    lb=rb=0.0
    for row in rows:
        key,label=row["case_id"],row["label"]
        lp,rp=_prob(left[key]),_prob(right[key])
        lc,rc=int(lp>=.5)==label,int(rp>=.5)==label
        both+=int(lc and rc)
        neither+=int(not lc and not rc)
        lonly+=int(lc and not rc)
        ronly+=int(rc and not lc)
        lb+=(lp-label)**2
        rb+=(rp-label)**2
    ndisc=lonly+ronly
    if ndisc:
        # Avoid overflow/underflow: the E2 test is exactly 64 cases.
        term=math.ldexp(1.0,-ndisc) if ndisc<1074 else 0.0
        if term==0.0:
            raise Invalid("unbounded discordance for exact McNemar")
        tail=term
        for k in range(min(lonly,ronly)):
            term*=(ndisc-k)/(k+1)
            tail+=term
        p=min(1.0,2.0*tail)
    else:
        p=1.0
    n=len(rows)
    return {
        "paired_cases":n,
        "reported_source_groups_not_independent":len(groups),
        "left_only_correct":lonly,"right_only_correct":ronly,
        "both_correct":both,"both_wrong":neither,
        "left_accuracy":(both+lonly)/n,
        "right_accuracy":(both+ronly)/n,
        "left_minus_right_accuracy":(lonly-ronly)/n,
        "left_brier":lb/n,"right_brier":rb/n,
        "left_minus_right_brier":(lb-rb)/n,
        "exact_mcnemar_two_sided_unadjusted_p":p,
        "future_or_source_independence_verified":False,
        "multiple_comparison_adjustment_applied":False,
        "independent_ndu_benefit_verified":False,
        "statistical_stem_winner_selected":False,
        "authority":"DENY_ALL",
    }
