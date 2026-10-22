"""Shadow-only check of REAL decoded outputs; never an NDU authorization gate."""
from dataclasses import asdict, dataclass
from hashlib import sha256
import math
import time
import numpy as np

class EvidenceRejected(ValueError):
    pass

@dataclass(frozen=True)
class Limits:
    cvar90: float
    quality_floor: float
    ambiguity_ceiling: float
    inconsistency_ceiling: float
    seconds_per_episode_ceiling: float
    quality_drop_ceiling: float = 0.
    cvar_increase_ceiling: float = 0.

def cvar90(x):
    """Worst ten percent with fractional boundary mass, AFTER episode reduction."""
    a = np.asarray(x, dtype=float)
    if a.ndim != 1 or len(a) < 10 or not np.isfinite(a).all() or (a < 0).any():
        raise EvidenceRejected('invalid episode-level losses')
    a = np.sort(a)[::-1]
    mass = .1*len(a)
    whole = math.floor(mass)
    total = float(a[:whole].sum()) + (mass-whole)*float(a[whole]) if mass > whole else float(a[:whole].sum())
    return total / mass

def compare(*, public_inputs, hidden_labels, episode_ids, draw_episode_ids,
            draws_per_episode, weights, generate, independent_score, limits,
            objective_digest, model_digest, input_digest,
            modalities=('text','audio','image','video')):
    """Generate BOTH trajectories before passing hidden labels to the scorer.

    Callback capture can still leak truth; this is a local structural audit,
    NOT an independently authenticated heldout result or trusted runtime.
    """
    if any(not isinstance(v, (int,float)) or not math.isfinite(v) for v in asdict(limits).values()):
        raise EvidenceRejected('invalid or nonfinite limits')
    if not (limits.cvar90 >= 0 and limits.seconds_per_episode_ceiling > 0
            and 0 <= limits.quality_floor <= 1 and 0 <= limits.ambiguity_ceiling <= 1
            and 0 <= limits.inconsistency_ceiling <= 1
            and limits.quality_drop_ceiling >= 0 and limits.cvar_increase_ceiling >= 0):
        raise EvidenceRejected('invalid hard/relative limits')
    if not (objective_digest and model_digest and input_digest):
        raise EvidenceRejected('missing frozen input identifiers')
    if (len(episode_ids) < 10 or len(set(episode_ids)) != len(episode_ids)
            or any(not isinstance(v,str) or not v for v in episode_ids)
            or not isinstance(draws_per_episode,int) or draws_per_episode < 1):
        raise EvidenceRejected('invalid episode cohort')
    order = [ep for ep in episode_ids for _ in range(draws_per_episode)]
    if list(draw_episode_ids) != order:
        raise EvidenceRejected('unpaired or missing draw episode identity')
    if (len(weights) > 128 or any(not np.isfinite(w) or w < 0 or w > 1 for w in weights)
            or sum(weights) > 1+1e-12):
        raise EvidenceRejected('invalid continuous portfolio')
    if not modalities or len(set(modalities)) != len(modalities):
        raise EvidenceRejected('missing modality contract')
    n, samples = len(episode_ids), len(order)
    results = {}
    for name, allocation in [('baseline',tuple(0. for _ in weights)),
                             ('selected',tuple(float(w) for w in weights))]:
        start=time.perf_counter()
        raw=generate(public_inputs,allocation)  # no hidden labels are passed
        elapsed=time.perf_counter()-start
        if not isinstance(raw,dict) or not set(modalities).issubset(raw):
            raise EvidenceRejected('missing raw decoded modalities')
        for modality in modalities:
            z=np.asarray(raw[modality])
            if z.ndim<1 or len(z)!=samples or not np.issubdtype(z.dtype,np.number) or not np.isfinite(z).all():
                raise EvidenceRejected('invalid raw decoded '+modality)
        external=independent_score(raw,hidden_labels)  # after full generation
        if not isinstance(external,dict) or set(external)!={'loss','quality','ambiguity','inconsistency'}:
            raise EvidenceRejected('incomplete independent scoring fields')
        columns={}
        for key,x in external.items():
            a=np.asarray(x,dtype=float)
            if a.shape!=(samples,) or not np.isfinite(a).all() or (a<0).any() or (key!='loss' and (a>1).any()):
                raise EvidenceRejected('bad independent scoring dimension/value '+key)
            columns[key]=a.reshape(n,draws_per_episode).mean(1)
        digest=sha256(b'hepta.mgp.decoded-observed.v1\0')
        for key in sorted(columns):
            digest.update(key.encode()+b'\0'+np.ascontiguousarray(columns[key],dtype='<f8').tobytes())
        results[name]={
            'cvar90':cvar90(columns['loss']),
            'quality':float(columns['quality'].mean()),
            'ambiguity':float(columns['ambiguity'].mean()),
            'inconsistency':float(columns['inconsistency'].mean()),
            'generator_seconds_per_episode':elapsed/n,
            'external_scores_sha256':digest.hexdigest()
        }
    selected,base=results['selected'],results['baseline']
    checks={
        'observed_cvar90': selected['cvar90']<=limits.cvar90,
        'observed_quality': selected['quality']>=limits.quality_floor,
        'observed_ambiguity': selected['ambiguity']<=limits.ambiguity_ceiling,
        'observed_inconsistency': selected['inconsistency']<=limits.inconsistency_ceiling,
        'observed_generation_cost': selected['generator_seconds_per_episode']<=limits.seconds_per_episode_ceiling,
        'relative_quality': selected['quality']>=base['quality']-limits.quality_drop_ceiling,
        'relative_tail': selected['cvar90']<=base['cvar90']+limits.cvar_increase_ceiling,
    }
    return {'schema':'hepta-mgp-observed-decoded-risk-v1',
            'status':'ADVISORY_ONLY' if all(checks.values()) else 'REJECT_OBSERVED_OUTPUT',
            'authority':'DENY_ALL','independent_observer_authenticated':False,
            'scientific_efficacy_claim':False,'evaluation_scope':'LOCAL_RESEARCH',
            'objective_digest':objective_digest,'model_digest':model_digest,
            'input_digest':input_digest,'n_episodes':n,'draws_per_episode':draws_per_episode,
            'modalities':list(modalities),'weights':list(weights),
            'baseline':base,'selected':selected,'checks':checks,
            'cost_scope':'generation wall only: excludes offline work, GPU sync, evaluator and energy'}
