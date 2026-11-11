"""One bounded metadata analysis worker, activated only by a later exact authorization."""
import os
import time
START = float(os.environ.get('HCSN_C2_RESOURCE_STARTED', time.monotonic()))
import argparse
from pathlib import Path
import resource
import traceback
from zipfile import ZIP_DEFLATED, ZipFile

from build_report import build, skeleton, withhold
from metadata_io import Inputs, PROGRAM, RSS, WHOLE, authorize, identity, program_manifest, save
from resource_arithmetic import require


def main(args):
    output = Path(args.output)
    output.mkdir(exist_ok=False)
    result = skeleton()
    def budget():
        require(time.monotonic()-START <= WHOLE-10, 'metadata worker grant exhausted; 10s reserved for final artifact envelope')
        require(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024 <= RSS, 'metadata worker RSS over fixed cap')
    inputs = Inputs(budget)
    try:
        result['program_manifest_before'] = program_manifest()
        _, plan, binding = authorize(args, inputs)
        result['authorization_identity'] = identity(args.authorization)
        result['binding_identity'] = identity(args.binding)
        build(binding, plan, inputs, output, result)
        budget()
    except Exception:
        withhold(result, traceback.format_exc())
    finally:
        try:
            inputs.verify()
            result['program_manifest_after'] = program_manifest()
            require(result['program_manifest_after'] == result.get('program_manifest_before'), 'analysis source changed')
            result['inputs_unchanged'] = True
        except Exception:
            result['inputs_unchanged'] = False
            withhold(result, traceback.format_exc())
        result.update(input_identities=inputs.files, metadata_worker_wall_seconds=time.monotonic()-START,
                      worker_process_CPU_sample_seconds=time.process_time(),
                      worker_self_peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                      resource_scope='Worker sample before report/archive serialization; external wait4 and whole wall supply final envelope.')
        save(output/'RESULT.json', result)
        save(output/'MANIFEST.json', {'files': {str(p.relative_to(output)): identity(p)
                                               for p in sorted(output.rglob('*')) if p.is_file()}})
        with ZipFile(str(output)+'.zip', 'x', compression=ZIP_DEFLATED) as archive:
            for path in sorted(output.rglob('*')):
                if path.is_file():
                    archive.write(path, str(path.relative_to(output)))
    return 0 if result['execution_status'] in ('completed_metadata', 'completed_metadata_with_explicit_holds') else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('authorization', 'authorization-sha', 'binding', 'binding-sha', 'output'):
        parser.add_argument('--'+key, required=True)
    raise SystemExit(main(parser.parse_args()))
