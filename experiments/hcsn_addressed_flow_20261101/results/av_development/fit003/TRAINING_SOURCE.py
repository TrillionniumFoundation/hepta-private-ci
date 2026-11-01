"""Common, supervised closed-vocabulary AV encoders with an untouched test gate.

This frontend has an explicit sentence-supervision prior. It is a diagnostic
and reusable shared encoder, not evidence for an analytic dynamic core.
"""

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import resource
import subprocess
import time

import numpy as np
from scipy.fft import dctn
from scipy.special import expit
from scipy.signal import resample_poly


HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "hcsn_four_stage_flow_20261031"
MODALITIES = ("audio", "video", "text")
SLICES = {"audio": slice(0, 64), "video": slice(64, 128), "text": slice(128, 140)}
SOURCE_COMMIT = "1658cd342dff90010aa843eaeebd53610a08b1dc"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(1 << 20), b""):
            h.update(data)
    return h.hexdigest()


def write_json(path, obj):
    path = Path(path)
    payload = json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text() != payload:
            raise FileExistsError(path)
    else:
        path.write_text(payload)


def cpu_seconds():
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time() + children.ru_utime + children.ru_stime


def temporal_features(wave, pixels, timestamps, audio_start, sample_rate):
    """Causal fixed-prefix features; never use end-of-recording normalization."""
    timestamps = np.asarray(timestamps, dtype=float)
    if len(pixels) != len(timestamps) or not np.all(np.diff(timestamps) > 0):
        raise ValueError("Frame timestamps must be strictly increasing")
    origin = max(audio_start, float(timestamps[0]))
    if timestamps[-1] < origin + 1.0:
        raise ValueError("Incomplete one-second video prefix")
    lo = int(np.ceil((origin - audio_start) * sample_rate - 1e-7))
    hi = int(np.floor((origin + 1.0 - audio_start) * sample_rate + 1e-7))
    if lo < 0 or hi > len(wave) or not sample_rate-1 <= hi-lo <= sample_rate:
        raise ValueError("Incomplete native audio prefix")
    window = np.asarray(wave[lo:hi], dtype=float)
    divisor = math.gcd(sample_rate, 16000)
    window = resample_poly(window, 16000 // divisor, sample_rate // divisor,
                           padtype="constant")
    if len(window) > 16000 or len(window) < 15998:
        raise ValueError("Unexpected resampled prefix length")
    window = np.pad(window, (0, 16000-len(window)))
    frames = np.lib.stride_tricks.sliding_window_view(window, 400)[::160]
    power = np.abs(np.fft.rfft(frames * np.hanning(400), n=512)) ** 2
    frequencies = np.fft.rfftfreq(512, 1 / 16000)
    edges = 700 * (10 ** (np.linspace(0, 2595 * np.log10(1 + 8000 / 700), 34)
                         / 2595) - 1)
    filters = np.maximum(0, np.minimum(
        (frequencies[None, :] - edges[:-2, None]) / np.diff(edges)[:-1, None],
        (edges[2:, None] - frequencies[None, :]) / np.diff(edges)[1:, None]))
    mel = np.log(np.maximum(power @ filters.T, 1e-8))
    audio = np.stack([part.mean(0) for part in np.array_split(mel, 20)])
    indices = np.searchsorted(timestamps, origin + np.arange(1, 11) / 10,
                              side="right") - 1
    selected = np.asarray(pixels[indices], dtype=float)[:, 12:40, 16:48] / 255.0
    if selected.shape != (10, 28, 32):
        raise ValueError("Expected 64x48 decoded video")
    transformed = dctn(selected, axes=(-2, -1), norm="ortho")[:, :8, :8]
    centered = transformed - transformed.mean(0, keepdims=True)
    video = np.concatenate((transformed.ravel(), centered.ravel()))
    return {"audio": audio.astype(np.float32).ravel(),
            "video": video.astype(np.float32)}, {
                "origin": origin, "accepted_end": origin + 1.0,
                "last_selected_frame": float(timestamps[indices[-1]]),
                "native_audio_samples": hi - lo}


def decode(path):
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-show_frames", "-show_entries",
        "stream=codec_type,start_time,sample_rate:frame=media_type,best_effort_timestamp_time",
        "-of", "json", str(path)]))
    timestamps = np.array([float(r["best_effort_timestamp_time"])
                          for r in probe["frames"] if r.get("media_type") == "video"])
    audio = next(r for r in probe["streams"] if r["codec_type"] == "audio")
    start, rate = float(audio.get("start_time", 0)), int(audio["sample_rate"])
    command = ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-threads", "1",
               "-i", str(path)]
    wave = np.frombuffer(subprocess.check_output(command + ["-map", "0:a:0", "-ac", "1",
        "-threads", "1", "-f", "f32le", "-"]), dtype="<f4")
    pixels = np.frombuffer(subprocess.check_output(command + ["-map", "0:v:0", "-an",
        "-vf", "scale=64:48:flags=area,format=gray", "-filter_threads", "1",
        "-threads", "1", "-vsync", "0", "-f", "rawvideo", "-"]), dtype=np.uint8)
    return temporal_features(wave, pixels.reshape(-1, 48, 64), timestamps, start, rate)


def mouth_features(pixels, timestamps, origin):
    """One-second final-prefix descriptor; subtract static facial appearance."""
    timestamps=np.asarray(timestamps,dtype=float)
    if timestamps[-1] < origin+1.0 or not np.all(np.diff(timestamps)>0):
        raise ValueError('Incomplete or unordered video prefix')
    indices=np.searchsorted(timestamps,origin+np.arange(1,11)/10,side='right')-1
    crop=np.asarray(pixels[indices],dtype=float)[:,21:34,24:42]/255.0
    if crop.shape!=(10,13,18): raise ValueError('Expected 64x48 video')
    # All statistics are restricted to the accepted prefix, never whole media.
    scale=max(float(crop.std()),.01)
    residual=(crop-np.median(crop,axis=0,keepdims=True))/scale
    coeff=dctn(residual,axes=(-2,-1),norm='ortho')[:,:6,:6]
    return np.concatenate((coeff.ravel(),np.diff(coeff,axis=0).ravel())).astype(np.float32)


def prepare_mouth(media_root,out,splits,candidate_freeze=None,cohort_path=None):
    if any(s not in ('train','validation') for s in splits):
        if candidate_freeze is None: raise ValueError('Confirmation requires candidate freeze')
        validate_confirmation_cohort(cohort_path or BASE/'data/COHORT.json',candidate_freeze)
    wall,cpu=time.perf_counter(),cpu_seconds();out=Path(out);out.mkdir(parents=True,exist_ok=True)
    cohort=json.loads(Path(cohort_path or BASE/'data/COHORT.json').read_text())
    rows=[r for r in cohort['records'] if r['split'] in splits]
    for row in rows:
        path=Path(media_root)/(row['clip']+'.flv');target=out/(row['clip']+'.npz')
        if target.exists(): raise FileExistsError(target)
        if path.stat().st_size!=row['bytes'] or digest(path)!=row['sha256']:
            raise ValueError('Media identity mismatch')
        probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_frames',
            '-show_entries','stream=codec_type,start_time:frame=media_type,best_effort_timestamp_time','-of','json',str(path)]))
        ts=np.array([float(r['best_effort_timestamp_time']) for r in probe['frames'] if r.get('media_type')=='video'])
        audio=next(r for r in probe['streams'] if r['codec_type']=='audio')
        origin=max(float(audio.get('start_time',0)),float(ts[0]))
        raw=subprocess.check_output(['ffmpeg','-nostdin','-v','error','-xerror','-threads','1','-i',str(path),
            '-map','0:v:0','-an','-vf','scale=64:48:flags=area,format=gray','-filter_threads','1','-threads','1','-vsync','0','-f','rawvideo','-'])
        features=mouth_features(np.frombuffer(raw,dtype=np.uint8).reshape(-1,48,64),ts,origin)
        with target.open('xb') as stream: np.savez_compressed(stream,video=features)
        write_json(target.with_suffix('.json'),dict(raw_sha256=row['sha256'],sha256=digest(target),source_sha256=digest(__file__)))
    receipt=dict(splits=splits,clips=len(rows),cpu_seconds=cpu_seconds()-cpu,wall_seconds=time.perf_counter()-wall,
        source_sha256=digest(__file__),energy_joules=None,observation_seconds=1.,feature='within-prefix mouth motion')
    write_json(out/('PREPARE_'+'_'.join(splits)+'.json'),receipt)
    return receipt


def load_freeze(path):
    value = json.loads(Path(path).read_text())
    if value["source_sha256"] != digest(__file__):
        raise ValueError("Frontend source changed after freeze")
    if value["protocol_sha256"] != digest(HERE / "av_frontend_protocol.json"):
        raise ValueError("Protocol changed after freeze")
    for row in value["checkpoints"]:
        if digest(Path(path).parent / row["file"]) != row["sha256"]:
            raise ValueError("Checkpoint changed after freeze")
    if digest(Path(path).parent/'DEVELOPMENT.json') != value['development_sha256']:
        raise ValueError('Development evidence changed after freeze')
    return value


def validate_confirmation_cohort(cohort_path,candidate_freeze):
    frozen=load_freeze(candidate_freeze)
    if digest(cohort_path)==digest(BASE/'data/COHORT.json'): return
    cohort=json.loads(Path(cohort_path).read_text())
    keys=('actor','sentence','emotion','clip','sha256','bytes')
    records=[{k:r[k] for k in keys} for r in cohort['records'] if r['split']=='test']
    value=hashlib.sha256(json.dumps(sorted(records,key=lambda r:r['clip']),sort_keys=True).encode()).hexdigest()
    if value!=frozen['independent_cohort']['core_records_sha256']:
        raise ValueError('Confirmation source records differ from frozen cohort')


def prepare(media_root, out, splits, candidate_freeze=None, cohort_path=None):
    wall, cpu = time.perf_counter(), cpu_seconds()
    if any(s not in ("train", "validation") for s in splits):
        if candidate_freeze is None:
            raise ValueError("Confirmation extraction requires a candidate freeze")
        validate_confirmation_cohort(cohort_path or BASE/'data/COHORT.json',candidate_freeze)
    cohort = json.loads(Path(cohort_path or BASE / "data/COHORT.json").read_text())
    out, media_root = Path(out), Path(media_root)
    out.mkdir(parents=True, exist_ok=True)
    records = [r for r in cohort["records"] if r["split"] in splits]
    if not records:
        raise ValueError("No records for requested splits")
    for count, row in enumerate(records):
        path = media_root / (row["clip"] + ".flv")
        target = out / (row["clip"] + ".npz")
        if path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
            raise ValueError("Media identity mismatch: " + row["clip"])
        if target.exists():
            receipt = json.loads(target.with_suffix(".json").read_text())
            if receipt["source_sha256"] != digest(__file__) or receipt["sha256"] != digest(target):
                raise ValueError("Stale feature cache")
            continue
        tick, clock = cpu_seconds(), time.perf_counter()
        features, detail = decode(path)
        with target.open("xb") as stream:
            np.savez_compressed(stream, **features)
        write_json(target.with_suffix(".json"), dict(
            raw_sha256=row["sha256"], sha256=digest(target), source_sha256=digest(__file__),
            cpu_seconds=cpu_seconds()-tick, wall_seconds=time.perf_counter()-clock,
            feature_dimensions={k: len(v) for k,v in features.items()}, detail=detail))
        if (count + 1) % 48 == 0:
            print(json.dumps({"prepared": count+1, "total": len(records)}), flush=True)
    receipt = dict(splits=splits, clips=len(records), cpu_seconds=cpu_seconds()-cpu,
        wall_seconds=time.perf_counter()-wall, source_sha256=digest(__file__),
        energy_joules=None, cost_scope="Whole-file decoder children and feature preparation; no download cost")
    write_json(out / ("PREPARE_" + "_".join(splits) + ".json"), receipt)
    return receipt


def load_data(data_root, temporal_root, split, mouth_root=None):
    with np.load(Path(data_root) / f"{split}.npz", allow_pickle=False) as z:
        arrays = {k: z[k] for k in z.files}
    features = {}
    for i, mod in enumerate(MODALITIES):
        features[mod, "baseline"] = arrays["x"][:, :, SLICES[mod]].reshape(len(arrays["y"]), -1)
        if mod == "text":
            continue
        values = []
        for a, e, sentence in zip(arrays["actor"], arrays["emotion"], arrays["sentence_indices"][:,i]):
            with np.load(Path(temporal_root) / f"{a}_{('DFA','IOM')[sentence]}_{e}_XX.npz") as z:
                values.append(z[mod])
        features[mod, "temporal"] = np.stack(values)
        if mod=='video' and mouth_root is not None:
            values=[]
            for a,e,sentence in zip(arrays['actor'],arrays['emotion'],arrays['sentence_indices'][:,i]):
                with np.load(Path(mouth_root)/f"{a}_{('DFA','IOM')[sentence]}_{e}_XX.npz") as z:
                    values.append(z['video'])
            features[mod,'mouth_motion']=np.stack(values)
    return arrays, features


def unique_indices(arrays, modality):
    i = MODALITIES.index(modality)
    keys = zip(arrays["actor"], arrays["emotion"], arrays["sentence_indices"][:,i])
    seen = {}
    for index, key in enumerate(keys):
        seen.setdefault(key, index)
    return np.array(list(seen.values()))


def infer(checkpoint, x):
    """Portable NumPy forward pass; accepts content features only."""
    x = np.asarray(x,dtype=np.float64)
    if int(checkpoint['kind'])==2: x=x[:,:360]
    x = (x - checkpoint["mean"]) / checkpoint["scale"]
    if int(checkpoint["kind"]) == 0:
        margin = x @ checkpoint["coef"] + checkpoint["intercept"]
    elif int(checkpoint['kind'])==1:
        support = checkpoint["support"]
        distance = np.maximum(0, (x*x).sum(1)[:,None] + (support*support).sum(1)[None,:]
                              - 2*x@support.T)
        margin = np.exp(-float(checkpoint["gamma"]) * distance) @ checkpoint["dual"]
        margin += checkpoint["intercept"]
    else:
        margin=dtw_margin(x,checkpoint['support'],checkpoint['labels'])
    return expit(checkpoint["cal_coef"] * margin + checkpoint["cal_intercept"])


def dtw_margin(x,support,labels):
    """Fixed bandwidth-two DTW and mean three-nearest distance per class."""
    x=x.reshape(-1,10,36);support=support.reshape(-1,10,36)
    previous=np.full((11,len(x),len(support)),np.inf);previous[0]=0
    for i in range(1,11):
        current=np.full_like(previous,np.inf)
        a=x[:,i-1];aa=(a*a).sum(1)[:,None]
        for j in range(max(1,i-2),min(10,i+2)+1):
            b=support[:,j-1]
            local=np.maximum(aa+(b*b).sum(1)[None,:]-2*a@b.T,0)/36
            current[j]=local+np.minimum(np.minimum(previous[j],current[j-1]),previous[j-1])
        previous=current
    distances=previous[10]/20
    nearest=[]
    for label in (0,1):
        values=distances[:,labels==label];k=min(3,values.shape[1])
        nearest.append(np.partition(values,k-1,axis=1)[:,:k].mean(1))
    return (nearest[0]-nearest[1])/(nearest[0]+nearest[1]+1e-12)


def fit_decoder(x, y, actors, kind, c):
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupKFold
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC
    if kind=='dtw':
        def normalize(training,query):
            points=training[:,:360].reshape(-1,36)
            mean=np.tile(points.mean(0),10);scale=np.tile(np.maximum(points.std(0),.01),10)
            return (training[:,:360]-mean)/scale,(query[:,:360]-mean)/scale,mean,scale
        scores=np.zeros(len(y))
        for train,held in GroupKFold(n_splits=4).split(x,y,actors):
            support,query,_,_=normalize(x[train],x[held])
            scores[held]=dtw_margin(query,support,y[train])
        calibrator=LogisticRegression(C=1,max_iter=1000).fit(scores[:,None],y)
        support,_,mean,scale=normalize(x,x)
        cp=dict(kind=np.array(2),mean=mean,scale=scale,support=support,labels=y,
            cal_coef=calibrator.coef_[0,0],cal_intercept=calibrator.intercept_[0])
        return cp,expit(calibrator.decision_function(scores[:,None]))
    def fit_base(xx, yy):
        scaler = StandardScaler().fit(xx)
        transformed = scaler.transform(xx)
        model = (LogisticRegression(C=c, max_iter=1000) if kind == "logistic" else
                 SVC(C=c, kernel="rbf", probability=False)).fit(transformed, yy)
        return scaler, model
    scores = np.zeros(len(y))
    for train, held in GroupKFold(n_splits=4).split(x, y, actors):
        scaler, model = fit_base(x[train], y[train])
        scores[held] = model.decision_function(scaler.transform(x[held]))
    calibrator = LogisticRegression(C=1, max_iter=1000).fit(scores[:,None], y)
    scaler, model = fit_base(x, y)
    cp = dict(kind=np.array(0 if kind == "logistic" else 1), mean=scaler.mean_,
              scale=scaler.scale_, intercept=model.intercept_[0],
              cal_coef=calibrator.coef_[0,0], cal_intercept=calibrator.intercept_[0])
    if kind == "logistic":
        cp["coef"] = model.coef_[0]
    else:
        cp.update(support=model.support_vectors_, dual=model.dual_coef_[0], gamma=np.array(model._gamma))
    return cp, expit(calibrator.decision_function(scores[:,None]))


def log_loss(y, p):
    p = np.clip(p, 1e-12, 1-1e-12)
    return float(-np.mean(y*np.log(p)+(1-y)*np.log1p(-p)))


def relation_features(probabilities):
    p = np.asarray(probabilities, dtype=float)
    return np.column_stack([np.prod(p[:,group], axis=1) for size in range(1,4)
                            for group in itertools.combinations(range(3),size)])


def constructed_posterior(probabilities):
    p = np.asarray(probabilities, dtype=float)
    q = p.prod(1)+(1-p).prod(1)
    return 3*q/(1+2*q)


def train(data_root, temporal_root, out, mouth_root=None):
    from sklearn.linear_model import LogisticRegression
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    wall, cpu = time.perf_counter(), cpu_seconds()
    train_data, train_features = load_data(data_root, temporal_root, "train",mouth_root)
    val_data, val_features = load_data(data_root, temporal_root, "validation",mouth_root)
    candidates, selected, train_p, val_p, cross_p = [], {}, [], [], []
    for mi, modality in enumerate(MODALITIES):
        ti, vi = unique_indices(train_data, modality), unique_indices(val_data, modality)
        candidates_mod = []
        available_features=[name for mod,name in train_features if mod==modality]
        for feature in available_features:
            kinds=("logistic",) if modality=='text' else (('logistic','rbf','dtw') if feature=='mouth_motion' else ('logistic','rbf'))
            for kind in kinds:
                for c in ((1.0,) if modality == "text" or kind=='dtw' else (.01,.1,1.,10.,100.)):
                    tick = cpu_seconds()
                    x, y = train_features[modality,feature][ti], train_data["sentence_indices"][ti,mi]
                    cp, cross = fit_decoder(x, y, train_data["actor"][ti], kind, c)
                    vp = infer(cp,val_features[modality,feature][vi]); vy=val_data["sentence_indices"][vi,mi]
                    row = dict(modality=modality,feature=feature,estimator=kind,C=c,
                        validation_accuracy=float(np.mean((vp>=.5)==vy)),validation_log_loss=log_loss(vy,vp),
                        train_accuracy=float(np.mean((infer(cp,x)>=.5)==y)),cpu_seconds=cpu_seconds()-tick)
                    candidates.append(row); candidates_mod.append((row,cp,cross))
        _, (row,cp,cross) = min(enumerate(candidates_mod),key=lambda e:(-e[1][0]["validation_accuracy"],e[1][0]["validation_log_loss"],e[0]))
        destination=out/f"{modality}_encoder.npz"
        with destination.open("xb") as stream:
            np.savez_compressed(stream,**cp)
        selected[modality]=row|dict(checkpoint=destination.name,sha256=digest(destination))
        feature=row["feature"]
        train_p.append(infer(cp,train_features[modality,feature]));val_p.append(infer(cp,val_features[modality,feature]))
        mapping={(a,e,int(s[mi])):float(p) for a,e,s,p in zip(train_data['actor'][ti],train_data['emotion'][ti],train_data['sentence_indices'][ti],cross)}
        cross_p.append(np.array([mapping[a,e,int(s[mi])] for a,e,s in zip(train_data['actor'],train_data['emotion'],train_data['sentence_indices'])]))
        print(json.dumps({"selected":modality,**row}),flush=True)
    train_p,val_p,cross_p=np.stack(train_p,1),np.stack(val_p,1),np.stack(cross_p,1)
    relation=LogisticRegression(C=1,max_iter=1000).fit(relation_features(cross_p),train_data['y'],sample_weight=train_data['sample_weight'])
    with (out/'relation_head.npz').open('xb') as stream:
        np.savez_compressed(stream,coef=relation.coef_[0],intercept=relation.intercept_[0])
    np.savez_compressed(out/'development_probabilities.npz',train=train_p,validation=val_p,train_actor_crossfit=cross_p)
    report=dict(schema='hcsn.av.development.v2',selected=selected,candidates=candidates,
        validation=evaluate_arrays(val_data,val_p,dict(coef=relation.coef_[0],intercept=relation.intercept_[0])),
        train_data_sha256=digest(Path(data_root)/'train.npz'),validation_data_sha256=digest(Path(data_root)/'validation.npz'),
        cpu_seconds=cpu_seconds()-cpu,wall_seconds=time.perf_counter()-wall,energy_joules=None,
        scope='Auxiliary-supervised common frontend; no analytic-core claim; confirmation not loaded')
    write_json(out/'DEVELOPMENT.json',report)
    return report


def evaluate_arrays(arrays, probabilities, relation):
    results={}; y,w=arrays['y'],arrays['sample_weight']; actors=np.unique(arrays['actor'])
    rng=np.random.default_rng(71); samples=rng.integers(len(actors),size=(10000,len(actors)))
    for size in range(4):
        for visible in itertools.combinations(range(3),size):
            p=np.full_like(probabilities,.5);p[:,visible]=probabilities[:,visible]
            name='+'.join(MODALITIES[i] for i in visible) or 'none'
            posterior=constructed_posterior(p)
            learned=expit(relation_features(p)@relation['coef']+relation['intercept'])
            results[name]={}
            for head,scores in [('construction',posterior),('learned',learned)]:
                correct=(scores>=.5)==y;actor_rates=np.array([np.average(correct[arrays['actor']==a],weights=w[arrays['actor']==a]) for a in actors])
                boot=actor_rates[samples].mean(1)
                results[name][head]=dict(accuracy=float(np.average(correct,weights=w)),
                    actor_bootstrap_95=np.quantile(boot,[.025,.975]).tolist(),
                    brier=float(np.average((scores-y)**2,weights=w)),
                    weighted_confusion=[[float(w[(y==truth)&((scores>=.5)==pred)].sum()) for pred in (0,1)] for truth in (0,1)])
    return results


def freeze(out,independent_cohort_plan=None):
    out=Path(out);development=json.loads((out/'DEVELOPMENT.json').read_text())
    checkpoints=[dict(file=f.name,sha256=digest(f)) for f in sorted(out.glob('*encoder.npz'))]
    checkpoints.append(dict(file='relation_head.npz',sha256=digest(out/'relation_head.npz')))
    value=dict(schema='hcsn.av.candidate.freeze.v2',source_sha256=digest(__file__),
        protocol_sha256=digest(HERE/'av_frontend_protocol.json'),checkpoints=checkpoints,
        development_sha256=digest(out/'DEVELOPMENT.json'),selected=development['selected'])
    if independent_cohort_plan is not None:
        plan=json.loads(Path(independent_cohort_plan).read_text())
        old=json.loads((BASE/'data/COHORT.json').read_text())
        if set(plan['actors']) & set(sum(old['splits'].values(),[])):
            raise ValueError('Independent actors overlap prior cohort')
        value['independent_cohort']=dict(sha256=digest(independent_cohort_plan),actors=plan['actors'],
            records_sha256=hashlib.sha256(json.dumps(plan['records'],sort_keys=True).encode()).hexdigest(),
            core_records_sha256=hashlib.sha256(json.dumps(sorted([{k:r[k] for k in ('actor','sentence','emotion','clip','sha256','bytes')} for r in plan['records']],key=lambda r:r['clip']),sort_keys=True).encode()).hexdigest())
    write_json(out/'CANDIDATES.json',value)
    return value


def confirm(data_root, temporal_root, out, candidate_freeze, split='test',mouth_root=None):
    frozen=load_freeze(candidate_freeze);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    wall,cpu=time.perf_counter(),cpu_seconds(); model_root=Path(candidate_freeze).parent
    arrays,features=load_data(data_root,temporal_root,split,mouth_root);probs=[];models=[]
    if split=='independent_test' and set(arrays['actor'])!=set(frozen['independent_cohort']['actors']):
        raise ValueError('Independent confirmation actors differ from frozen cohort')
    for modality in MODALITIES:
        info=frozen['selected'][modality]
        with np.load(model_root/info['checkpoint']) as z: cp={k:z[k] for k in z}
        x=features[modality,info['feature']];probs.append(infer(cp,x));models.append((cp,x))
    probs=np.stack(probs,1)
    with np.load(model_root/'relation_head.npz') as z: relation={k:z[k] for k in z}
    latency={}
    for batch in (1,len(probs)):
        times=[]
        for repeat in range(36):
            tick=time.perf_counter();p=np.stack([infer(cp,x[:batch]) for cp,x in models],1)
            constructed_posterior(p)
            if repeat>=5: times.append(time.perf_counter()-tick)
        latency[str(batch)]=dict(batch=batch,repetitions=31,median_seconds=float(np.median(times)),
            p95_seconds=float(np.quantile(times,.95)),episodes_per_second=batch/float(np.median(times)))
    sentence={}
    for i,modality in enumerate(MODALITIES):
        ix=unique_indices(arrays,modality)
        sentence[modality]=float(np.mean((probs[ix,i]>=.5)==arrays['sentence_indices'][ix,i]))
    scores=evaluate_arrays(arrays,probs,relation)
    result=dict(schema='hcsn.av.confirmation.v2',split=split,actors=np.unique(arrays['actor']).tolist(),
        sentence_accuracy=sentence,consistency=scores,latency=latency,
        data_sha256=digest(Path(data_root)/f'{split}.npz'),candidate_freeze_sha256=digest(candidate_freeze),
        cpu_seconds=cpu_seconds()-cpu,wall_seconds=time.perf_counter()-wall,energy_joules=None,
        frontend_qualified=bool(sentence['audio']>=.9 and sentence['video']>=.9 and scores['audio+video+text']['construction']['actor_bootstrap_95'][0]>5/6),
        scope='Closed vocabulary auxiliary-supervised frontend; ordinary shared baseline; no dynamic-core attribution',
        confirmation_status='Locked reevaluation on previously studied actors' if split=='test' else 'Independent actor confirmation')
    np.savez_compressed(out/'predictions.npz',probabilities=probs,y=arrays['y'],sample_weight=arrays['sample_weight'],actor=arrays['actor'],sentence_indices=arrays['sentence_indices'])
    write_json(out/'CONFIRMATION.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('prepare','prepare-mouth','train','freeze','confirm'))
    parser.add_argument('--data-root',type=Path)
    parser.add_argument('--temporal-root',type=Path)
    parser.add_argument('--mouth-root',type=Path)
    parser.add_argument('--independent-cohort-plan',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--media-root',type=Path)
    parser.add_argument('--splits',nargs='+',default=['train','validation'])
    parser.add_argument('--split',default='test')
    parser.add_argument('--cohort-path',type=Path)
    parser.add_argument('--candidate-freeze',type=Path)
    a=parser.parse_args()
    if a.mode=='prepare': result=prepare(a.media_root,a.out,a.splits,a.candidate_freeze,a.cohort_path)
    elif a.mode=='prepare-mouth': result=prepare_mouth(a.media_root,a.out,a.splits,a.candidate_freeze,a.cohort_path)
    elif a.mode=='train': result=train(a.data_root,a.temporal_root,a.out,a.mouth_root)
    elif a.mode=='freeze': result=freeze(a.out,a.independent_cohort_plan)
    else: result=confirm(a.data_root,a.temporal_root,a.out,a.candidate_freeze,a.split,a.mouth_root)
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':
    main()
