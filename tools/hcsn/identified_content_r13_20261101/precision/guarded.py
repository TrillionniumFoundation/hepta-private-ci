"""Explicit diagnostics/fallback wrapper, separate from the frozen DS kernel.

mixed_check=True always executes FP64 and is NEVER a pure-FP32/DS call, even
when it returns the preferred result. Agreement is an error diagnostic, not
a certified error bound. The unchanged acceptance gates are not widened.
"""

from pathlib import Path
import sys

import numpy as np

import ds_kernel

OLD=Path(__file__).resolve().parents[2]/"unified_cell_r12_20261031"/"numerics"
sys.path.insert(0,str(OLD))
import stable32


def diagnostics(values,jacobian):
    if not np.isfinite(values).all() or not np.isfinite(jacobian).all():
        return ['nonfinite value or Jacobian']
    b,e,f,g,debt=values
    issues=[]
    if b<=0 or e < -np.float32(8e-7)*max(np.float32(1),abs(b)) or debt<0:
        issues.append('negative boundary/equity/debt invariant')
    if not (-8e-7<=g<=f+8e-7 and f<=1+8e-7 and f>=-8e-7):
        issues.append('first-passage probability invariant')
    return issues


def discrepancy(a,b):
    # Guard/report arithmetic is explicitly FP64, independently of kernel mode.
    a,b=np.asarray(a,np.float64),np.asarray(b,np.float64)
    return float(np.max(np.abs(a-b)/np.maximum(1,np.abs(b))))


def evaluate(theta,state,*,coordinate='log_distance',prefer='double_single',
             mixed_check=False,allow_fallback=True,diagnostic_outside_box=False):
    if prefer not in ('single32','double_single','mixed64'):
        raise ValueError('Unknown preferred backend')
    kwargs=dict(coordinate=coordinate,diagnostic_outside_box=diagnostic_outside_box)
    metadata=dict(preferred=prefer,mixed_executed=prefer=='mixed64',fallback=False,
                  validation='computable diagnostics, not a uniform numerical certificate')
    control=None
    try:
        if prefer=='double_single':
            values,jacobian=ds_kernel.evaluate(theta,state,**kwargs)
        else:
            values,jacobian=stable32.evaluate(theta,state,
                mode='float32' if prefer=='single32' else 'mixed32',candidate=prefer=='single32',**kwargs)
        issues=diagnostics(values,jacobian)
    except (ValueError,ArithmeticError) as exc:
        issues=[str(exc)]
    if mixed_check and prefer!='mixed64':
        control=stable32.evaluate(theta,state,mode='mixed32',candidate=False,**kwargs)
        metadata['mixed_executed']=True
        if not issues:
            ve,je=discrepancy(values,control[0]),discrepancy(jacobian,control[1])
            metadata.update(value_discrepancy_to_mixed=ve,jacobian_discrepancy_to_mixed=je)
            if ve>4e-7 or je>1e-5:
                issues.append('disagreement with mixed64 exceeds half of unchanged gates')
    if issues:
        if not allow_fallback or prefer=='mixed64':
            raise ArithmeticError('; '.join(issues))
        if control is None:
            control=stable32.evaluate(theta,state,mode='mixed32',candidate=False,**kwargs)
        values,jacobian=control
        if diagnostics(values,jacobian):
            raise ArithmeticError('Explicit mixed fallback also failed diagnostics')
        metadata.update(mixed_executed=True,fallback=True,fallback_reason=issues)
    metadata['returned_backend']='mixed64' if metadata['fallback'] else prefer
    metadata['whole_call_precision']='contains_FP64' if metadata['mixed_executed'] else (
        'two_FP32_kernel_with_host_diagnostics' if prefer=='double_single' else 'single_FP32_kernel_with_host_diagnostics')
    return values,jacobian,metadata
