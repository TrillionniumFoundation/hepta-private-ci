"""P2 research-only *sampled* Brownian FIRE train, with causal checkpointing.

Independent of the finite-horizon *expected count* calculation. Brownian
first-hitting time sampled from the exact (possibly defective) IG/Lévy law
for constant drift/diffusion and fixed upper threshold, not Euler time steps.
This is a scalar Python oracle, NOT a trainable, native or live Cell owner.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math

_MASK=(1 << 64)-1


class UnresolvedSpike(ValueError):
    """Reject invalid law, checkpoint, event budget or precision regime."""


@dataclass(frozen=True)
class SpikeSpec:
    drift: float
    diffusion: float
    discount: float
    cost: float
    reset: float
    refractory: float
    boundary: float
    initial: float

    def __post_init__(self):
        if (any(type(v) not in (int,float) or not math.isfinite(v)
                for v in vars(self).values()) or self.diffusion <= 0
                or self.discount <= 0 or self.refractory < 0
                or not (self.reset < self.cost < self.boundary)
                or self.reset >= self.boundary
                or not (math.isfinite(self.diffusion*self.diffusion)
                        and self.diffusion*self.diffusion > 0)):
            raise UnresolvedSpike('invalid Brownian regenerative firing domain')


def _canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False)


class SpikeStream:
    VERSION=1

    def __init__(self,spec: SpikeSpec, *, seed: int, stream_id: str):
        if (not isinstance(spec,SpikeSpec) or type(seed) is not int
                or not 0 <= seed <= _MASK or type(stream_id) is not str
                or not 0 < len(stream_id) <= 64):
            raise UnresolvedSpike('invalid deterministic stream identity')
        self.spec=spec
        self.stream_id=stream_id
        stream_hash=int.from_bytes(hashlib.sha256(stream_id.encode('utf-8')).digest()[:8],'big')
        self.rng=(seed ^ stream_hash)&_MASK
        self.now=0.0
        self.events=0
        self.next_time=(0.0 if spec.initial >= spec.boundary else
                        self._first_hit(spec.boundary-spec.initial))

    def _uniform(self):
        # Counter-state SplitMix64: open-interval U in (0,1), no cached draw.
        self.rng=(self.rng+0x9E3779B97F4A7C15)&_MASK
        z=self.rng
        z=((z ^ (z >> 30))*0xBF58476D1CE4E5B9)&_MASK
        z=((z ^ (z >> 27))*0x94D049BB133111EB)&_MASK
        z ^= z >> 31
        return ((z >> 11)+0.5) / (1 << 53)

    def _first_hit(self, distance):
        p=self.spec
        if distance <= 0 or not math.isfinite(distance):
            raise UnresolvedSpike('invalid positive hit distance')
        if p.drift < 0:
            try:
                probability=math.exp(2*p.drift*distance/(p.diffusion**2))
            except (OverflowError,ZeroDivisionError) as e:
                raise UnresolvedSpike('defective-hit probability unresolved') from e
            if self._uniform() > probability:
                return None  # true defective first-passage probability
        try:
            z=math.sqrt(-2*math.log(self._uniform())) * math.cos(2*math.pi*self._uniform())
            if p.drift == 0:
                t=(distance/(p.diffusion*z))**2 if z else math.inf
            else:
                # Conditional law for negative drift uses |drift| (h-transform).
                mu=distance/abs(p.drift)
                lam=(distance/p.diffusion)**2
                sq=z*z
                rad=4*mu*lam*sq+mu*mu*sq*sq
                t=mu+(mu*mu*sq)/(2*lam)-(mu/(2*lam))*math.sqrt(rad)
                if not (t > 0 and math.isfinite(t)):
                    # Algebraically identical cancellation-free IG low root.
                    ratio=mu*sq/lam
                    t=2*mu/(2+ratio+math.sqrt(4*ratio+ratio*ratio))
                if not (t > 0 and math.isfinite(t)):
                    raise UnresolvedSpike('inverse Gaussian low root unresolved')
                if self._uniform()>mu/(mu+t):
                    t=mu*mu/t
        except (OverflowError, ZeroDivisionError) as e:
            raise UnresolvedSpike('first passage floating-point domain unresolved') from e
        if not (math.isfinite(t) and t>0):
            raise UnresolvedSpike('first passage sampling precision unresolved')
        return t

    def checkpoint(self):
        payload=dict(version=self.VERSION,spec=asdict(self.spec),stream_id=self.stream_id,
                     rng=self.rng,now=self.now,events=self.events,next_time=self.next_time)
        payload['sha256']=hashlib.sha256(_canonical(payload).encode()).hexdigest()
        return _canonical(payload)

    @classmethod
    def from_checkpoint(cls, raw, *, expected_spec=None, expected_stream_id=None):
        try:
            data=json.loads(raw)
            if type(data) is not dict:
                raise ValueError('snapshot must be a map')
            checksum=data.pop('sha256')
            if type(checksum) is not str or len(checksum)!=64:
                raise ValueError('bad digest')
            if hashlib.sha256(_canonical(data).encode()).hexdigest()!=checksum:
                raise ValueError('digest mismatch')
            if set(data)!={'version','spec','stream_id','rng','now','events','next_time'}:
                raise ValueError('unknown snapshot fields')
            if type(data['version']) is not int or data['version']!=cls.VERSION:
                raise ValueError('unknown format version')
            spec=SpikeSpec(**data['spec'])
            if (expected_spec is not None and spec != expected_spec or
                    expected_stream_id is not None and data['stream_id'] != expected_stream_id):
                raise ValueError('snapshot model or stream mismatch')
            if (type(data['rng']) is not int or not 0<=data['rng']<=_MASK or
                    type(data['events']) is not int or data['events']<0 or
                    type(data['now']) not in (float,int) or not math.isfinite(data['now'])
                    or data['now']<0 or type(data['stream_id']) is not str
                    or not 0<len(data['stream_id'])<=64):
                raise ValueError('invalid event state')
            next_t=data['next_time']
            if (next_t is not None and
                    (type(next_t) not in (float,int) or not math.isfinite(next_t)
                     or next_t < data['now'] or (next_t == data['now'] and data['events']>0))):
                raise ValueError('invalid pending event')
        except (ValueError,TypeError,KeyError,AssertionError) as e:
            raise UnresolvedSpike('invalid or untrusted snapshot') from e
        obj=cls.__new__(cls)
        obj.spec,obj.stream_id=spec,data['stream_id']
        obj.rng,obj.now,obj.events,obj.next_time=(data[k] for k in ('rng','now','events','next_time'))
        return obj

    def advance_to(self, deadline: float, *, max_events=10000):
        if (type(deadline) not in (float,int) or not math.isfinite(deadline)
                or deadline < self.now or type(max_events) is not int
                or not 1<=max_events<=1000000):
            raise UnresolvedSpike('invalid causal deadline or event cap')
        # Transactional staging: an exhausted budget cannot half-advance state.
        trial=self.from_checkpoint(self.checkpoint(),expected_spec=self.spec,
                                   expected_stream_id=self.stream_id)
        out=[]
        while trial.next_time is not None and trial.next_time<=deadline:
            if len(out)>=max_events:
                raise UnresolvedSpike('event-budget exhausted without state commit')
            t=trial.next_time
            out.append(t)
            trial.events+=1
            gap=trial.spec.boundary-trial.spec.reset
            hit=trial._first_hit(gap)
            if hit is None:
                trial.next_time=None
            else:
                next_t=t+trial.spec.refractory+hit
                if not math.isfinite(next_t) or next_t<=t:
                    raise UnresolvedSpike('event clock did not advance')
                trial.next_time=next_t
        trial.now=float(deadline)
        self.rng,self.now,self.events,self.next_time=(trial.rng,trial.now,trial.events,trial.next_time)
        return tuple(out)
