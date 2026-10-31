"""Independent read-only V4 audit CLI; implementation lives in small modules.

No model, observer, corpus or training runner is imported. Full audit-source
identity accompanies every result. Earlier monolithic source is preserved
byte-for-byte in TRAINING_AUDITOR_ORIGINAL_640c75e7.py.gz.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

# Support the existing direct-script and importlib-from-file invocation forms.
if not __package__ and str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

if __package__:
    from .training_audit_common import (HERE, PORTFOLIO, SCIENCE, SEEDS, need, source_identity)
else:
    from training_audit_common import (HERE, PORTFOLIO, SCIENCE, SEEDS, need, source_identity)

if __package__:
    from .training_audit_checkpoints import (Inputs, checkpoint_audit, old_input_check)
else:
    from training_audit_checkpoints import (Inputs, checkpoint_audit, old_input_check)

if __package__:
    from .training_audit_trace import (fit_initial, head_prediction)
else:
    from training_audit_trace import (fit_initial, head_prediction)

if __package__:
    from .training_audit_run import (full_audit)
else:
    from training_audit_run import (full_audit)

if __package__:
    from .training_audit_contracts import (self_test)
else:
    from training_audit_contracts import (self_test)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path)
    parser.add_argument('--v3-run',type=Path,default=Path('/tmp/hepta-field-v3-run'))
    parser.add_argument('--protocol',type=Path,default=SCIENCE/'PROTOCOL.json')
    parser.add_argument('--freeze',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--self-test',action='store_true')
    modes.add_argument('--old-input-check',action='store_true')
    args=parser.parse_args()
    need(not args.output.exists(),'Refusing to overwrite an audit result')
    started,cpu=time.perf_counter_ns(),time.process_time_ns()
    inputs=Inputs()
    result={"schema":"hepta.field-bridge.v4.independent-training-audit.1",
            "source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "authority":"DENY_ALL","requires_calibration":True,"native_owner_integration":False,
            "scientific_gate_changed":False,"generator_calls":0,"observer_calls":0,"native_tick_calls":0,
            "gradient_or_optimizer_updates":0,"source_role_tensor_loads":0,"network_calls":0}
    result.update(source_identity())
    try:
        if args.self_test:
            result.update(self_test())
        elif args.old_input_check:
            result.update(old_input_check(args.protocol,args.v3_run,inputs))
        else:
            need(args.run is not None and args.freeze is not None,'Actual audit requires run and training freeze')
            result.update(full_audit(args.run,args.v3_run,args.protocol,args.freeze,inputs))
            result.update(passed=True,synthetic_only=False)
    except Exception as error:
        result.update(passed=False,error_type=type(error).__name__,error=str(error))
    result.update(wall_ns=time.perf_counter_ns()-started,cpu_ns=time.process_time_ns()-cpu,
        input_files=inputs.identities,auditor_io_read_bytes=inputs.read_bytes,auditor_io_read_calls=inputs.read_calls,
        weights_only_checkpoint_loads=inputs.checkpoint_loads,
        cost_scope='This auditor invocation only, including verification and deserialization; prior source/schema reading was separate and untimed.')
    with args.output.open('x') as stream:
        json.dump(result,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    print(json.dumps({"passed":result['passed'],"output":str(args.output),"error":result.get('error'),
                      "wall_ns":result['wall_ns'],"weights_only_checkpoint_loads":inputs.checkpoint_loads}))
    return 0 if result['passed'] else 2


if __name__=='__main__':
    raise SystemExit(main())
