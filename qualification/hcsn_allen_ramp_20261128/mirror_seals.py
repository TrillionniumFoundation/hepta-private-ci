"""Run on the independent receipt machine and acknowledge exact seals before held scoring."""
from datetime import datetime,timezone
import hashlib,json
from pathlib import Path
import subprocess,time
SRC="/home/qq/.local/share/hepta-research/hcsn-allen-ramp-9de7"
OUT=Path.home()/".local/state/hepta-allen-ramp-relay-9de7";OUT.mkdir(exist_ok=True)
SSH=["ssh","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-o","ConnectTimeout=8"]
names=["source/cohort.json","results/seal.json","hard-lif/seal.json"]
while True:
    z=subprocess.run(SSH+["ai395","test","-s",SRC+"/results/seal.json","-a","-s",SRC+"/hard-lif/seal.json"],capture_output=True,timeout=30)
    if z.returncode==0:break
    time.sleep(4)
for name in names:
    target=OUT/name;target.parent.mkdir(exist_ok=True,parents=True)
    subprocess.run(["rsync","-a","-e"," ".join(SSH),"ai395:"+SRC+"/"+name,str(target)],check=True,timeout=90)
ack=OUT/"joint_receipt.json"
values={n:hashlib.sha256((OUT/n).read_bytes()).hexdigest() for n in names}
if ack.is_file():assert json.loads(ack.read_bytes())["sources"]==values
else:ack.write_text(json.dumps(dict(sources=values,independent_observation_utc=datetime.now(timezone.utc).isoformat()),sort_keys=True,indent=2)+"\n")
subprocess.run(["rsync","-a","-e"," ".join(SSH),str(ack),"ai395:"+SRC+"/joint_receipt.json"],check=True,timeout=120)
print(ack.read_text(),flush=True)
