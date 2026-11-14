"""Generated single-model research fast path.
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
VMIN=float.fromhex('0x1.8c994f12d7e11p+6')
VMAX=float.fromhex('0x1.8c9980a604dc9p+6')
BHI=float.fromhex('0x1.8c994f12d7e11p+6')
BLO=float.fromhex('-0x1.87ce85b237dffp-50')
C2=float.fromhex('0x1.0d9b65ad29e42p-6')
C3=float.fromhex('-0x1.87ab6ed5c91e1p-13')
C4=float.fromhex('0x1.d311ff8114ddfp-20')
EXACT_PARAMETERS={'rate': '1/20', 'payout': '2/25', 'volatility': '1/4', 'maturity': '3', 'principal': '60', 'coupon': '4', 'tax_shield': '1/4', 'recovery': '3/20', 'shock_intensity': '1', 'sale_fraction': '2/25'}
RELATIVE_ERROR_BOUND=2.0**-49
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
