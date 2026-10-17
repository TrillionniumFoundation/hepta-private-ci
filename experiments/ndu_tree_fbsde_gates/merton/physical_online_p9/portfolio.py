"""P9 hard prepaid physical-token escrow and TRAIN-only shadow-value controller.

Finite, research-only decision and accounting contracts. Not a neural FBSDE,
not a learned resource-price theorem, and not executable authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction as Q

SCHEMA='hepta.ndu-merton.p9.prepaid-physical-token-portfolio.v1'
POLICIES=('direct','fixed_plain','fixed_think','myopic','neutral_shadow','ndu_shadow','ordinary_same_profile')
CHECKS=('stop','check_plain','check_think')
MAX_CHECKS=4
TOKEN_ENDOWMENT=1500
CHECK_CAP=256
TARIFF=Q(1,4096)


def strict_int(v:int,minimum:int,maximum:int)->int:
    if type(v) is not int or not minimum<=v<=maximum:
        raise ValueError('physical token/accounting integer invalid')
    return v


@dataclass
class TokenEscrow:
    """Reserve full input+max-generation before calling the actual model.

    Unfinished/failed calls are NOT refunded. No async recovery claim; a call
    whose done/settlement is unavailable is an indeterminate, unusable study.
    """
    available:int=TOKEN_ENDOWMENT
    remaining_calls:int=MAX_CHECKS
    paid:int=0
    ledger:list[dict]=field(default_factory=list)
    pending:tuple|None=None
    poisoned:bool=False

    def can_reserve(self,input_tokens:int,cap:int=CHECK_CAP)->bool:
        strict_int(input_tokens,1,1024)
        strict_int(cap,1,CHECK_CAP)
        return not self.poisoned and self.pending is None and self.remaining_calls>0 and input_tokens+cap<=self.available

    def reserve(self,identity:str,input_tokens:int,cap:int=CHECK_CAP)->dict:
        if type(identity) is not str or not identity or any(row['identity']==identity for row in self.ledger):
            raise ValueError('duplicate/invalid escrow identity')
        if not self.can_reserve(input_tokens,cap):
            raise ValueError('token/call budget unavailable')
        before=self.available
        self.available-=input_tokens+cap
        self.remaining_calls-=1
        self.pending=(identity,input_tokens,cap,before)
        return {'identity':identity,'input_quote':input_tokens,'output_cap':cap,
                'reserved_tokens':input_tokens+cap,'tokens_before':before,
                'calls_before':self.remaining_calls+1}

    def settle(self,identity:str,input_tokens:int,output_tokens:int)->dict:
        if self.poisoned or self.pending is None or self.pending[0]!=identity:
            raise ValueError('missing/mismatched pending physical invocation')
        _,quoted,cap,before=self.pending
        try:
            strict_int(input_tokens,1,1024)
            strict_int(output_tokens,1,cap)
            if input_tokens!=quoted:
                raise ValueError('quoted prompt was not actual billed input')
            spent=input_tokens+output_tokens
            refund=cap-output_tokens
            self.available+=refund
            self.paid+=spent
            result={'identity':identity,'input_quote':quoted,'output_cap':cap,
                    'reserved_tokens':quoted+cap,'tokens_before':before,
                    'actual_input_tokens':input_tokens,'actual_output_tokens':output_tokens,
                    'actual_paid_tokens':spent,'unused_refund':refund,
                    'tokens_after':self.available,'calls_after':self.remaining_calls}
            self.ledger.append(result)
            self.pending=None
            self.invariant()
            return result
        except Exception:
            self.poisoned=True
            raise

    def invariant(self):
        if self.poisoned or self.pending is not None or self.available+self.paid!=TOKEN_ENDOWMENT:
            raise ValueError('escrow conservation / unresolved physical invocation')
        if self.remaining_calls!=MAX_CHECKS-len(self.ledger) or self.available<0 or self.paid<0:
            raise ValueError('escrow call/token accounting invalid')

    def wire(self)->dict:
        self.invariant()
        return {'initial_tokens':TOKEN_ENDOWMENT,'initial_calls':MAX_CHECKS,
                'remaining_tokens':self.available,'remaining_calls':self.remaining_calls,
                'actual_paid_tokens':self.paid,'settlements':self.ledger.copy()}


def expected(profile:dict,state:str,action:str,alpha:Q)->Q:
    x=profile['entries'].get(state)
    if not x:
        raise ValueError('unsupported TRAIN feature bucket')
    row=x[action]
    return (1-alpha)*Q(row['mean'])+alpha*Q(row['worst_group'])


class Controller:
    """A declared finite empirical shadow heuristic, NOT a global Merton optimum.

    Future opportunity prices are estimated ONLY from TRAIN paired correctness,
    same frozen public bucket order and frozen TRAIN forecasted full-token cost.
    A freshly observed original answer is used only for its parse-validity bit.
    """
    def __init__(self,profile:dict,buckets:tuple[str,...],name:str):
        if name not in POLICIES or type(profile)!=dict or profile.get('census')!=32 or len(buckets)!=16:
            raise ValueError('wrong frozen research decision profile')
        if any(x not in ('short','long') for x in buckets):
            raise ValueError('unknown future public bucket')
        self.profile,self.buckets,self.name=profile,buckets,name

    def alpha(self,state:str,escrow:TokenEscrow)->Q:
        if self.name not in ('ndu_shadow','ordinary_same_profile'):
            return Q(0)
        row=self.profile['entries'].get(state)
        if row is None:return Q(0)
        prior=Q(row['stop']['mean'])
        return min(Q(1,2),Q(1,8)+(1-prior)/4+Q(TOKEN_ENDOWMENT-escrow.available,8*TOKEN_ENDOWMENT))

    def future_shadow(self,index:int,escrow:TokenEscrow)->Q:
        """TRAIN forecast of strongest positive incremental value per physical token.

        Scarcity correction is bounded; not an exact solution of an unknown future
        Markov process. The source supports no causal calibration guarantee.
        """
        if index>=15:return Q(0)
        values=[]
        for bucket in self.buckets[index+1:]:
            for f in ('valid','invalid'):
                state=f'{bucket}/{f}'
                if state not in self.profile['entries']:continue
                prob=Q(self.profile['features'][bucket][f])
                for action in ('check_plain','check_think'):
                    alpha=self.alpha(state,escrow)
                    gain=expected(self.profile,state,action,alpha)-expected(self.profile,state,'stop',alpha)
                    cost=Q(self.profile['entries'][state][action]['mean_full_tokens'])
                    if cost>0 and gain>0:values.append(prob*gain/cost)
        if not values:return Q(0)
        future_count=len(self.buckets)-index-1
        scarcity=max(Q(0),Q(future_count-escrow.remaining_calls,future_count))
        return scarcity*max(values)

    def choose(self,index:int,escrow:TokenEscrow,bucket:str,base_prediction:int|None,quotes:dict[str,int])->str:
        if type(index) is not int or not 0<=index<16 or bucket!=self.buckets[index]:
            raise ValueError('online order or observable bucket drift')
        if base_prediction is not None and (type(base_prediction) is not int or base_prediction not in range(4)):
            raise ValueError('invalid public original prediction')
        if set(quotes)!=set(CHECKS[1:]):raise ValueError('missing token quote candidate')
        for q in quotes.values():strict_int(q,1,1024)
        if self.name=='direct':return 'stop'
        feasible={a for a in ('check_plain','check_think') if escrow.can_reserve(quotes[a])}
        if self.name.startswith('fixed_'):
            desired='check_plain' if self.name=='fixed_plain' else 'check_think'
            return desired if index<MAX_CHECKS and desired in feasible else 'stop'
        state=f'{bucket}/{"valid" if base_prediction is not None else "invalid"}'
        if state not in self.profile['entries'] or not feasible:return 'stop'
        alpha=self.alpha(state,escrow)
        shadow=Q(0) if self.name=='myopic' else self.future_shadow(index,escrow)
        candidates=[(Q(0),'stop')]
        for action in ('check_plain','check_think'):
            if action not in feasible:continue
            predicted_cost=Q(self.profile['entries'][state][action]['mean_full_tokens'])
            advantage=(expected(self.profile,state,action,alpha)-expected(self.profile,state,'stop',alpha)
                -TARIFF*predicted_cost-shadow*quotes[action])
            candidates.append((advantage,action))
        # Prefer STOP on ties, then plainer/cheaper check; deterministic ordering.
        return max(candidates,key=lambda item:(item[0],-CHECKS.index(item[1])))[1]
