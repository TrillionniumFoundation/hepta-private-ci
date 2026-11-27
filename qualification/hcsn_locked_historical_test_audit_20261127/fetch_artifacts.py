"""Three once-only exact artifact downloads through the unchanged qualified API helper."""
import json
from pathlib import Path
import sys
import time
from audit_support import checked, load_module, write

HERE=Path(__file__).resolve().parent


def main():
    if len(sys.argv)!=5:
        raise SystemExit('fetch_artifacts.py BINDING TRANSFER NEW_DIRECTORY NEW_RECEIPT')
    binding_path,transfer,destination,receipt=(Path(value).resolve() for value in sys.argv[1:])
    binding=json.loads(binding_path.read_text())
    if binding['status']!='FROZEN_FOR_EXECUTION_AFTER_ROOT_REVIEW':
        raise ValueError('unreviewed audit artifact acquisition')
    checked((transfer/'fetch_predecessor.py').read_bytes(),binding['transfer_files']['fetch_predecessor.py'])
    old=load_module('exact_frozen_artifact_fetcher',transfer/'fetch_predecessor.py')
    destination.mkdir(parents=True,exist_ok=False)
    start=time.monotonic()
    rows=[]
    try:
        for key in ('sender47','transfer83_137','repair137'):
            item=binding['predecessor_artifacts'][key]
            current=destination/(key+'.binding.json')
            write(current,dict(status=binding['status'],predecessor_artifact=item))
            sys.argv=[str(transfer/'fetch_predecessor.py'),str(current),
                str(destination/(key+'.zip')),str(destination/(key+'.receipt.json'))]
            old.main()
            rows.append(json.loads((destination/(key+'.receipt.json')).read_text()))
        write(receipt,dict(status='EXACT_THREE_ARTIFACTS_DOWNLOADED',downloads=rows,retries=0,
            wall_seconds=time.monotonic()-start,model_calls=0,test_arrays_read=False))
    except BaseException as error:
        write(receipt,dict(status='FAILED_NO_RETRY',completed_downloads=rows,
            failure_type=type(error).__name__,wall_seconds=time.monotonic()-start,model_calls=0))
        raise RuntimeError('locked-audit artifact acquisition failed; redacted receipt retained') from None


if __name__=='__main__':
    main()
