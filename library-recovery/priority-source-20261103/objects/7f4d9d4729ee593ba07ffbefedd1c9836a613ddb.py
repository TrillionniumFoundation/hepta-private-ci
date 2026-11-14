import json
from pathlib import Path
import sys
from .admission import evaluate_ledger, pending_ledger, EvidenceError
if __name__=='__main__':
    try:
        if len(sys.argv)==1:
            data=pending_ledger()
        elif len(sys.argv)==2:
            data=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
        else:
            raise EvidenceError('usage: python -m p0_p5_gatebook [ledger.json]')
        print(json.dumps(evaluate_ledger(data),indent=2,ensure_ascii=False))
    except (EvidenceError,OSError,ValueError) as e:
        print(json.dumps({'decision':'DENY_INVALID_EVIDENCE','error':str(e),
                          'production_activation_allowed':False}))
        raise SystemExit(2) from e
