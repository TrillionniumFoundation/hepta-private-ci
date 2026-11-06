"""Small paid-calibration contract for a computation-rule equivalence audit.

Fixed external expected utility, four known candidate information laws with an
unknown true member, paid preparation, full label charges and a hard model clock.
This is a constructed finite reference, not a new independent empirical task.
"""
from dataclasses import dataclass
from fractions import Fraction as F
from math import comb

ORDER=('stop','follow','flip','prepare','fast','pair')


@dataclass(frozen=True,order=True)
class State:
    remaining:int
    labels:int=0
    ones:int=0
    ready:bool=False


def key(s):
    return f't{s.remaining}:n{s.labels}:k{s.ones}:z{int(s.ready)}'


@dataclass(frozen=True)
class Contract:
    deadline:int=4
    deployments:int=4
    world_accuracy:tuple=(F(1,10),F(3,10),F(7,10),F(9,10))
    prior:tuple=(F(1,4),)*4
    prepare_fee:F=F(1,25)
    fast_fee:F=F(3,100)
    pair_fee:F=F(1,20)
    time_price:F=F(1,100)
    deployment_fee:F=F(1,10)
    compute_price:F=F(1,1000000)
    compute_time:F=F(1,1000000)
    compute_reserve:F=F(1,2)
    validation_fee:F=F(1,1000)

    def __post_init__(self):
        if (type(self.deadline) is not int or not 0<=self.deadline<=4
                or self.deployments!=4 or self.world_accuracy!=(F(1,10),F(3,10),F(7,10),F(9,10))
                or self.prior!=(F(1,4),)*4
                or any(not isinstance(x,F) or x<0 for x in (self.prepare_fee,self.fast_fee,
                    self.pair_fee,self.time_price,self.deployment_fee,self.compute_price,
                    self.compute_time,self.compute_reserve,self.validation_fee))):
            raise ValueError('This audit uses the declared four-task rational finite contract')

    @property
    def root(self):return State(self.deadline)

    def posterior(self,s):
        if (not isinstance(s,State) or type(s.remaining) is not int or not 0<=s.remaining<=self.deadline
                or type(s.labels) is not int or type(s.ones) is not int
                or not 0<=s.ones<=s.labels<=4 or type(s.ready) is not bool):
            raise ValueError('Invalid sufficient calibration state')
        weights=[w*p**s.ones*(1-p)**(s.labels-s.ones) for w,p in zip(self.prior,self.world_accuracy)]
        total=sum(weights,F(0))
        return tuple(w/total for w in weights)

    def terminal(self,s):
        q=sum((w*p for w,p in zip(self.posterior(s),self.world_accuracy)),F(0))
        return {'stop':F(self.deployments,2),'follow':self.deployments*(q-self.deployment_fee),
                'flip':self.deployments*(1-q-self.deployment_fee)}

    def terminal_world(self,a,h):
        p=self.world_accuracy[h]
        return (F(self.deployments,2) if a=='stop' else
                self.deployments*((p if a=='follow' else 1-p)-self.deployment_fee))

    def upper(self,s):
        terminal=max(self.terminal(s).values())
        if s.remaining==0 or not s.ready and s.remaining<2:return terminal
        return self.deployments*sum((w*max(F(1,2),p-self.deployment_fee,1-p-self.deployment_fee)
            for w,p in zip(self.posterior(s),self.world_accuracy)),F(0))

    def information_actions(self,s):
        if s.remaining<1:return ()
        if not s.ready:return ('prepare',)
        return ('fast','pair') if s.remaining>=2 else ('fast',)

    def duration(self,a):return 2 if a=='pair' else 1

    def fee(self,a):return {'prepare':self.prepare_fee,'fast':self.fast_fee,'pair':self.pair_fee}[a]

    def cost(self,a):return self.fee(a)+self.time_price*self.duration(a)

    def responses(self,s,a):
        if a not in self.information_actions(s):raise ValueError('Illegal calibration launch')
        if a=='prepare':return ((F(1),State(s.remaining-1,s.labels,s.ones,True)),)
        n=self.duration(a)
        return tuple((sum((w*F(comb(n,j))*p**j*(1-p)**(n-j)
                    for w,p in zip(self.posterior(s),self.world_accuracy)),F(0)),
                State(s.remaining-n,s.labels+n,s.ones+j,True)) for j in range(n+1))

    def world_responses(self,s,a,h):
        if a=='prepare':return ((F(1),State(s.remaining-1,s.labels,s.ones,True)),)
        n=self.duration(a);p=self.world_accuracy[h]
        return tuple((F(comb(n,j))*p**j*(1-p)**(n-j),State(s.remaining-n,s.labels+n,s.ones+j,True))
                     for j in range(n+1))

    def quote(self,s):
        # Abstract, prospectively declared computation units; same quote for
        # candidate and classical rule. Actual work is separately metered.
        return 1+sum(1+(1 if a=='prepare' else self.duration(a)+1) for a in self.information_actions(s))
