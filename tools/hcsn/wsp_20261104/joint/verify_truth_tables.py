"""Independently regenerate the fixed finite-space CTMC matrices with SciPy."""
from pathlib import Path
import hashlib,json
import numpy as np
from joint_law import IndependentLaw

root=Path(__file__).resolve().parent
protocol=json.loads((root/'joint_protocol.json').read_text())
law=IndependentLaw(protocol['truth_raw'],protocol['n_grid'])
archive=np.load(root/'truth_transitions.npz');results=[]
with np.errstate(over='raise',invalid='raise',divide='raise'):
    for dt in (.25,.5,.75,1.5):
        for drive in (-1,0,1):
            key=f'dt{float(dt)}_drive{int(drive)}';p=law.transition(dt,drive)
            error=float(np.max(abs(p-archive[key])))
            assert error<=2e-12,(key,error)
            results.append({'key':key,'max_abs_difference':error,'max_row_sum_error':float(np.max(abs(p.sum(1)-1)))})
print(json.dumps({'schema':'hepta-independent-CTMC-table-verification-v1',
                  'source_asset_sha256':hashlib.sha256((root/'truth_transitions.npz').read_bytes()).hexdigest(),
                  'comparisons':results},indent=2))
