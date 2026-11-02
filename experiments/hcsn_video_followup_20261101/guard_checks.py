"""Behavioral metadata tamper checks; never open validation arrays."""
import json
from pathlib import Path
import shutil
import tempfile

from experiments.hcsn_video_followup_20261101 import study


def main():
    original = study.HERE
    run = original/'results/run002'
    checked = []
    for name in ('training','input_identity','checkpoint'):
        with tempfile.TemporaryDirectory(prefix='hcsn-video-guard-') as temporary:
            target = Path(temporary)
            out = target/'run';out.mkdir()
            for path in run.iterdir():
                if path.is_file():
                    shutil.copyfile(path,out/path.name)
            shutil.copyfile(original/'PROTOCOL.json',target/'PROTOCOL.json')
            shutil.copyfile(original/'INPUT_IDENTITY.json',target/'INPUT_IDENTITY.json')
            if name == 'training':
                path=out/'TRAINING.json';value=json.loads(path.read_text())
                value['selected']['video']['selected']['feature']='temporal'
                path.write_text(json.dumps(value))
            elif name == 'input_identity':
                path=target/'INPUT_IDENTITY.json';path.write_text(path.read_text()+' ')
            else:
                path=out/'video_encoder.npz';path.write_bytes(path.read_bytes()+b'changed')
            previous_load=study.load
            def forbidden(split):
                raise RuntimeError('Validation loader must never be called in guard check')
            study.HERE=target;study.load=forbidden
            try:
                study.evaluate(out)
            except AssertionError:
                checked.append(dict(tamper=name,rejected_before_loader=True))
            else:
                raise AssertionError('Tamper accepted')
            finally:
                study.HERE=original;study.load=previous_load
    result=dict(passed=True,checks=checked,source_sha256=study.sha(study.__file__),validation_loaded=False)
    study.write(original/'GUARD_CHECKS.json',result)
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    main()
