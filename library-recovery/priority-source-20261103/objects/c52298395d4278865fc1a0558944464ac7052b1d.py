from pathlib import Path
import sys,json,hashlib,types,tempfile,datetime
import torch

def sha256_file(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load_dataset(p,expected_sha256=None):
    rows=[json.loads(s) for s in Path(p).read_text().splitlines() if s]
    if expected_sha256!=sha256_file(p):raise ValueError('dataset mismatch')
    return rows,{'dataset_sha256':expected_sha256,'width':len(rows[0]['options'])}
cs=types.ModuleType('neuron_shared_encoder.contracts');cs.load_dataset=load_dataset;cs.sha256_file=sha256_file;sys.modules[cs.__name__]=cs
md=types.ModuleType('neuron_shared_encoder.models')
class OfflineEncoder:
    def __init__(self,*args,**kwargs):raise RuntimeError('synthetic smoke tried to load a real model')
md.OfflineEncoder=OfflineEncoder
def frozen_projection(feats,dim,seed):
    if feats.shape[1]==dim:return feats
    torch.manual_seed(seed)
    mat=torch.randn(feats.shape[1],dim)
    return feats@mat
md.frozen_projection=frozen_projection;sys.modules[md.__name__]=md
exp=types.ModuleType('neuron_shared_encoder.experiment')
def mock_embedding(row,dimension):
    v='|'.join([str(row.get('state','')),row.get('question',''),' '.join(row.get('options',[]))])
    arr=list(hashlib.sha256(v.encode()).digest())
    return torch.tensor([(arr[i%32]-127)/127 for i in range(dimension)],dtype=torch.float32)
exp._mock_embedding=mock_embedding;sys.modules[exp.__name__]=exp
from neuron_shared_encoder import validation_v3
with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp)/'ds.jsonl';output=Path(tmp)/'e3.json'
    with p.open('w') as file:
        for j,split in enumerate(('train','validation','future','ood')):
            for i in range(8):
                row=dict(row_id=f'{split}-{i}',source_group=f'{split}-{i}',principal='p1',organ_id='o1',cell_id='c1',state=f'state-{i}',question='Choose?',options=['A','B'],label=i%2,split=split,event_time=f'2026-01-{1+j:02d}T00:00:00+00:00')
                file.write(json.dumps(row)+'\n')
    sys.argv=['v3','e3-reuse','--allow-synthetic','--dataset',str(p),'--dataset-sha256',sha256_file(p),'--output',str(output),'--dimension','32','--batch','16','--steps','1','--budgets','2048']
    validation_v3.main()
    rec=json.loads(output.read_text())
    assert rec['production_admission']=='BLOCKED'
    assert rec['joint']['model_forward_observation'] is None
    assert rec['public']['model_forward_observation'] is None
    assert rec['joint']['model_forward_attestation_verified'] is False
    assert rec['public']['model_forward_attestation_verified'] is False
    print('E3 SYNTHETIC SMOKE PASS:',{k:{x:rec[k][x] for x in ('encoder_forward_invocations','encoder_forward_rows','model_forward_observation')} for k in ('joint','public')})
