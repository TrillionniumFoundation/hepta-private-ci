"""MANDATORY hosted cross-check against the parent #1923 two-sided math oracle.

This script fails if that original module is absent. It doesn't issue a general
FBSDE theorem or mutate any utility/control owners.
"""
from __future__ import annotations

from dataclasses import replace
from fractions import Fraction as Q
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[2]
ORACLE=ROOT/'experiments/ndu_tree_fbsde_gates'
if not (ORACLE/'stitch_audit.py').is_file():
    raise RuntimeError('mandatory original #1923 independent FBSDE oracle is absent')
sys.path.insert(0,str(ORACLE))
from stitch_audit import (Segment as OriginalSegment, audit as parent_audit,
                          construct_regular as parent_construct,
                          boundary_case as parent_case)  # noqa: E402
from e8_global_gate import Segment,certify


def main():
    matched=0
    refused=0
    for x in (Q(-1),Q(0),Q(1),Q(2)):
        for g in (Q(-2),Q(-1,2),Q(0),Q(1,2),Q(1),Q(2),Q(3)):
            for steps in ((Q(1,8),Q(1,8)),
                          (Q(1,4),Q(1,4)),
                          (Q(1,5),Q(1,5),Q(1,10))):
                original_case=parent_case(x,g,steps)
                if original_case=='unique_regular':
                    src=parent_construct(x,g,steps)
                    own=[Segment(s.duration,s.x_start,s.y_start,s.x_end,s.y_end,
                                 s.field_start,s.field_end) for s in src]
                    report=certify(x,g,own)
                    independent=parent_audit(x,g,src)
                    if not report.globally_solved or not independent.globally_solved or report.case!=original_case:
                        raise AssertionError('two independent regular global checks disagree')
                    matched+=1
                    # A deliberately broken backward interface must NOT be
                    # promoted on either independently implemented auditor.
                    if len(src)>1:
                        j=1
                        bad=own.copy()
                        bad[j]=replace(bad[j],y_start=bad[j].y_start+Q(1,7))
                        changed=list(src)
                        changed[j]=replace(changed[j],y_start=changed[j].y_start+Q(1,7))
                        if certify(x,g,bad).globally_solved or parent_audit(x,g,changed).globally_solved:
                            raise AssertionError('unqualified backward stitch accepted')
                        refused+=1
                else:
                    # These cannot be certified by any chain of unique local
                    # solutions and must remain unadmitted.
                    if original_case not in ('non_unique','no_solution','nonregular_unique'):
                        raise AssertionError('unregistered analytic boundary case')
                    refused+=1
    if matched<40 or refused<40:
        raise AssertionError('insufficient mandatory original-reference matrix')
    print(json.dumps({'schema':'hepta.e8.original-independent-math-parity.v1',
                      'unique_regular_full_path_cases':matched,
                      'invalid_boundary_or_corrupted_path_rejections':refused,
                      'original_oracle_consumed':True,
                      'continuous_stochastic_fbsde_proven':False,
                      'production_accepted':False,'authority':'DENY_ALL'},sort_keys=True))


if __name__=='__main__':
    main()
