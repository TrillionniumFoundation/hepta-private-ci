import json,hashlib
from pathlib import Path
from flint import arb
from oracle import EXACT
R=Path(__file__).resolve().parent
p=json.loads((R/'COEFFICIENTS.json').read_text())
assert p['status']=='UNIFORM_BOUND_ESTABLISHED_UNDER_IEEE_RN_PREMISES'
assert p['exact_params']==EXACT, 'Coefficient receipt does not match frozen exact model'
root=json.loads((R/'ROOT_PROOF.json').read_text())
assert root['status']=='FIXED_CASE_ROOT_AND_GUARD_ENCLOSED'
assert root['exact_rational_inputs']==EXACT, 'Root proof does not match frozen exact model'
assert all(row['required_sign_verified'] for row in root['endpoints'])
assert p['global_status']=='NOT_CERTIFIED'
assert arb(p['relative_error_upper'])<arb(2)**(-49)
code='''"""Generated single-model research fast path.
Uniform relative error <=2^-49 under trusted CPython IEEE binary64 RN ties-even,
no rounding-mode mutation or fast-math. Not a universal runtime certificate.
No Arb, log, exp, special functions or per-call numerical oracle.
"""
import sys
if sys.implementation.name != 'cpython' or (sys.float_info.radix,sys.float_info.mant_dig,sys.float_info.max_exp,sys.float_info.min_exp,sys.float_info.rounds)!=(2,53,1024,-1021,1):
    raise RuntimeError('Unsupported floating runtime')
# Smoke probes do not replace the stated fixed-rounding-mode premise.
_one=1.0;_u=2.0**-53
if not (_one+_u==_one and _one+3*_u==1.0000000000000004):
    raise RuntimeError('Nearest-even rounding probe failed')
'''
for name,key in [('VMIN','asset_lower_hex'),('VMAX','asset_upper_hex'),('BHI','root_hi_hex'),('BLO','root_lo_hex')]:
 code+=f'{name}=float.fromhex({p[key]!r})\n'
for name,value in zip(('C2','C3','C4'),p['coefficients_hex']):code+=f'{name}=float.fromhex({value!r})\n'
code+=f'EXACT_PARAMETERS={p["exact_params"]!r}\n'
code+='''RELATIVE_ERROR_BOUND=2.0**-49
MODEL='second frozen exact rational HX model at exact smoothfit root; see EXACT_PARAMETERS'
def equity(asset):
    if type(asset) is not float or not VMIN<=asset<=VMAX:
        raise ValueError('Outside certified fixed-model binary64 asset interval')
    gap_hi=asset-BHI
    w=gap_hi-BLO
    h0=C4*w
    h1=h0+C3
    h2=h1*w
    h3=h2+C2
    square=w*w
    result=square*h3
    if not result>0.0:
        raise ArithmeticError('Runtime violated positive-result proof premises')
    return result
'''
(R/'fastpath.py').write_text(code)
print(hashlib.sha256(code.encode()).hexdigest())
