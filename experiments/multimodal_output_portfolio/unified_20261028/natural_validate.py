"""Independent custody, source separation, and delivered-score validation."""
import argparse, hashlib, io, json, pathlib, wave
import numpy as np
import torch
from PIL import Image
from .profile import NduProfile
from .natural_model import NaturalPortfolio, parameter_hash, process_ffmpeg, score_bundle

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def validate_study(assets,results):
 metadata=json.loads((assets/"EVENTS.json").read_text());rows=metadata["events"]
 arrays=dict(np.load(assets/"EVENTS.npz"))
 if sha(assets/"EVENTS.npz")!=metadata["arrays_sha256"]:raise AssertionError("Event-array identity changed")
 split_sources={}
 for e in rows:split_sources.setdefault(e["split"],set()).add(e["source_id"])
 for a,aa in split_sources.items():
  for b,bb in split_sources.items():
   if a!=b and aa&bb:raise AssertionError("Original video crosses a statistical split")
 profile=NduProfile.from_dict(json.loads((results/"NDU_PROFILE.json").read_text()))
 report=json.loads((results/"RESULTS.json").read_text());ledger=json.loads((results/"OUTCOME_LEDGER.json").read_text())
 protocol=json.loads((results/"RUN_PROTOCOL.json").read_text())
 for name,expected in protocol["source_files"].items():
  if sha(results/"executed_sources"/name)!=expected:raise AssertionError("Executed source snapshot changed")
 if report["profile_sha256"]!=profile.digest:raise AssertionError("Outcome profile identity changed")
 index={e["event_id"]:i for i,e in enumerate(rows)};count=0;rescored=set()
 extensions={"text":".txt","audio":".wav","image":".png","video":".mkv"}
 for record in ledger:
  if record["profile_sha256"]!=profile.digest:raise AssertionError("Mixed outcome profiles")
  if abs(record["net_return"]-(record["utility"]-record["cost"]))>1e-12:raise AssertionError("Execution cost was omitted or charged twice")
  if record["split"]!="qualification":continue
  directory=results/"outputs"/record["arm"]/(record["event_id"]+"-"+str(record["draw"]))
  if record["terminal_kind"]=="failed":continue
  if set(record["artifacts"])!=set(extensions):raise AssertionError("Incomplete delivered bundle")
  for modality,expected in record["artifacts"].items():
   if sha(directory/(modality+extensions[modality]))!=expected:raise AssertionError("Stored artifact byte identity changed")
   count+=1
  if record["arm"] in rescored:continue
  d={"text":(directory/"text.txt").read_text(),
     "image":np.asarray(Image.open(directory/"image.png").convert("RGB"),np.float32)/255}
  with wave.open(str(directory/"audio.wav"),"rb") as src:
   if src.getnframes()!=4000 or src.getframerate()!=8000:raise AssertionError("WAV duration/rate changed")
   d["audio"]=np.frombuffer(src.readframes(4000),"<i2").astype(np.float32)/32767
  raw=process_ffmpeg(["-i","pipe:0","-f","rawvideo","-pix_fmt","rgb24","pipe:1"],(directory/"video.mkv").read_bytes())
  d["video"]=np.frombuffer(raw,np.uint8).reshape(4,32,32,3).astype(np.float32)/255
  i=index[record["event_id"]]
  target={"image":arrays["target_image"][i].astype(np.float32)/255,
   "video":arrays["target_video"][i].astype(np.float32)/255,"audio":arrays["target_audio"][i]}
  actual=score_bundle(d,target,rows[i]["caption"])
  if abs(actual["utility"]-record["utility"])>1e-12:raise AssertionError("Stored-media score differs from recorded score")
  rescored.add(record["arm"])
 checkpoints={}
 for name,entry in report["checkpoints"].items():
  path=pathlib.Path(entry.get("path",results/(name+".pt")))
  if not path.exists():
   local=results/path.name
   path=local if local.exists() else results.parent/"natural_results"/path.name
  if sha(path)!=entry["sha256"]:raise AssertionError("Checkpoint file identity changed")
  record=torch.load(path,map_location="cpu",weights_only=False)
  model=NaturalPortfolio(record["vocabulary"]);model.load_state_dict(record["model"])
  if parameter_hash(model)!=entry["model_sha256"]:raise AssertionError("Reloaded model parameter identity changed")
  checkpoints[name]=entry["sha256"]
 return {"profile_sha256":profile.digest,"event_array_sha256":metadata["arrays_sha256"],
  "split_source_counts":{s:len(v) for s,v in split_sources.items()},
  "qualification_saved_artifacts_verified":count,"stored_media_rescored_arms":sorted(rescored),
  "checkpoint_file_and_parameter_identities_verified":checkpoints,"executed_source_snapshots_match_frozen_hashes":True,"costs_charged_exactly_once":True,"passed":True}

def validate_all(root):
 original_assets=root/"natural_assets";expanded_assets=root/"natural_expanded_assets"
 a=validate_study(original_assets,root/"natural_results")
 b=validate_study(expanded_assets,root/"natural_expanded_results")
 old=json.loads((original_assets/"EVENTS.json").read_text())["events"]
 new=json.loads((expanded_assets/"EVENTS.json").read_text())["events"]
 original_sources={e["source_id"] for e in old}
 fresh_sources={e["source_id"] for e in new if e["split"] in ("calibration","qualification")}
 if original_sources&fresh_sources:raise AssertionError("Expansion held-out video was used in the original study")
 old_data=dict(np.load(original_assets/"EVENTS.npz"));new_data=dict(np.load(expanded_assets/"EVENTS.npz"))
 oi=[i for i,e in enumerate(old) if e["split"] in ("train","development")]
 ni=[i for i,e in enumerate(new) if e["split"] in ("train","development")]
 if [old[i]["event_id"] for i in oi]!=[new[i]["event_id"] for i in ni]:raise AssertionError("Inherited event selection changed")
 for k in old_data:
  if not np.array_equal(old_data[k][oi],new_data[k][ni]):raise AssertionError("Inherited training/development tensor changed")
 source_receipts={}
 for assets in (original_assets,expanded_assets):
  for row in json.loads((assets/"EVENTS.json").read_text())["sources"]:
   source_receipts[row["source_id"]]=row["sha256"]
 if len(set(source_receipts.values()))!=len(source_receipts):raise AssertionError("Exact source bytes occur under multiple video IDs")
 # A server may ignore a Range header. Reject it before any huge body read.
 from unittest.mock import patch
 from .natural_data import RemoteZip
 class Response:
  status=200;headers={"content-length":"28404087974"};read_called=False
  def __enter__(self):return self
  def __exit__(self,*args):return False
  def read(self,*args):self.read_called=True;raise AssertionError("Read an unbounded body")
 remote=RemoteZip.__new__(RemoteZip);remote.url="https://example.invalid/archive";remote.p=0;remote.length=28404087974;remote.etag="etag";remote.receipts=[]
 response=Response()
 with patch("urllib.request.urlopen",return_value=response):
  try:remote.read(128)
  except IOError:pass
  else:raise AssertionError("Ignored range not rejected")
 if response.read_called:raise AssertionError("Ignored range body was read")
 result={"original":a,"expanded":b,"unique_original_source_byte_hashes":len(source_receipts),"ignored_range_rejected_before_body_read":True,"all_original_sources_excluded_from_fresh_holdouts":True,
  "fresh_holdout_sources":len(fresh_sources),"inherited_train_development_bitwise_identical":True,"passed":True}
 (root/"NATURAL_VALIDATION.json").write_text(json.dumps(result,indent=2)+"\n")
 print(json.dumps(result,indent=2));return result

if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--root",type=pathlib.Path,required=True);a=p.parse_args();validate_all(a.root)
