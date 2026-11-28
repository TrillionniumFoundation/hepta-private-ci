"""Add an exact, audited table cache for native ROCm where SciPy is absent."""
import ast
import base64
from dataclasses import replace
from hashlib import sha256
import io
from pathlib import Path
import sys
import types
import numpy as np
from scipy.special import expit

root,cloud,output=map(Path,sys.argv[1:])
model=root/'hcsn_recurrent_boundary_20261128/direct_hidden/model.py'
sys.path.insert(0,str(root/'hcsn_sustained_20261128/resolvent'))
from closed_form import Contract,Prices
source=ast.parse(model.read_text())
functions=[a for a in source.body if isinstance(a,ast.FunctionDef) and a.name in ('channels','make_table')]
ns=dict(np=np,NODES=2049,expit=expit,Prices=Prices,Contract=Contract,replace=replace,
        torch=types.SimpleNamespace(from_numpy=lambda array:array))
exec(compile(ast.fix_missing_locations(ast.Module(body=functions,type_ignores=[])),str(model),'exec'),ns)
tables={}
for k in ('financial','smooth'):
    table,gain,error=ns['make_table'](k)
    tables[k]=table;tables[k+'_error']=np.array(error)
tables['gain']=np.array(gain)
buf=io.BytesIO();np.savez_compressed(buf,**tables)
b=buf.getvalue()
src=cloud.read_text()
before='    from data import streams,SHA'
inject="""    import types, io, base64
    raw_tables=base64.b64decode(%r)
    assert hashlib.sha256(raw_tables).hexdigest()==%r
    arrays=np.load(io.BytesIO(raw_tables))
    def make_table(kind):
        return torch.from_numpy(arrays[kind]), float(arrays['gain']), arrays[kind+'_error'].tolist()
    cached=types.ModuleType('model'); cached.make_table=make_table
    sys.modules['model']=cached
    report['precomputed_contract_tables']={'sha256':%r,'nodes':2049,'source_model_sha256':%r}
    report['device']['rocm']=torch.version.hip
"""%(base64.b64encode(b).decode(),sha256(b).hexdigest(),sha256(b).hexdigest(),sha256(model.read_bytes()).hexdigest())
assert src.count(before)==1
src=src.replace(before,inject+before)
src=src.replace('torch.cuda.is_available() and torch.version.cuda','torch.cuda.is_available() and (torch.version.cuda or torch.version.hip)')
src=src.replace('cuda_full_epoch_and_sixty_seconds','native_gpu_full_epoch_and_sixty_seconds')
output.write_text(src)
print(len(src.encode()),sha256(src.encode()).hexdigest())
for kind in ('financial','smooth'):
    live=Path('/tmp/hcsn9de-trimodal')/(kind+'-137-epoch1.npz')
    if live.exists():
        with np.load(live) as a:
            for key in ('cells.0.table','cells.1.table'):assert np.array_equal(a[key],tables[kind])
        print(kind,'exact match to both canonical training checkpoint buffers')
