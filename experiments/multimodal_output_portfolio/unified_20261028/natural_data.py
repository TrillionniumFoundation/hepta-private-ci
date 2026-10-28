"""Frozen, source-disjoint Perception Test natural event preparation.

The remote ZIP is a public archive. Range requests avoid fetching unrelated
videos; central-directory metadata and every downloaded member are hashed.
A source video is the statistical cluster. Participant identities are absent.
"""
import argparse, hashlib, io, json, os, pathlib, struct, subprocess, time, urllib.request, zipfile
import numpy as np

BASE = "https://storage.googleapis.com/dm-perception-test/zip_data/"
URL = BASE + "train_videos.zip"
ANNOTATIONS = {
 "action": ("action_localisation_train_annotations.zip", "5b27beaa97df0a1ea258437b179ed17092981a93501a22a572d64dd46fb12575"),
 "sound": ("sound_localisation_train_annotations.zip", "0200a50644ab9d36a2dd80e5239e709cabeeaf2e4274eca201c90743b89cc6f5"),
}
SEED = "hepta-natural-joint-20261028-v1"
COUNTS = {"train": 32, "development": 8, "calibration": 8, "qualification": 16}
SIDE, FPS, SR, MAX_EVENTS = 32, 8, 8000, 4

def sha(b): return hashlib.sha256(b).hexdigest()
def canonical(x): return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
def write_json(path, x):
 path = pathlib.Path(path); path.parent.mkdir(parents=True, exist_ok=True)
 path.write_bytes(json.dumps(x, indent=2, ensure_ascii=False).encode()+b"\n")

class RemoteZip(io.RawIOBase):
 def __init__(self, url):
  self.url=url; self.p=0; self.receipts=[]
  with urllib.request.urlopen(urllib.request.Request(url, method="HEAD")) as r:
   self.length=int(r.headers["content-length"])
   self.generation=r.headers.get("x-goog-generation")
   self.etag=r.headers.get("etag")
 def seekable(self): return True
 def seek(self, offset, whence=0):
  self.p=offset if whence==0 else self.p+offset if whence==1 else self.length+offset
  return self.p
 def tell(self): return self.p
 def read(self, count=-1):
  count=self.length-self.p if count<0 else min(count,self.length-self.p)
  if count<=0:return b""
  begin=self.p
  request=urllib.request.Request(self.url,headers={"Range":f"bytes={begin}-{begin+count-1}","If-Match":self.etag})
  with urllib.request.urlopen(request, timeout=90) as r:
   if r.status!=206 or int(r.headers.get("content-length",count))!=count:
    raise IOError("Server did not honor bounded public Range request")
   data=r.read(count+1)
   if len(data)!=count:
    raise IOError("Bounded public Range response length changed")
  self.p+=len(data)
  self.receipts.append({"start":begin,"bytes":len(data),"sha256":sha(data)})
  return data

def annotations(root):
 result={}; receipts={}
 for kind,(name,expected) in ANNOTATIONS.items():
  p=root/name
  if p.exists():data=p.read_bytes()
  else:
   data=urllib.request.urlopen(BASE+name,timeout=60).read();p.write_bytes(data)
  if sha(data)!=expected:raise ValueError("Official annotation byte identity changed")
  z=zipfile.ZipFile(io.BytesIO(data))
  result[kind]=json.loads(z.read(z.namelist()[0]))
  receipts[kind]={"url":BASE+name,"bytes":len(data),"sha256":expected}
 return result,receipts

def eligible_events(a,s):
 duration=a["metadata"]["num_frames"]/a["metadata"]["frame_rate"]
 events=[]
 for action in a["action_localisation"]:
  lo,hi=[v/1e6 for v in action["timestamps"]]
  for sound in s["sound_localisation"]:
   if not sound.get("is_visible") or sound["label_id"] in (12,13,16):continue
   sl,sh=[v/1e6 for v in sound["timestamps"]]
   left,right=max(lo,sl,.5),min(hi,sh,duration-.5)
   if right-left<.25:continue
   center=(left+right)/2
   events.append({"start_seconds":round(center-.5,6),
      "action_id":action["label_id"],"action":action["label"],
      "sound_id":sound["label_id"],"sound":sound["label"],
      "caption":action["label"].lower()+"; "+sound["label"].lower(),
      "overlap_seconds":round(right-left,6)})
 # Keep nonoverlapping windows only; all crops from a source remain one cluster.
 events.sort(key=lambda e:sha(canonical([SEED,e])))
 kept=[]
 for e in events:
  if all(abs(e["start_seconds"]-x["start_seconds"])>=1. for x in kept):kept.append(e)
  if len(kept)==MAX_EVENTS:break
 return kept

def freeze(root):
 root.mkdir(parents=True,exist_ok=True)
 p=root/"SOURCE_PROTOCOL.json"
 if p.exists():return json.loads(p.read_text())
 ann,receipts=annotations(root)
 remote=RemoteZip(URL); archive=zipfile.ZipFile(remote)
 candidates=[]
 for info in archive.infolist():
  if not info.filename.endswith(".mp4") or info.file_size>5_000_000:continue
  source=pathlib.PurePosixPath(info.filename).stem
  if source not in ann["action"] or source not in ann["sound"]:continue
  events=eligible_events(ann["action"][source],ann["sound"][source])
  if len(events)<2:continue
  candidates.append({"source_id":source,"member":info.filename,
    "compressed_bytes":info.compress_size,"bytes":info.file_size,
    "zip_crc32":f"{info.CRC:08x}","events":events,
    "priority":sha(canonical([SEED,source]))})
 candidates.sort(key=lambda x:x["priority"])
 chosen=candidates[:sum(COUNTS.values())]
 if len(chosen)!=sum(COUNTS.values()):raise ValueError("Insufficient eligible source videos")
 cursor=0
 for split,count in COUNTS.items():
  for row in chosen[cursor:cursor+count]:row["split"]=split
  cursor+=count
 # Vocabulary is a published annotation ontology, not fitted to held-out pixels/audio.
 vocab=sorted({t for v in ann["action"].values() for a in v["action_localisation"] for t in a["label"].lower().replace(";"," ; ").split()}
             |{t for v in ann["sound"].values() for a in v["sound_localisation"] for t in a["label"].lower().replace(";"," ; ").split()}|{";"})
 plan={"schema":"hepta.natural.sources.v1","dataset":"DeepMind Perception Test",
   "license":"CC-BY-4.0","attribution":"Patraucean et al., Perception Test: A Diagnostic Benchmark for Multimodal Video Models, NeurIPS 2023",
   "official_repository":"https://github.com/google-deepmind/perception_test",
   "official_split":"train","task":"same-event natural 0.5-second missing-segment reconstruction with action/sound label caption",
   "seed":SEED,"counts":COUNTS,"selection":"SHA256 order of seed/source among <=5MB official train MP4s with >=2 visible annotated sound/action overlap events; no quality outcomes used",
   "source_unit":"original video_id","participant_disjoint_verified":False,
   "limitations":["Participant identity is unavailable; video-source separation is not participant separation.",
     "Size-bounded source subset is not representative of all natural video.",
     "Captions are templated action/sound annotations, not open-domain fluent narration.",
     "Qualification annotations are read only to freeze event windows; qualification media and metrics are not used for fitting or selection.",
     "All sources are from the official train split; these are new project-level partitions, not official benchmark results."],
   "archive":{"url":URL,"bytes":remote.length,"generation":remote.generation,"etag":remote.etag,
              "index_range_receipts":remote.receipts},
   "annotation_archives":receipts,"vocabulary":["<pad>","<unk>"]+vocab,
   "decode":{"side":SIDE,"fps":FPS,"audio_sample_rate":SR,"duration_seconds":1.,
             "context_frames":[0,1,6,7],"target_frames":[2,3,4,5],
             "context_audio_samples":[[0,2000],[6000,8000]],"target_audio_samples":[2000,6000],
             "image_target_frame":4},
   "selected":chosen,"created_at_unix":time.time()}
 plan["protocol_sha256"]=sha(canonical(plan))
 write_json(p,plan)
 return plan

def ffmpeg(cmd):
 p=subprocess.run(["ffmpeg","-v","error","-threads","1",*cmd],capture_output=True)
 if p.returncode:raise RuntimeError(p.stderr.decode(errors="replace")[:1000])
 return p.stdout

def prepare(root):
 plan=freeze(root); checked=dict(plan); expected=checked.pop("protocol_sha256")
 decode_protocol={"source_protocol_sha256":plan["protocol_sha256"],"full_source_decode":"ffmpeg fps=8,scale=32:32 area; mono audio 8000Hz", "window_alignment":"round(start_seconds*8)/8; matching audio sample boundaries", "retain_raw_source":False,"raw_source_custody":"SHA256, official archive generation, URL, ZIP member/CRC and HTTP-range receipts permit exact recovery", "chosen_before_model_training":True}
 decode_protocol["sha256"]=sha(canonical(decode_protocol))
 write_json(root/"DECODE_PROTOCOL.json",decode_protocol)
 if sha(canonical(checked))!=expected:raise ValueError("Frozen source protocol changed")
 videos=root/"sources";videos.mkdir(exist_ok=True)
 remote=RemoteZip(URL)
 if remote.generation!=plan["archive"]["generation"]:raise ValueError("Official archive generation changed")
 archive=zipfile.ZipFile(remote); rows=[]; decoded=[]; source_receipts=[]
 for si,source in enumerate(plan["selected"]):
  path=videos/(source["source_id"]+".mp4")
  if not path.exists():
   data=archive.read(source["member"])
   if len(data)!=source["bytes"]:raise ValueError("Source byte size changed")
   path.write_bytes(data)
  source_sha=sha(path.read_bytes())
  source_receipts.append({"source_id":source["source_id"],"split":source["split"],"path":str(path),
                          "sha256":source_sha,"bytes":path.stat().st_size})
  full_frames=np.frombuffer(ffmpeg(["-i",str(path),"-vf",f"fps={FPS},scale={SIDE}:{SIDE}:flags=area","-f","rawvideo","-pix_fmt","rgb24","pipe:1"]),np.uint8).reshape(-1,SIDE,SIDE,3)
  full_audio=np.frombuffer(ffmpeg(["-i",str(path),"-vn","-ac","1","-ar",str(SR),"-f","f32le","pipe:1"]),"<f4")
  for ei,event in enumerate(source["events"]):
   first=int(round(event["start_seconds"]*FPS)); actual_start=first/FPS
   frames=full_frames[first:first+FPS]
   audio=full_audio[int(actual_start*SR):int(actual_start*SR)+SR]
   if frames.size!=8*SIDE*SIDE*3 or audio.size<SR:
    raise ValueError(f"Short synchronized event {source['source_id']} {ei}")
   frames=frames.reshape(8,SIDE,SIDE,3);audio=audio[:SR]
   # No per-event normalization: original amplitude remains a scored variable.
   tokens=event["caption"].replace(";"," ; ").split()
   text=np.zeros(16,dtype=np.int64);lookup={t:i for i,t in enumerate(plan["vocabulary"])}
   for j,t in enumerate(tokens[:16]):text[j]=lookup.get(t,1)
   decoded.append((frames[[0,1,6,7]],audio[np.r_[0:2000,6000:8000]],frames[2:6],audio[2000:6000],frames[4],text))
   rows.append({"event_id":source["source_id"]+f"-event-{ei}","source_id":source["source_id"],
                "split":source["split"],"source_sha256":source_sha,**event,"actual_start_seconds":actual_start})
  path.unlink()  # This module owns only this just-verified downloaded member.
  print(f"natural source {si+1}/{len(plan['selected'])} {source['source_id']} {source['split']}",flush=True)
 arrays={name:np.stack([r[i] for r in decoded]) for i,name in enumerate(("context_video","context_audio","target_video","target_audio","target_image","target_text"))}
 np.savez_compressed(root/"EVENTS.npz",**arrays)
 write_json(root/"EVENTS.json",{"source_protocol_sha256":plan["protocol_sha256"],"events":rows,
   "arrays_sha256":sha((root/"EVENTS.npz").read_bytes()),"sources":source_receipts,"download_range_receipts":remote.receipts,
   "counts":{split:sum(r["split"]==split for r in rows) for split in COUNTS},
   "freshness_note":"No matching Perception Test media was found in searched prior workspaces; prior holdout history outside accessible records is not provable."})
 return rows

if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--assets",type=pathlib.Path,required=True);p.add_argument("--freeze-only",action="store_true");a=p.parse_args()
 plan=freeze(a.assets)
 print(json.dumps({"protocol_sha256":plan["protocol_sha256"],"source_count":len(plan["selected"]),
  "raw_source_bytes":sum(x["bytes"] for x in plan["selected"]),"counts":plan["counts"]}))
 if not a.freeze_only:prepare(a.assets)
