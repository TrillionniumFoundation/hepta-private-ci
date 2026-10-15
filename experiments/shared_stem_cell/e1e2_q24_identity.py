"""Cross-E1/E2 frozen Q24 feature identity; no model-origin or training attestation."""
from __future__ import annotations
import hashlib
import json
import math
import struct

Q24=1<<24
WIDTHS=(256,384)
class Invalid(ValueError):pass

def _id(value):
    if (type(value) is not str or not 1 <= len(value) <= 128 or
            any(not(c.isascii() and (c.isalnum() or c in '._:-')) for c in value)):
        raise Invalid('invalid feature case identifier')
    return value

def feature_digest(case_id, feature):
    _id(case_id)
    if type(feature) not in (tuple,list) or len(feature) not in WIDTHS:
        raise Invalid('wrong native feature width')
    packed=bytearray()
    for value in feature:
        if type(value) not in (int,float) or not math.isfinite(value) or abs(value)>8:
            raise Invalid('nonfinite/out-of-domain Q24 input')
        integer=round(value*Q24)
        packed.extend(struct.pack('<q',integer))
    content=(b'hepta.e1e2.case-q24.v1\0'+case_id.encode('ascii')+b'\0'+
             struct.pack('<H',len(feature))+bytes(packed))
    return hashlib.sha256(content).hexdigest()

def feature_inventory(case_ids,features):
    if type(case_ids) not in (list,tuple) or not case_ids or len(case_ids)>50000:
        raise Invalid('bounded exact case inventory required')
    ids=[_id(x) for x in case_ids]
    if len(ids)!=len(set(ids)) or type(features) is not dict or set(features)!=set(ids):
        raise Invalid('feature bank case coverage mismatch')
    widths={len(features[x]) for x in ids if type(features[x]) in (list,tuple)}
    if len(widths)!=1 or next(iter(widths)) not in WIDTHS:
        raise Invalid('mismatched Q24 feature widths')
    case_digests={x:feature_digest(x,features[x]) for x in ids}
    ordered=[[x,case_digests[x]] for x in sorted(ids)]
    canonical=json.dumps(ordered,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
    whole=hashlib.sha256(b'hepta.e1e2.bank-q24.v1\0'+canonical).hexdigest()
    return {'schema':'hepta.e1e2-q24-feature-bank.v1',
            'case_q24_sha256':case_digests,'bank_q24_sha256':whole,
            'feature_width':next(iter(widths)), 'case_count':len(ids),
            'model_origin_independently_verified':False,
            'authority':'DENY_ALL'}
