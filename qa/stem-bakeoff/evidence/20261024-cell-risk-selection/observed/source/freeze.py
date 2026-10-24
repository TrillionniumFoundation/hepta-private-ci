import json,hashlib,datetime
from pathlib import Path
P=Path(__file__).resolve().parent;S=P.parent/'cell-head-calibration-sharing-research';B=P.parent/'cell-head-budget-research'
H=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
protocol={'scope':'historical exposed pool algorithm/sample-size diagnostic, no fresh safety qualification','proposal_sha256':H(P/'PROPOSAL.md'),'heads_sha256':H(S/'heads.npz'),'split_sha256':H(S/'split-freeze.json'),'train_labels_sha256':H(B/'train-labels-local-only.json'),'train_tensor_sha256':'1faf5c88e4cbf227e7a921f0daa3f4692804a50d0705cc516529b2e2a94767fc','seeds':list(range(2026102500,2026102520)),'thresholds':[.50,.55,.60,.65,.70,.75,.80,.85,.90,.95],'alpha':.05,'delta':.05,'candidates':200,'bootstrap_seed':2026102600,'bootstrap_replicates':10000,'selection':'maximum cal accepted among CP-upper-passing; tie smallest threshold; else reject_all','comparator':.70,'no_temperature':True,'old1600_test_access':False}
with (P/'protocol.json').open('x') as f:json.dump(protocol,f,indent=2)
with (P/'freeze.json').open('x') as f:json.dump({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'protocol_sha256':H(P/'protocol.json'),'raw_cal_threshold_counts_read':False,'new_evaluation_computed':False,'historical_evaluation_previously_exposed':True},f,indent=2)
print(H(P/'protocol.json'))
