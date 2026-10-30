"""Opt-in semantic pushforward: edit set axes, conserve every remaining axis.

Unlike support conditioning, this moves probability mass rather than discarding
and renormalizing it. It is a finite-vocabulary serving operator, not learning.
Every destination must exist in a BIJECTIVE observed decoder map; no nearest,
best, uniform or renderer fallback may invent a missing destination.
"""
from dataclasses import dataclass
import hashlib
import json
from control import Command, ControlProfile, MODE, _policy, _canonical

SCHEMA = 'rgb-decoded-semantic-pushforward-v1'
TRANSPORT_MODE = 'explicit-word-semantic-transport'


@dataclass(frozen=True)
class TransportProfile:
    base: ControlProfile
    mode: str

    def __post_init__(self):
        if type(self.base) is not ControlProfile or self.mode != TRANSPORT_MODE:
            raise ValueError('explicit semantic transport profile required')
        if any(set(s) != set(range(12)) for s in (self.base.text_semantics, self.base.image_semantics)):
            raise ValueError('complete bijective observed semantics required')

    def metadata(self):
        return dict(schema=SCHEMA,mode=self.mode,base_profile=json.loads(self.base.dumps()))

    @property
    def key(self):
        return hashlib.sha256(_canonical(self.metadata()).encode()).hexdigest()

    def dumps(self):
        return _canonical(dict(profile=self.metadata(),profile_key=self.key))

    @classmethod
    def loads(cls,payload,*,expected_model_sha256,expected_mode):
        if type(payload) is not str or len(payload.encode())>16384:
            raise ValueError('bounded transport profile required')
        def unique(pairs):
            result={}
            for k,v in pairs:
                if k in result:raise ValueError('duplicate field')
                result[k]=v
            return result
        obj=json.loads(payload,object_pairs_hook=unique)
        if type(obj) is not dict or set(obj)!={'profile','profile_key'}:raise ValueError('exact transport envelope')
        p=obj['profile']
        if (type(p) is not dict or set(p)!={'schema','mode','base_profile'} or p['schema']!=SCHEMA
                or p['mode']!=expected_mode or expected_mode!=TRANSPORT_MODE):
            raise ValueError('transport schema/mode mismatch')
        base=ControlProfile.loads(_canonical(p['base_profile']),expected_model_sha256=expected_model_sha256,expected_mode=MODE)
        result=cls(base,expected_mode)
        if result.key!=obj['profile_key']:raise ValueError('altered transport identity')
        return result

    @staticmethod
    def destinations(semantics,command):
        inverse={semantic:index for index,semantic in enumerate(semantics)}
        destinations=[]
        for semantic in semantics:
            attrs=[semantic//4,(semantic//2)%2,semantic%2]
            for axis,word in enumerate(command.values):
                if word:attrs[axis]=word-1
            edited=(attrs[0]*2+attrs[1])*2+attrs[2]
            destinations.append(inverse[edited])
        return tuple(destinations)

    def apply(self,text,image,command,*,observed_model_sha256):
        if observed_model_sha256!=self.base.model_sha256 or type(command) is not Command:
            raise ValueError('exact model and explicit request command required')
        text,image=_policy(text),_policy(image)
        def push(policy,semantics):
            destinations=self.destinations(semantics,command)
            if destinations==tuple(range(12)):return policy
            result=[0.0]*12
            for probability,index in zip(policy,destinations):result[index]+=probability
            return tuple(result)
        return dict(text=push(text,self.base.text_semantics),image=push(image,self.base.image_semantics),
                    profile_key=self.key,command=command.values)
