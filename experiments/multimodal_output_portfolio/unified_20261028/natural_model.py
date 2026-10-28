"""Neural four-emission natural infilling and exact delivered-media scoring.

This is a bounded reconstruction research port, not a pretrained all-modality
foundation model and not a claim that a small observer measures open semantics.
"""
import hashlib, io, json, math, pathlib, resource, subprocess, time, wave
import numpy as np
from PIL import Image
import torch
from torch import nn
from torch.nn import functional as F

def digest(x):
 if not isinstance(x,bytes):x=json.dumps(x,sort_keys=True,separators=(",",":")).encode()
 return hashlib.sha256(x).hexdigest()

SCORE_SPEC = {
 "schema":"hepta.natural.joint-score.v1",
 "text":"multiset token F1 over emitted UTF8 and official action/sound caption",
 "image":"exp(-10*mean squared RGB error after PNG reopen)",
 "video":"exp(-10*mean squared RGB error after FFV1 Matroska reopen)",
 "audio":"exp(-min(10, .5*waveform_MSE/(target_power+1e-5)+.5*mean_abs(log1p(20*STFTabs(output))-log1p(20*STFTabs(target))))) after int16 WAV reopen",
 "joint":"clip(.5*min(four qualities)+.5*geometric_mean(four qualities)-.1*mean_abs(image-video[2]),0,1)",
 "cost":"0.001 utility/CPU-second for all self+child inference, actor, serialization/readback and scoring; no training cost silently included as inference cost",
 "failure_utility":0.,"gamma":2.,"risk_scope":"population",
 "semantic_gate":"requires independent-source observer adequacy and generated action/sound agreement; reconstruction score alone never certifies natural semantic generation",
 "fixed_horizon":"select one full-bundle branch; neural branches encode once, two shared transitions, four adapters and emissions; interpolation/retrieval baselines are deterministic; serialize, score and stop",
}
OBJECTIVE_SHA256=digest(SCORE_SPEC)
CONTINUATION_SHA256=digest({"policy":"natural-four-emission-single-bundle-v1",
 "steps":2,"branches":{"ndu_neural":"Gaussian image/video/audio and categorical text, same as training", "uniform_neural":"same stochastic law, expected-return training comparator", "fixed_neural":"deterministic mean/argmax", "interpolation":"deterministic public context only", "source_nearest":"deterministic nearest training source", "actor":"choose one declared branch from public context before output"},
 "stop":"terminal after exactly one complete bundle; failures terminate at declared zero utility"})
OBSERVER_SHA256=digest(pathlib.Path(__file__).read_bytes())
def cpu_seconds():
 a,b=resource.getrusage(resource.RUSAGE_SELF),resource.getrusage(resource.RUSAGE_CHILDREN)
 return a.ru_utime+a.ru_stime+b.ru_utime+b.ru_stime
def parameter_hash(module):
 h=hashlib.sha256()
 for name,t in sorted(module.state_dict().items()):h.update(name.encode());h.update(t.detach().cpu().numpy().tobytes())
 return h.hexdigest()

class NaturalPortfolio(nn.Module):
 """Extends the repository's NeuralPortfolio shared-state/coupling convention."""
 def __init__(self,vocabulary):
  super().__init__();self.vocabulary=vocabulary;self.hidden=64
  self.encoder_video=nn.Sequential(nn.Conv2d(12,16,3,2,1),nn.SiLU(),nn.Conv2d(16,24,3,2,1),nn.SiLU(),nn.Flatten(),nn.Linear(24*8*8,64),nn.Tanh())
  self.encoder_audio=nn.Sequential(nn.Conv1d(2,8,17,8,8),nn.SiLU(),nn.Conv1d(8,16,9,8,4),nn.SiLU(),nn.AdaptiveAvgPool1d(8),nn.Flatten(),nn.Linear(128,64),nn.Tanh())
  self.encoder_fusion=nn.Sequential(nn.Linear(128,64),nn.Tanh())
  self.initial_states=nn.Linear(64,4*64)
  self.shared_transition=nn.Sequential(nn.Linear(6*64,5*64),nn.Tanh())
  self.adapters=nn.ModuleDict({m:nn.Sequential(nn.Linear(128,64),nn.Tanh()) for m in ("text","audio","image","video")})
  self.emissions=nn.ModuleDict({"image":nn.Linear(64,3*32*32),"video":nn.Linear(64,4*3*32*32),
    "audio":nn.Linear(64,4000),"text":nn.Linear(64,16*len(vocabulary))})
  for m in ("image","video","audio"):
   nn.init.normal_(self.emissions[m].weight,std=.002);nn.init.zeros_(self.emissions[m].bias)
 def forward(self,video,audio):
  context=self.encoder_fusion(torch.cat([self.encoder_video(video.flatten(1,2)),self.encoder_audio(audio.reshape(-1,2,2000))],1))
  h=context;states=list(self.initial_states(context).tanh().chunk(4,1))
  for _ in range(2):
   delta=self.shared_transition(torch.cat([h,*states,context],1)).chunk(5,1)
   h=h+.2*delta[0];states=[x+.2*d for x,d in zip(states,delta[1:])]
  latent={m:self.adapters[m](torch.cat([h,s],1)) for m,s in zip(("text","audio","image","video"),states)}
  weight=torch.linspace(.2,.8,4,device=video.device)[None,:,None,None,None]
  base=video[:,1,None]*(1-weight)+video[:,2,None]*weight
  image_base=base[:,2].clamp(.005,.995)
  return {"image":torch.sigmoid(torch.logit(image_base)+self.emissions["image"](latent["image"]).reshape(-1,3,32,32)),
   "video":torch.sigmoid(torch.logit(base.clamp(.005,.995))+self.emissions["video"](latent["video"]).reshape(-1,4,3,32,32)),
   "audio":(audio+.1*self.emissions["audio"](latent["audio"]).tanh()).clamp(-1,1),
   "text":self.emissions["text"](latent["text"]).reshape(-1,16,len(self.vocabulary)),
   "context":context}
 def component_hashes(self):
  return {n:parameter_hash(m) for n,m in self.named_children()}

def supervised_loss(output,target):
 image=(output["image"]-target["image"]).square().flatten(1).mean(1)
 video=(output["video"]-target["video"]).square().flatten(1).mean(1)
 audio=(output["audio"]-target["audio"]).square().mean(1)/(target["audio"].square().mean(1)+1e-4)
 spectrum=(torch.log1p(20*torch.stft(output["audio"],128,64,window=torch.hann_window(128),return_complex=True).abs())-
           torch.log1p(20*torch.stft(target["audio"],128,64,window=torch.hann_window(128),return_complex=True).abs())).abs().flatten(1).mean(1)
 text=F.cross_entropy(output["text"].transpose(1,2),target["text"],reduction="none").mean(1)
 consistency=(output["image"]-output["video"][:,2]).square().flatten(1).mean(1)
 return 10*(image+video)+.1*audio+.1*spectrum+text+.5*consistency

def draw(output,rng,deterministic=False):
 values={};logp=torch.zeros(len(output["audio"]))
 for name,sigma in (("image",.015),("video",.015),("audio",.0015)):
  mean=output[name]
  sample=mean.detach() if deterministic else mean.detach()+sigma*torch.randn(mean.shape,generator=rng)
  values[name]=sample
  if not deterministic:logp+=(-.5*((sample-mean)/sigma).square()).flatten(1).sum(1)
 if deterministic:tokens=output["text"].argmax(-1)
 else:tokens=torch.multinomial(output["text"].detach().softmax(-1).reshape(-1,output["text"].shape[-1]),1,generator=rng).reshape(-1,16)
 values["text"]=tokens
 logp+=output["text"].log_softmax(-1).gather(-1,tokens[...,None]).squeeze(-1).sum(1)
 return values,logp

def text_render(tokens,vocab):
 words=[vocab[int(x)] for x in tokens if int(x)>1]
 return " ".join(words).replace(" ; ","; ").strip()

def process_ffmpeg(args,data):
 p=subprocess.run(["ffmpeg","-v","error","-threads","1",*args],input=data,capture_output=True)
 if p.returncode:raise RuntimeError(p.stderr.decode(errors="replace")[:500])
 return p.stdout

def pack_bundle(values,index,vocab,output_dir=None):
 """Actual four formats; scores exclusively use reopened bytes."""
 encoded={};decoded={}
 for name in ("image",):
  pixels=np.uint8(np.clip(values[name][index].detach().numpy().transpose(1,2,0),0,1)*255+.5)
  stream=io.BytesIO();Image.fromarray(pixels).save(stream,format="PNG");encoded[name]=stream.getvalue()
  decoded[name]=np.asarray(Image.open(io.BytesIO(encoded[name])).convert("RGB"),np.float32)/255
 pcm=np.int16(np.clip(values["audio"][index].detach().numpy(),-1,1)*32767)
 stream=io.BytesIO()
 with wave.open(stream,"wb") as out:out.setnchannels(1);out.setsampwidth(2);out.setframerate(8000);out.writeframes(pcm.astype("<i2").tobytes())
 encoded["audio"]=stream.getvalue()
 with wave.open(io.BytesIO(encoded["audio"]),"rb") as src:
  if src.getframerate()!=8000 or src.getnframes()!=4000:raise ValueError("Audio length/rate changed")
  decoded["audio"]=np.frombuffer(src.readframes(4000),"<i2").astype(np.float32)/32767
 video=np.uint8(np.clip(values["video"][index].detach().numpy().transpose(0,2,3,1),0,1)*255+.5)
 encoded["video"]=process_ffmpeg(["-f","rawvideo","-pix_fmt","rgb24","-s","32x32","-r","8","-i","pipe:0","-an","-c:v","ffv1","-level","3","-pix_fmt","bgr0","-f","matroska","pipe:1"],video.tobytes())
 raw=process_ffmpeg(["-i","pipe:0","-f","rawvideo","-pix_fmt","rgb24","pipe:1"],encoded["video"])
 decoded["video"]=np.frombuffer(raw,np.uint8).reshape(4,32,32,3).astype(np.float32)/255
 if not np.array_equal(np.uint8(decoded["video"]*255+.5),video):raise ValueError("FFV1 did not preserve emitted frame bytes")
 encoded["text"]=text_render(values["text"][index],vocab).encode("utf8");decoded["text"]=encoded["text"].decode("utf8")
 hashes={k:digest(v) for k,v in encoded.items()}
 if output_dir:
  output_dir=pathlib.Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
  suffix={"text":".txt","audio":".wav","image":".png","video":".mkv"}
  for k,b in encoded.items():(output_dir/(k+suffix[k])).write_bytes(b)
 return decoded,hashes,{k:len(v) for k,v in encoded.items()}

def token_f1(pred,target):
 from collections import Counter
 a,b=Counter(pred.replace(";"," ; ").split()),Counter(target.replace(";"," ; ").split())
 overlap=sum((a&b).values())
 return 2*overlap/max(1,sum(a.values())+sum(b.values()))

def score_bundle(delivered,target,text):
 image=float(np.mean((delivered["image"]-target["image"])**2))
 video=float(np.mean((delivered["video"]-target["video"])**2))
 audio=delivered["audio"];ref=target["audio"]
 waverr=float(np.mean((audio-ref)**2)/(np.mean(ref**2)+1e-5))
 from scipy.signal import stft
 a=np.abs(stft(audio,fs=8000,nperseg=128,noverlap=64,boundary="zeros")[2])*64
 b=np.abs(stft(ref,fs=8000,nperseg=128,noverlap=64,boundary="zeros")[2])*64
 spectral=float(np.mean(np.abs(np.log1p(20*a)-np.log1p(20*b))))
 qualities={"text":token_f1(delivered["text"],text),"image":math.exp(-10*image),
   "video":math.exp(-10*video),"audio":math.exp(-min(10,.5*waverr+.5*spectral))}
 q=np.array(list(qualities.values()))
 consistency=float(np.mean(np.abs(delivered["image"]-delivered["video"][2])))
 joint=float(np.clip(.5*q.min()+.5*np.prod(q)**.25-.1*consistency,0,1))
 return {"utility":joint,"qualities":qualities,"image_mse":image,"video_mse":video,
    "normalized_audio_mse":waverr,"audio_spectral_distance":spectral,"image_video_disagreement":consistency}

def simple_features(video,audio):
 """Public-context features for a cheap actor and source-trained observers."""
 # video B,F,H,W,C; audio B,T. No references or annotations.
 video=np.asarray(video);audio=np.asarray(audio)
 channels=video.mean(axis=(1,2,3))
 motion=np.mean(np.abs(np.diff(video,axis=1)),axis=(1,2,3,4))[:,None]
 spatial=video.std(axis=(1,2,3))
 rms=np.sqrt((audio**2).mean(1)+1e-12)[:,None]
 spec=np.abs(np.fft.rfft(audio,axis=1))
 bands=np.stack([np.log1p(spec[:,a:b].mean(1)) for a,b in ((0,64),(64,256),(256,800),(800,spec.shape[1]))],1)
 return np.concatenate([channels,spatial,motion,rms,bands,np.ones((len(audio),1))],1)
