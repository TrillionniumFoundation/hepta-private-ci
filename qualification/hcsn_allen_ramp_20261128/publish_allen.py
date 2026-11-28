"""Relay complete original bytes into the private Allen event-time research branch."""
import os,sys,time,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/"hcsn_signed_encoder_20261128"))
import publish_chunks
publish_chunks.BRANCH="research/hcsn-allen-ramp-event-time-9de7"
publish_chunks.PREFIX="qualification/hcsn_allen_ramp_20261128/"
SSH=["ssh","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-o","ConnectTimeout=12"]
REMOTE="/home/qq/.local/share/hepta-research/hcsn-allen-ramp-9de7/deliver"
while subprocess.run(SSH+["ai395","test","-s",REMOTE+"/original_manifest.json"],capture_output=True,timeout=25).returncode:time.sleep(6)
dest=ROOT/"full";dest.mkdir(exist_ok=True)
subprocess.run(["rsync","-a","-e"," ".join(SSH),"ai395:"+REMOTE+"/",str(dest)+"/"],check=True,timeout=600)
os.environ["GODEBUG"]="http2client=0"
print(publish_chunks.release(dest,ROOT/"ledger","evidence"),flush=True)
