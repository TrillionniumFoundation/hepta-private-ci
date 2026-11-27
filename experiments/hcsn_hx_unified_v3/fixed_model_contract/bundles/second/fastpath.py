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
MODEL_DIGEST='2cc8f255028d24d8f1c40f824a58bb5ed02b2999e482e46e259cdd3d0c27cfa2'
EXACT_PARAMETERS={'coupon': '4', 'maturity': '3', 'payout': '2/25', 'principal': '60', 'rate': '1/20', 'recovery': '3/20', 'sale_fraction': '2/25', 'shock_intensity': '1', 'tax_shield': '1/4', 'volatility': '1/4'}
CONTRACT_SHA256='b7a16b4c9642dc3f41dc5bd138b453f776c596302891f455657111c9b51108e9'
MODEL='HX exact rational model sha256:2cc8f255028d24d8f1c40f824a58bb5ed02b2999e482e46e259cdd3d0c27cfa2'
VMIN=float.fromhex('0x1.8c994f12d7e11p+6')
VMAX=float.fromhex('0x1.8c9980a604dc9p+6')
BHI=float.fromhex('0x1.8c994f12d7e11p+6')
BLO=float.fromhex('-0x1.87ce85b237dffp-50')
C2=float.fromhex('0x1.0d9b65ad29e42p-6')
C3=float.fromhex('-0x1.87ab6ed5c91e1p-13')
C4=float.fromhex('0x1.d311ff8114ddfp-20')
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
