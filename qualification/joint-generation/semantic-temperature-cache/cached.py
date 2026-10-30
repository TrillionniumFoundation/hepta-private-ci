"""Same calibrated generation law; precompile fixed command maps/profile binding.

Only immutable profile/semantic metadata are cached,never raw policies or targets.
Generation identity stays the original temperature profile key; separate cache key
binds implementation and all36command maps. Compilation/serialization cost is real.
Old/default serving is unchanged. This is a qualified-source implementation cache,
not an old-source artifact compatibility promise or new generation-quality claim.
"""
from dataclasses import dataclass,field
import hashlib,itertools,json,math
import numpy as np
from control import Command,_canonical
from calibration import TemperatureProfile,MODE as GENERATION_MODE,calibrate_marginals
from normalized import _law

IMPLEMENTATION='immutable-command-map-cache-v1'
SCHEMA='rgb-calibrated-command-cache-v1'
COMMANDS=tuple(itertools.product(range(4),range(3),range(3)))

@dataclass(frozen=True)
class CompiledTemperatureProfile:
    profile:TemperatureProfile
    implementation:str
    text_maps:tuple=field(init=False,repr=False)
    image_maps:tuple=field(init=False,repr=False)
    generation_key:str=field(init=False)
    model_sha256:str=field(init=False)
    text_semantics:tuple=field(init=False,repr=False)
    image_semantics:tuple=field(init=False,repr=False)
    _text_bytes:bytes=field(init=False,repr=False)
    _image_bytes:bytes=field(init=False,repr=False)
    _key:str=field(init=False,repr=False)
    def __post_init__(self):
        if type(self.profile) is not TemperatureProfile or self.implementation!=IMPLEMENTATION:raise ValueError('explicit immutable calibrated cache')
        transport=self.profile.base.transport;ts=transport.base.text_semantics;ims=transport.base.image_semantics
        tm=tuple(transport.destinations(ts,Command(*c)) for c in COMMANDS);im=tuple(transport.destinations(ims,Command(*c)) for c in COMMANDS)
        for key,value in (('text_maps',tm),('image_maps',im),('generation_key',self.profile.key),('model_sha256',transport.base.model_sha256),('text_semantics',ts),('image_semantics',ims),('_text_bytes',np.asarray(tm,dtype='<i8').tobytes()),('_image_bytes',np.asarray(im,dtype='<i8').tobytes())):
            object.__setattr__(self,key,value)
        object.__setattr__(self,'_key',hashlib.sha256(_canonical(self.metadata()).encode()).hexdigest())
    def metadata(self):
        return dict(schema=SCHEMA,implementation=self.implementation,profile=json.loads(self.profile.dumps()),command_order=COMMANDS,text_maps=self.text_maps,image_maps=self.image_maps,generation_key=self.generation_key)
    @property
    def key(self):return self._key
    def dumps(self):return _canonical(dict(cache=self.metadata(),cache_key=self.key))
    @classmethod
    def loads(cls,payload,*,expected_model_sha256,expected_generation_mode,expected_implementation):
        if type(payload) is not str or len(payload.encode())>262144:raise ValueError('bounded cache document')
        def unique(pairs):
            out={}
            for k,v in pairs:
                if k in out:raise ValueError('duplicate field')
                out[k]=v
            return out
        obj=json.loads(payload,object_pairs_hook=unique)
        if type(obj) is not dict or set(obj)!={'cache','cache_key'}:raise ValueError('exact cache envelope')
        c=obj['cache']
        if (type(c) is not dict or set(c)!={'schema','implementation','profile','command_order','text_maps','image_maps','generation_key'}
                or c['schema']!=SCHEMA or c['implementation']!=expected_implementation or expected_implementation!=IMPLEMENTATION or expected_generation_mode!=GENERATION_MODE):raise ValueError('explicit cache schema/implementation/generation mode')
        profile=TemperatureProfile.loads(_canonical(c['profile']),expected_model_sha256=expected_model_sha256,expected_mode=expected_generation_mode)
        result=cls(profile,expected_implementation)
        if _canonical(c)!=_canonical(result.metadata()) or obj['cache_key']!=result.key:raise ValueError('tampered maps/order/profile/cache identity')
        return result


def apply_batch(compiled,p,q,commands,*,observed_model_sha256):
    if type(compiled) is not CompiledTemperatureProfile or observed_model_sha256!=compiled.model_sha256:raise ValueError('exact compiled profile andmodel binding')
    if type(commands) is not tuple or len(commands)!=len(p) or any(type(c) is not Command for c in commands):raise ValueError('immutable explicit commandbatch')
    indices=np.asarray([c.values[0]*9+c.values[1]*3+c.values[2] for c in commands],dtype=np.int64)
    ft=np.frombuffer(compiled._text_bytes,dtype='<i8').reshape(36,12)[indices]
    fi=np.frombuffer(compiled._image_bytes,dtype='<i8').reshape(36,12)[indices]
    ts,ims=compiled.text_semantics,compiled.image_semantics
    pp,qq,ft,fi,matching,a,b,left,right,ra,rb,joint,total=_law(p,q,ft,fi,ts,ims)
    # Exact qualified base_apply arithmetic, replacing only destination-map setup.
    table=np.empty_like(joint,dtype=np.float64);table[:,:,matching]=(joint/total[:,None,None]).astype(float)
    output_b=np.empty_like(b);output_b[:,matching]=b
    cdf=np.asarray([math.fsum(x.ravel().tolist()) for x in table])
    if (np.any(np.abs(table.sum(2)/cdf[:,None]-a)>1e-12) or np.any(np.abs(table.sum(1)/cdf[:,None]-output_b)>1e-12)):raise ValueError('returned binary64 CDF marginal check failed')
    base_joint=table/cdf[:,None,None];original_a=base_joint.sum(2);original_b=base_joint.sum(1)
    # Exact qualified calibration.apply_batch numerical graph and guards.
    a,b=calibrate_marginals(compiled.profile,original_a,original_b)
    matching=np.argsort(ims)[np.asarray(ts)]
    aligned_b=b[:,matching];diag=np.minimum(a,aligned_b);left=a-diag;right=aligned_b-diag
    ra=left.sum(1);rb=right.sum(1);active=(ra>0)&(rb>0)
    joint=np.zeros((len(a),12,12),dtype=np.longdouble)
    np.divide(left[:,:,None]*right[:,None,:],ra[:,None,None],out=joint,where=active[:,None,None])
    joint[:,np.arange(12),np.arange(12)]+=diag;total=joint.sum((1,2))
    if (np.any(total<=0) or np.any(np.abs(joint.sum(2)-a)>1e-12) or np.any(np.abs(joint.sum(1)-aligned_b)>1e-12)):raise ValueError('calibrated raw coupling marginals; no repair')
    table=np.empty_like(joint,dtype=float);table[:,:,matching]=(joint/total[:,None,None]).astype(float)
    cdf=np.asarray([math.fsum(x.ravel().tolist()) for x in table]);actual=table/cdf[:,None,None]
    final_a=actual.sum(2);final_b=actual.sum(1)
    if (not np.isfinite(actual).all() or np.any(actual<0) or np.any(np.abs(final_a-a)>1e-12) or np.any(np.abs(final_b-b)>1e-12)
            or not np.array_equal(final_a>0,original_a>0) or not np.array_equal(final_b>0,original_b>0)
            or not np.array_equal(final_a.argmax(1),original_a.argmax(1)) or not np.array_equal(final_b.argmax(1),original_b.argmax(1))):raise ValueError('calibrated CDF support/argmax/marginal guard; no fallback')
    return dict(text=final_a,image=final_b,joint=table,cdf_total=cdf,profile_key=compiled.generation_key,commands=tuple(c.values for c in commands),implementation=IMPLEMENTATION,implementation_key=compiled.key)
