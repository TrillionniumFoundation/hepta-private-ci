"""Source and data contracts; no model or solver execution on import."""
from pathlib import Path
import gzip
import hashlib
import json
import os
import numpy as np

ROOT = Path(__file__).resolve().parent
WORK = Path(os.environ.get('HEPTA_WSP_INPUT_ROOT', str(ROOT/'inputs'))).resolve()
OLD = WORK/'neuron_margin_experiment'
MLP = WORK/'neuron_full_mlp_experiment'
CAUSAL = WORK/'neuron_causal_rescue_20261120'
LAST = Path(os.environ.get('HEPTA_WSP_PREVIOUS_ROOT', str(WORK/'wsp_continuation_20261121/neuron'))).resolve()
FITS = (11, 23, 37, 53, 71)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(path):
    raw = Path(path).read_bytes()
    return {'bytes': len(raw), 'sha256': sha(raw)}


def read(path):
    path = Path(path)
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def save(path, value):
    with Path(path).open('x') as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2,
                  allow_nan=False)
        handle.write('\n')


def specs(fit):
    dpath = LAST/'attempt001/discovery'/f'fit_{fit}.json'
    old = read(dpath)
    return dict(model=str(LAST/'attempt001/models'/f'fit_{fit}_C.json.gz'),
        data=old['inputs']['dataset']['path'], teacher=old['inputs']['teacher']['path'],
        discovery=str(dpath), discovery_arrays=str(dpath.with_suffix('.npz')),
        reconstruction=str(MLP/'attempt001'/f'fit_{fit}_CANDIDATE.json.gz'),
        family=str(CAUSAL/'attempt001'/f'fit_{fit}_FAMILY.json.gz'),
        publics=str(OLD/'inputs'/f'fit_{fit}_TRAIN_PUBLICS.json.gz'))


def verify_pin_map(pins):
    for path, expected in pins.items():
        if identity(path) != expected:
            raise ValueError('pinned bytes changed: '+path)


def load_fit(spec):
    """No neural forward: authenticate exact exposed data and own-law labels."""
    base = read(spec['model'])
    if base['schema'] != 'joint-policy-v1' or base['family'] != 'renewal' or base['head_dimensions'] != [85,48,4]:
        raise ValueError('original architecture contract')
    rec, fam, disc = (read(spec[k]) for k in ('reconstruction','family','discovery'))
    data_pin = {k:rec['dataset'][k] for k in ('bytes','sha256')}
    if identity(spec['data']) != data_pin or identity(spec['teacher']) != {k:fam['teacher'][k] for k in ('bytes','sha256')}:
        raise ValueError('prior data or teacher source binding')
    if not fam['program']['own_law_labels_only']:
        raise ValueError('own-law teacher is required')
    if identity(spec['model']) != {k:fam['source_C'][k] for k in ('bytes','sha256')}:
        raise ValueError('original C differs from own-law teacher source')
    with np.load(spec['data'], allow_pickle=False) as archive:
        data = {k:archive[k] for k in ('X','legal_masks','C_scores','state_weights','belief_weights')}
    with np.load(spec['teacher'], allow_pickle=False) as archive:
        teacher = {k:archive[k] for k in archive.files}
    with np.load(spec['discovery_arrays'], allow_pickle=False) as archive:
        old = {k:archive[k] for k in archive.files}
    X, masks, scores = data['X'],data['legal_masks'],data['C_scores']
    if X.shape != (rec['train_rows'],85) or masks.shape != (len(X),6) or scores.shape != masks.shape:
        raise ValueError('cached dimensions')
    target_q = np.c_[np.zeros(len(X)),teacher['own_optimal_targets'][:,:3],
                     1-2*teacher['own_posterior'],2*teacher['own_posterior']-1]
    target = np.where(masks,target_q,-np.inf).argmax(1)
    incumbent = np.where(masks,scores,-np.inf).argmax(1)
    gap = np.maximum(0.,target_q[np.arange(len(X)),target]-target_q[np.arange(len(X)),incumbent])
    if not np.array_equal(target,old['own_actions']) or not np.array_equal(incumbent,old['C_actions']) or not np.array_equal(gap,old['own_action_gap']):
        raise ValueError('own-law targets changed from previous discovery')
    normocc=np.zeros(len(X)); rawocc=np.zeros(len(X)); worldindex=np.zeros(len(X),np.int64); localindex=np.zeros(len(X),np.int64)
    offset=0; publics=read(spec['publics'])
    if len(publics)!=64 or len(rec['reconstructed_worlds'])!=64 or len(fam['program']['TRAIN'])!=64:
        raise ValueError('64 original TRAIN worlds required')
    for world,(previous,trow,public) in enumerate(zip(rec['reconstructed_worlds'],fam['program']['TRAIN'],publics)):
        n=previous['rows']; sl=slice(offset,offset+n)
        if trow['rows']!=n or trow['world_id']!=previous['world_id'] or public['id']!=previous['world_id'] or trow['state_order_sha256']!=previous['state_order_sha256']:
            raise ValueError('teacher/state/world row binding')
        if sha(teacher['own_optimal_targets'][sl].tobytes())!=trow['teacher_sha256'] or sha(teacher['sample_weights'][sl].tobytes())!=trow['sample_weight_sha256']:
            raise ValueError('per-world own-law teacher bytes')
        eligible=masks[sl,1:4].any(1); E=int(eligible.sum())
        recovered=np.zeros(n); recovered[eligible]=(64*data['state_weights'][sl][eligible]-.1/E)/.9
        if np.min(recovered)<-1e-12 or abs(recovered.sum()-1)>1e-10:
            raise ValueError('eligible occupancy mixture inversion')
        normocc[sl]=np.maximum(0.,recovered)/64
        rawocc[sl]=normocc[sl]*previous['weights']['eligible_occupancy_mass']
        worldindex[sl]=world;localindex[sl]=np.arange(n);offset+=n
    if offset!=len(X) or not np.array_equal(normocc,old['incumbent_eligible_occupancy']):
        raise ValueError('previous occupancy exact identity')
    if np.any(target[normocc>0]==0):
        raise ValueError('frozen sequential belief subproblem requires no occupied STOP target')
    return dict(base=base,rec=rec,family=fam,discovery=disc,X=X,masks=masks,scores=scores,
        target=target,target_q=target_q,incumbent=incumbent,gap=gap,normocc=normocc,
        rawocc=rawocc,uniform=data['belief_weights'],worldindex=worldindex,localindex=localindex,
        previous=old)
