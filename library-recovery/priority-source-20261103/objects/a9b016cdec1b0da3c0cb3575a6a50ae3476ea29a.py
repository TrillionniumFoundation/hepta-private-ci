"""python -m p1_mechanism_gate PATH_TO_REAL_PAIRED_RESULTS.json"""
import dataclasses
import json
from pathlib import Path
import sys
from .paired_gate import analyze, ContractError

if __name__=='__main__':
    if len(sys.argv)!=2:
        raise SystemExit('usage: python -m p1_mechanism_gate paired-results.json')
    try:
        data=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        result=analyze(data)
    except (OSError,ValueError,ContractError) as e:
        print(json.dumps({'status':'DENY','reason':str(e)}))
        raise SystemExit(2) from e
    print(json.dumps({
        'status':'STATISTICAL_DIAGNOSTIC_ONLY_NOT_PRODUCTION',
        'external_registration_verified':False,
        'scientific_claim':'unconfirmed: requires fresh heldout experiment and independent review',
        'contrasts':[dataclasses.asdict(x) for x in result],
    },indent=2))
