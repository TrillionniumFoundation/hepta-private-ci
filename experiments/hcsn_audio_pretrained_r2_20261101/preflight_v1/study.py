"""Fixed C=1 actor-crossfit audio head and separately frozen relation heads."""

import argparse
import importlib
import itertools
import json
from pathlib import Path
import re
import time

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
import torch
import torchaudio

from experiments.hcsn_video_followup_20261101 import study as r1
from . import encoder


HERE, ROOT = encoder.HERE, encoder.ROOT
PREVIOUS = HERE.parent / "hcsn_video_followup_20261101"
OLD = PREVIOUS / "results/run002"
FITS = []
RUNTIME_MODULES = ("torchaudio.pipelines._wav2vec2.impl", "torchaudio.pipelines._wav2vec2.utils",
                   "torchaudio.models.wav2vec2.model", "torchaudio.models.wav2vec2.components")


def dependency_paths():
    return [Path(r1.__file__), PREVIOUS / "INPUT_IDENTITY.json", OLD / "CANDIDATE_FREEZE.json",
            OLD / "TRAINING.json", OLD / "TRAIN_OOF.npz", OLD / "text_encoder.npz", OLD / "video_encoder.npz"]


def freeze_source():
    checks = json.loads((HERE / "CHECKS.json").read_text())
    if not checks["passed"]:
        raise ValueError("Official encoder preflight must pass before source publication")
    paths = [HERE / name for name in ("acquire.py", "encoder.py", "study.py", "checks.py", "PROTOCOL.json",
                                      "CHECKPOINT.json", "TRAIN_COHORT.json", "CHECKS.json")]
    paths += dependency_paths()
    result = dict(schema="hcsn.audio.pretrained.source-freeze.v1", created_unix_ns=time.time_ns(),
        source={str(p.relative_to(ROOT)): encoder.sha(p) for p in paths},
        runtime_source_sha256={name:encoder.sha(importlib.import_module(name).__file__) for name in RUNTIME_MODULES},
        checkpoint_sha256=encoder.CHECKPOINT_SHA256, development_loaded=False,
        runtime=dict(torch=torch.__version__, torchaudio=torchaudio.__version__, numpy=np.__version__),
        protocol_sha256=encoder.sha(HERE / "PROTOCOL.json"))
    encoder.write(HERE / "SOURCE_FREEZE.json", result)
    return result


def runtime_guard(frozen):
    if any(encoder.sha(importlib.import_module(name).__file__) != value
           for name, value in frozen["runtime_source_sha256"].items()):
        raise ValueError("Official installed encoder implementation changed")


def train_arrays():
    path = PREVIOUS / "inputs/data/train.npz"
    expected = next(r["sha256"] for r in json.loads((PREVIOUS / "INPUT_IDENTITY.json").read_text())["files"]
                    if r["path"] == "inputs/data/train.npz")
    if encoder.sha(path) != expected:
        raise ValueError("R1 training episode identity differs")
    with np.load(path, allow_pickle=False) as z:
        return {k:z[k] for k in z.files}


def load_features(directory, split):
    identity = json.loads((directory / "IDENTITY.json").read_text())
    if (identity["split"] != split or identity["features_sha256"] != encoder.sha(directory / "features.npz")
            or identity["checkpoint_sha256"] != encoder.CHECKPOINT_SHA256
            or identity["source_sha256"] != encoder.sha(HERE / "encoder.py")):
        raise ValueError("Frozen audio feature identity differs")
    if split == "train" and identity["manifest_sha256"] != encoder.sha(HERE / "TRAIN_COHORT.json"):
        raise ValueError("Training manifest identity differs")
    with np.load(directory / "features.npz", allow_pickle=False) as z:
        a = {k:z[k] for k in z.files}
    expected = np.asarray([encoder.SENTENCES.index(str(c).split("_")[1]) for c in a["clip"]])
    if (not np.array_equal(a["label"], expected) or a["features"].shape != (len(a["label"]), encoder.FEATURE_WIDTH)
            or not np.array_equal(a["actor"], np.asarray([str(c).split("_")[0] for c in a["clip"]]))):
        raise ValueError("Binary sentence labels and exact descriptor width required")
    return a


def fit(x, y, weights=None, tag=""):
    started = time.process_time()
    x, y = np.asarray(x, np.float64), np.asarray(y, np.float64)
    if not set(np.unique(y)) <= {0., 1.} or not np.isfinite(x).all():
        raise ValueError("Finite features and binary targets required")
    mean, scale = x.mean(0), np.maximum(x.std(0), 1e-8)
    xx = (x - mean) / scale
    w = np.ones(len(y)) if weights is None else np.asarray(weights, np.float64)
    def objective(beta):
        margin = xx @ beta[:-1] + beta[-1]
        residual = w * (expit(margin) - y)
        loss = np.dot(w, np.logaddexp(0, margin) - y*margin) + .5*np.dot(beta[:-1], beta[:-1])
        return float(loss), np.r_[xx.T @ residual + beta[:-1], residual.sum()]
    result = minimize(objective, np.zeros(x.shape[1]+1), jac=True, method="L-BFGS-B",
                      options={"maxiter":2000, "ftol":1e-12, "gtol":1e-7})
    FITS.append(dict(tag=tag, rows=len(y), features=x.shape[1], C=1., success=bool(result.success),
                     status=int(result.status), iterations=int(result.nit), gradient_inf=float(np.abs(result.jac).max()),
                     cpu_seconds=time.process_time()-started))
    if not result.success:
        raise RuntimeError("Predeclared logistic optimizer did not converge: " + str(result.message))
    return dict(mean=mean, scale=scale, beta=result.x)


def predict(head, x):
    return expit(((np.asarray(x, np.float64)-head["mean"])/head["scale"]) @ head["beta"][:-1] + head["beta"][-1])


def relation_features(probabilities, name):
    if name == "AT_unique":
        return np.column_stack((probabilities[:,0], probabilities[:,2], probabilities[:,0]*probabilities[:,2]))
    return np.column_stack([np.prod(probabilities[:,group], axis=1) for n in range(1,4)
                            for group in itertools.combinations(range(3),n)])


def map_audio(episodes, clips, probabilities):
    mapping = dict(zip(clips.tolist(), probabilities.tolist(), strict=True))
    return np.asarray([mapping[f"{actor}_{encoder.SENTENCES[int(s[0])]}_{emotion}_XX"]
                       for actor, emotion, s in zip(episodes["actor"], episodes["emotion"], episodes["sentence_indices"], strict=True)])


def candidate_guard(out=None):
    frozen_source = encoder.source_guard(); runtime_guard(frozen_source)
    out = Path(out or HERE / "results/run001")
    frozen = json.loads((out / "CANDIDATE_FREEZE.json").read_text())
    publication = json.loads((HERE / "CANDIDATE_PUBLICATION.json").read_text())
    if publication["candidate_freeze_sha256"] != encoder.sha(out / "CANDIDATE_FREEZE.json"):
        raise ValueError("Remote candidate publication identity differs")
    if not re.fullmatch(r"[0-9a-f]{40}", publication["source_commit"]):
        raise ValueError("Remote candidate commit is required")
    if (frozen["source_freeze_sha256"] != encoder.sha(HERE / "SOURCE_FREEZE.json")
            or any(encoder.sha(out / name) != value for name, value in frozen["files"].items())):
        raise ValueError("Frozen candidate source or artifact changed")
    original = Path(frozen["input_features_path"])
    if (encoder.sha(original / "features.npz") != frozen["input_features_sha256"]
            or encoder.sha(original / "IDENTITY.json") != frozen["input_identity_sha256"]):
        raise ValueError("Frozen training feature artifact changed")
    return frozen


def validation_manifest_guard(manifest):
    candidate_guard()
    records = json.loads(Path(manifest).read_text())["records"]
    encoder.target_guard(records, "validation")
    # Read only the original six-actor validation records after candidate
    # publication. Never parse old-test/1019 media or the full old cohort.
    identity = {r["path"]:r["sha256"] for r in json.loads((PREVIOUS / "INPUT_IDENTITY.json").read_text())["files"]}
    path = PREVIOUS / "inputs/data/validation.npz"
    if encoder.sha(path) != identity["inputs/data/validation.npz"]:
        raise ValueError("Original historical validation identity differs")
    with np.load(path, allow_pickle=False) as z:
        wanted = {f"{a}_{s}_{e}_XX" for a,e in zip(z["actor"],z["emotion"],strict=True) for s in encoder.SENTENCES}
    if len(records) != 72 or {r["clip"] for r in records} != wanted:
        raise ValueError("Exactly original72 six-actor validation clips required")
    for row in records:
        name = f"inputs/av_features/{row['clip']}.json"
        source = PREVIOUS / name
        if encoder.sha(source) != identity[name] or json.loads(source.read_text())["raw_sha256"] != row["sha256"]:
            raise ValueError("Validation raw bytes differ from inherited pinned source")


def train(features, out):
    frozen = encoder.source_guard(); runtime_guard(frozen)
    out.mkdir(parents=True, exist_ok=False)
    clock, cpu = time.perf_counter(), time.process_time()
    arrays = load_features(features, "train")
    cohort = json.loads((HERE / "TRAIN_COHORT.json").read_text())["records"]
    wanted = {r["clip"] for r in cohort}; encoder.target_guard(cohort, "train")
    if set(arrays["clip"].tolist()) != wanted or len(arrays["label"]) != 288:
        raise ValueError("Train clip set differs")
    actors = np.unique(arrays["actor"])
    if len(actors) != 24:
        raise ValueError("Original24 train actors required")
    scores = np.empty(288, np.float64); folds = []
    for fold in range(4):
        held = np.isin(arrays["actor"], actors[fold::4])
        head = fit(arrays["features"][~held], arrays["label"][~held], tag=f"audio/fold{fold}")
        scores[held] = predict(head, arrays["features"][held])
        np.savez_compressed(out / f"audio_fold{fold}.npz", **head)
        folds.append(dict(fold=fold, fit_actors=np.unique(arrays["actor"][~held]).tolist(),
                          held_actors=np.unique(arrays["actor"][held]).tolist(),
                          held_clips=arrays["clip"][held].tolist(),
                          accuracy=float(np.mean((scores[held]>=.5)==arrays["label"][held]))))
    full = fit(arrays["features"], arrays["label"], tag="audio/full")
    np.savez_compressed(out / "audio_full_head.npz", **full)
    np.savez_compressed(out / "TRAIN_OOF.npz", audio=scores, clip=arrays["clip"], actor=arrays["actor"], label=arrays["label"])
    episodes = train_arrays()
    with np.load(OLD / "TRAIN_OOF.npz", allow_pickle=False) as z:
        if not np.array_equal(z["actor"],episodes["actor"]) or not np.array_equal(z["sentence_indices"],episodes["sentence_indices"]) or not np.array_equal(z["y"],episodes["y"]):
            raise ValueError("Inherited relation OOF identity differs")
        p = z["probabilities"].copy()
    p[:,0] = map_audio(episodes, arrays["clip"], scores)
    for name in ("AT_unique", "AVT_R1V"):
        head = fit(relation_features(p,name), episodes["y"], episodes["sample_weight"], "relation/"+name)
        np.savez_compressed(out / (name+"_head.npz"), **head)
    np.savez_compressed(out / "RELATION_TRAIN_OOF.npz", probabilities=p, actor=episodes["actor"],
                        y=episodes["y"], sample_weight=episodes["sample_weight"], sentence_indices=episodes["sentence_indices"])
    encoder.write(out / "TRAINING.json", dict(folds=folds, fits=FITS,
        sentence_oof_accuracy=float(np.mean((scores>=.5)==arrays["label"])),
        input_features_sha256=encoder.sha(features / "features.npz"),
        input_identity_sha256=encoder.sha(features / "IDENTITY.json"),
        body_cpu_seconds=time.process_time()-cpu, body_wall_seconds=time.perf_counter()-clock,
        development_loaded=False, hyperparameter_selection=False, pooled_oof_recalibration=False))
    files = {p.name:encoder.sha(p) for p in out.iterdir() if p.is_file()}
    encoder.write(out / "CANDIDATE_FREEZE.json", dict(schema="hcsn.audio.pretrained.candidate.v1",
        source_freeze_sha256=encoder.sha(HERE / "SOURCE_FREEZE.json"), files=files,
        input_features_path=str(features), input_features_sha256=encoder.sha(features / "features.npz"),
        input_identity_sha256=encoder.sha(features / "IDENTITY.json"),
        checkpoint_sha256=encoder.CHECKPOINT_SHA256, development_loaded=False, created_unix_ns=time.time_ns()))
    print(json.dumps(dict(audio_oof_accuracy=float(np.mean((scores>=.5)==arrays["label"])), fits=len(FITS))))


def evaluate(features, out):
    candidate_guard(out)
    audio = load_features(features, "validation")
    probabilities = predict(dict(np.load(out / "audio_full_head.npz", allow_pickle=False)), audio["features"])
    episodes, old_features = r1.load("validation")
    old_training = json.loads((OLD / "TRAINING.json").read_text())
    video_kind = old_training["selected"]["video"]["selected"]["feature"]
    video = r1.predict(dict(np.load(OLD / "video_encoder.npz", allow_pickle=False)), old_features["video",video_kind])
    text = r1.predict(dict(np.load(OLD / "text_encoder.npz", allow_pickle=False)), old_features["text","baseline"])
    p = np.column_stack((map_audio(episodes,audio["clip"],probabilities), video, text))
    predictions = {name:predict(dict(np.load(out/(name+"_head.npz"),allow_pickle=False)),relation_features(p,name))
                   for name in ("AT_unique","AVT_R1V")}
    y, w, actors = episodes["y"],episodes["sample_weight"],np.unique(episodes["actor"])
    differences=[]
    for actor in actors:
        ix=episodes["actor"]==actor
        av,at=predictions["AVT_R1V"][ix],predictions["AT_unique"][ix]
        differences.append([np.average(((av>=.5)==y[ix]).astype(float)-((at>=.5)==y[ix]),weights=w[ix]),
                            np.average((av-y[ix])**2-(at-y[ix])**2,weights=w[ix])])
    differences=np.asarray(differences);rng=np.random.default_rng(20261110)
    boot=differences[rng.integers(len(actors),size=(10000,len(actors)))].mean(1)
    accuracy=float(np.mean((probabilities>=.5)==audio["label"]))
    result=dict(schema="hcsn.audio.pretrained.development.v1", scope="Original historically exposed six-actor development only",
        audio_sentence_accuracy=accuracy,audio_sentence_clips=len(audio["label"]),audio_gate=accuracy>=.9,
        relation={name:dict(accuracy=float(np.average((v>=.5)==y,weights=w)),brier=float(np.average((v-y)**2,weights=w)))
                  for name,v in predictions.items()},actors=actors.tolist(),actor_differences=differences.tolist(),
        AVT_R1V_minus_AT_unique=dict(accuracy=float(differences[:,0].mean()),brier=float(differences[:,1].mean()),
                                    actor_bootstrap_95=np.quantile(boot,[.025,.975],axis=0).T.tolist()),
        candidate_freeze_sha256=encoder.sha(out/"CANDIDATE_FREEZE.json"),
        feature_identity_sha256=encoder.sha(features/"IDENTITY.json"),
        original_video_attribution_primary_replaced=False, genuinely_independent_confirmation=False,
        gpu=None,energy_joules=None,production_activation=False,all_blockers_closed=False)
    np.savez_compressed(out/"VALIDATION_OUTPUTS.npz",audio=probabilities,clip=audio["clip"],audio_actor=audio["actor"],
        audio_label=audio["label"],probabilities=p,AT_unique=predictions["AT_unique"],AVT_R1V=predictions["AVT_R1V"],
        actor=episodes["actor"],y=y,sample_weight=w)
    encoder.write(out/"RESULT.json",result);print(json.dumps(result))


if __name__ == "__main__":
    torch.set_num_threads(1)
    parser=argparse.ArgumentParser();parser.add_argument("phase",choices=("freeze","train","evaluate"))
    parser.add_argument("--features",type=Path);parser.add_argument("--out",type=Path)
    args=parser.parse_args()
    if args.phase=="freeze":print(json.dumps(freeze_source(),indent=2))
    elif args.phase=="train":train(args.features,args.out)
    else:evaluate(args.features,args.out)
