"""The original train-normalized input recipe; used only in the approved final lane."""
import hashlib
import io
import numpy as np

ACTORS = (5,6,11,12,21,22)


def load_locked_test(raw, manifest):
    item = next(row for row in manifest['payload_members'] if row['path']=='data/test.npz')
    if len(raw)!=item['bytes'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:
        raise ValueError('locked historical test bytes differ')
    normalization=bytes.fromhex(manifest['normalizer_f32_le_hex'])
    if len(normalization)!=76 or hashlib.sha256(normalization).hexdigest()!=manifest['normalizer_sha256']:
        raise ValueError('original train-only19F32 normalization differs')
    values=np.frombuffer(normalization,dtype='<f4')
    if not np.isfinite(values).all() or not (values[9:]>0).all():
        raise ValueError('normalizer domain')
    mu,sd,scale=values[:9],values[9:18],values[18]
    with np.load(io.BytesIO(raw),allow_pickle=False) as archive:
        shared=archive['x'][:, :, [0,1,2,3,4,5,7]]
        baseline=archive['read_scores'].astype('float32')
        audio=archive['scores']
        visual=2*archive['read_scores']-audio
        inputs=np.concatenate((np.broadcast_to(shared[:, :, None, :],(*baseline.shape,7)),
            audio[...,None],visual[...,None]),axis=-1).astype('float32')
        target=archive['target']
        if target.dtype.kind not in 'iu' or not np.isin(target,(0,1)).all():
            raise ValueError('binary integer targets required')
        row=dict(x=inputs,baseline=baseline,y=target.astype('int64'),
            groups=archive['group'].copy(),query_id=archive['query_id'].copy(),
            gallery_id=archive['gallery_id'].copy())
    if (inputs.shape!=(48,6,2,9) or baseline.shape!=(48,6,2) or row['y'].shape!=(48,) or
            row['groups'].shape!=(48,) or row['query_id'].shape!=(48,) or row['gallery_id'].shape!=(48,2)):
        raise ValueError('fixed historical-test shape differs')
    if not np.isfinite(inputs).all() or not np.isfinite(baseline).all():
        raise ValueError('historical-test nonfinite source inputs')
    if any(row[key].dtype.kind not in 'US' for key in ('groups','query_id','gallery_id')):
        raise ValueError('expected non-object source identifiers')
    if len(set(map(str,row['query_id'])))!=48:
        raise ValueError('duplicate query identity')
    expected_groups=['ravdess-actor-%02d'%actor for actor in ACTORS]
    if set(map(str,row['groups']))!=set(expected_groups):
        raise ValueError('six frozen actor groups differ')
    for group in expected_groups:
        mask=row['groups']==group
        if int(mask.sum())!=8 or np.bincount(row['y'][mask],minlength=2).tolist()!=[4,4]:
            raise ValueError('per-actor original query/target coverage differs')
    for group,query,gallery in zip(row['groups'],row['query_id'],row['gallery_id']):
        actor=str(group).rsplit('-',1)[-1]
        if any(str(value).rsplit('-',1)[-1].split('.')[0]!=actor for value in (query,*gallery)):
            raise ValueError('query/gallery actor disagrees with source group')
        if len(set(map(str,gallery)))!=2 or str(query) in set(map(str,gallery)):
            raise ValueError('independent-take paired identities differ')
    row['x']=((inputs-mu)/sd).astype('float32')
    row['baseline']=(baseline[:,-1]/scale).astype('float32')
    if not np.isfinite(row['x']).all() or not np.isfinite(row['baseline']).all():
        raise ValueError('nonfinite normalized inputs')
    return row


def per_query_metrics(scores, labels):
    values=np.asarray(scores)
    labels=np.asarray(labels)
    if values.dtype!=np.float32 or values.shape!=(48,2) or labels.shape!=(48,) or not np.isfinite(values).all():
        raise ValueError('actual48-query F32 outputs required')
    double=values.astype(np.float64)
    shifted=double-double.max(axis=1,keepdims=True)
    probs=np.exp(shifted)
    probs/=probs.sum(axis=1,keepdims=True)
    return dict(accuracy=(values.argmax(axis=1)==labels).astype(np.float64),
        brier=np.square(probs[:,1]-labels),
        ce=np.log(np.exp(shifted).sum(axis=1))-shifted[np.arange(48),labels])
