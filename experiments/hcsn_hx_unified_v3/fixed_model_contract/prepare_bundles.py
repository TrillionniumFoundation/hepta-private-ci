"""Prepare only the two pinned, pre-reviewed local proof receipts."""
import json,shutil
from pathlib import Path
from contract import registry,make_contract,emit,verify_runtime
R=Path(__file__).resolve().parent
for key,row in registry().items():
 d=R/'bundles'/row['name'];d.mkdir(parents=True,exist_ok=True)
 source=(R/row['source_directory']).resolve()
 for name in ('ROOT_PROOF.json','COEFFICIENTS.json'):shutil.copyfile(source/name,d/name)
 (d/'CONTRACT.json').write_text(json.dumps(make_contract(key),indent=2)+'\n')
 emit(d);print(json.dumps(verify_runtime(d)))
