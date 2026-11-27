"""Generated fixed-model local research path, identified by canonical parameters.
Uniform relative error <=2^-49 only under trusted CPython IEEE binary64 RN
premises, unchanged rounding mode and operation order. Digests are identity
labels, not signatures, authentication or hostile-artifact safety proofs.
"""
import sys
if sys.implementation.name != 'cpython' or (sys.float_info.radix,sys.float_info.mant_dig,sys.float_info.max_exp,sys.float_info.min_exp,sys.float_info.rounds)!=(2,53,1024,-1021,1):
    raise RuntimeError('Unsupported floating runtime')
_one=1.0;_u=2.0**-53
if not (_one+_u==_one and _one+3*_u==1.0000000000000004):
    raise RuntimeError('Nearest-even rounding probe failed')
SCHEMA_VERSION='hx-fixed-model-bundle-v1'
PROOF_VERSION='hx-local-taylor4-ieee-rn-v1'
MODEL_DIGEST='ff595d678287a1d75a59f593214fd87f052b9ca348aa28a184721ef6241915c1'
EXACT_PARAMETERS={'coupon': '4', 'maturity': '2', 'payout': '3/100', 'principal': '60', 'rate': '1/20', 'recovery': '3/5', 'sale_fraction': '3/200', 'shock_intensity': '1', 'tax_shield': '1/4', 'volatility': '1/4'}
CONTRACT_SHA256='048deaef192b34af5bccb41cd45e506284aa444a21486b184686c6b3bc622638'
MODEL='HX exact rational model sha256:ff595d678287a1d75a59f593214fd87f052b9ca348aa28a184721ef6241915c1'
VMIN=float.fromhex('0x1.02802e507a1c7p+6')
VMAX=float.fromhex('0x1.02804ea081eb7p+6')
BHI=float.fromhex('0x1.02802e507a1c6p+6')
BLO=float.fromhex('0x1.bf8ab8d9451a7p-48')
C2=float.fromhex('0x1.6e5d964ff3313p-5')
C3=float.fromhex('-0x1.2e08460774ffap-10')
C4=float.fromhex('0x1.752608a071c15p-16')
RELATIVE_ERROR_BOUND=2.0**-49
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
