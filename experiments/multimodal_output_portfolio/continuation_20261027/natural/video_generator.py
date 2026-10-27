"""Natural-frame interpolation with a small fitted pixel generator."""
import hashlib
import time

import cv2
import numpy as np
from PIL import Image

from .common import save, sha


def endpoints(left_path, right_path):
    with Image.open(left_path) as image:
        left = np.asarray(image.convert("RGB"), dtype=np.float32)/255
    with Image.open(right_path) as image:
        right = np.asarray(image.convert("RGB"), dtype=np.float32)/255
    if left.shape != right.shape:
        raise ValueError("Endpoint shapes differ")
    return left, right


def cheap_features(left, right):
    difference = np.mean(np.abs(left-right), axis=2)
    gray_left = cv2.cvtColor(left, cv2.COLOR_RGB2GRAY)
    gray_right = cv2.cvtColor(right, cv2.COLOR_RGB2GRAY)
    shift, response = cv2.phaseCorrelate(gray_left, gray_right)
    return [float(difference.mean()), float(difference.std()),
        float(np.hypot(*shift)/max(left.shape[:2])), float(response)]


def motion(left, right):
    gray_left = cv2.cvtColor((left*255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    gray_right = cv2.cvtColor((right*255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    forward = cv2.calcOpticalFlowFarneback(gray_left, gray_right, None, .5, 3, 15, 3, 5, 1.2, 0)
    backward = cv2.calcOpticalFlowFarneback(gray_right, gray_left, None, .5, 3, 15, 3, 5, 1.2, 0)
    y, x = np.indices(left.shape[:2], dtype=np.float32)
    first = cv2.remap(left, x-.5*forward[:,:,0], y-.5*forward[:,:,1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    second = cv2.remap(right, x-.5*backward[:,:,0], y-.5*backward[:,:,1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    blended = (left+right)/2
    warped = (first+second)/2
    features = np.stack((np.ones(left.shape[:2], dtype=np.float32), np.mean(np.abs(left-right),axis=2),
        np.mean(np.abs(warped-blended),axis=2), np.minimum(1,(np.linalg.norm(forward,axis=2)+np.linalg.norm(backward,axis=2))/40)),axis=2)
    return blended, warped, features


def fit_mixer(training, spec):
    rng = np.random.default_rng(spec["seed"])
    features, blends, movements, targets = [], [], [], []
    for row in training:
        left,right=endpoints(row["left"],row["right"])
        blend,warped,x=motion(left,right)
        with Image.open(row["private_target"]) as image:
            target=np.asarray(image.convert("RGB"),dtype=np.float64)/255
        indices=rng.choice(left.shape[0]*left.shape[1],size=spec["sample_pixels_per_frame"],replace=False)
        features.append(x.reshape(-1,4)[indices])
        blends.append(blend.reshape(-1,3)[indices])
        movements.append((warped-blend).reshape(-1,3)[indices])
        targets.append(target.reshape(-1,3)[indices])
    x=np.concatenate(features).astype(np.float64)
    b,d,t=map(lambda a:np.concatenate(a).astype(np.float64),(blends,movements,targets))
    weights=np.zeros(4)
    first,second=np.zeros(4),np.zeros(4)
    losses=[]
    initial=hashlib.sha256(weights.tobytes()).hexdigest()
    for step in range(1,spec["steps"]+1):
        alpha=1/(1+np.exp(-np.clip(x@weights,-30,30)))
        error=b+alpha[:,None]*d-t
        loss=float(np.mean(error**2))
        derivative=2*np.mean(error*d,axis=1)*alpha*(1-alpha)
        gradient=x.T@derivative/len(x)
        first=.9*first+.1*gradient
        second=.999*second+.001*gradient**2
        weights-=spec["learning_rate"]*(first/(1-.9**step))/(np.sqrt(second/(1-.999**step))+1e-8)
        if step==1 or step%100==0:
            losses.append({"step":step,"pixel_MSE":loss})
    return weights,{"trainable_parameters":4,"optimizer_steps":spec["steps"],"sampled_training_pixels":len(x),
        "source_videos":len({r['source'] for r in training}),"initial_parameter_sha256":initial,
        "final_parameter_sha256":hashlib.sha256(weights.tobytes()).hexdigest(),"weights":weights.tolist(),"losses":losses}


def render(left_path,right_path,weights,use_motion,output,cached_endpoints=None):
    output.mkdir(parents=True,exist_ok=False)
    wall,cpu=time.perf_counter(),time.process_time()
    left,right=endpoints(left_path,right_path) if cached_endpoints is None else cached_endpoints
    if use_motion:
        blended,warped,x=motion(left,right)
        if weights is None:
            result=warped
        else:
            alpha=1/(1+np.exp(-np.clip(x@weights,-30,30)))
            result=blended+alpha[:,:,None]*(warped-blended)
    else:
        result=(left+right)/2
    pixels=np.rint(np.clip(result,0,1)*255).astype(np.uint8)
    path=output/"DELIVERED.png"
    Image.fromarray(pixels).save(path)
    with Image.open(path) as reopened:
        observed=np.asarray(reopened)
        if not np.array_equal(observed,pixels):
            raise ValueError("Generated video-frame delivery changed pixels")
    public={"output_path":str(path),"output_sha256":sha(path),"shape":list(pixels.shape),
        "reused_public_endpoint_arrays":cached_endpoints is not None,
        "expensive_calls":int(use_motion),"private_target_received":False,"delivered_ns":time.time_ns()}
    save(output/"PUBLIC_RESULT.json",public)
    return {**public,"cpu_seconds":time.process_time()-cpu,"wall_seconds":time.perf_counter()-wall}


def score(target_path,output_path):
    with Image.open(target_path) as image:
        target=np.asarray(image.convert("RGB"),dtype=np.float64)/255
    with Image.open(output_path) as image:
        predicted=np.asarray(image.convert("RGB"),dtype=np.float64)/255
    mse=float(np.mean((target-predicted)**2))
    return {"pixel_MSE":mse,"PSNR":float(-10*np.log10(max(mse,1e-12)))}
