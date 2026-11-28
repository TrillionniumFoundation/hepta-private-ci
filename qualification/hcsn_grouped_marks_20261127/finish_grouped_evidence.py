"""Complete the portable cold and board-cost replay after all original writers release their locks."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument('study', type=Path)
    cli.add_argument('data_root', type=Path)
    cli.add_argument('output', type=Path)
    args = cli.parse_args()
    base, data, out = (p.resolve() for p in (args.study, args.data_root, args.output))
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HCSN_GROUPED_STUDY=str(base), HEPTA_FLICKR_ROOT=str(data),
               OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
               PYTHONPATH=str(base/'src'))
    src = Path(__file__).resolve().parent
    with contextlib.ExitStack() as hold:
        release = hold.enter_context((out/'analysis.lock').open('a'))
        fcntl.flock(release, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finish = out/'complete.json'
        if finish.exists():
            recorded = json.loads(finish.read_bytes())
            assert all(sha(out/k) == v for k,v in recorded['output_sha256'].items())
            assert sha(base/'final.json') == recorded['final_sha256']
            return
        deadline = time.monotonic() + 20*3600
        while not (base/'final.json').is_file():
            if time.monotonic() > deadline:
                raise TimeoutError('joint cold result has not yet closed')
            time.sleep(20)
        # The final result is written by an analysis child. Require its controller and both sensor writers to exit.
        for lockfile in (base/'controller.lock', base/'board_observations/record.lock',
                         base/'board_observations/native_power.lock'):
            owner = hold.enter_context(lockfile.open('a'))
            fcntl.flock(owner, fcntl.LOCK_EX)
        tuning = json.loads((base/'tuning_seal.json').read_bytes())
        sealed = json.loads((base/'evaluation_seal.json').read_bytes())
        assert len(tuning['tuning_receipts']) == 36 and len(sealed['assignments']) == 72
        assert sealed['tuning'] == sha(base/'tuning_seal.json')
        def run(program, *arguments):
            command = [sys.executable, str(src/program), *map(str,arguments)]
            print(program,*map(str,arguments),flush=True)
            subprocess.run(command,cwd=src,env=env,check=True)
        # The portable numerical checks use CPU. Only the post-freeze inference profile uses the GPU.
        run('account_grouped_costs.py', base, out/'costs.json')
        run('export_cold_evidence.py', base, out)
        run('replay_cold_evidence.py', out, out/'replay.json')
        run('portable_board.py','export', base, out)
        run('portable_board.py','verify', out, out/'costs.json', out/'board_verification.json')
        if not (base/'port_profile.json').is_file():
            run('profile_ports.py')
        profile = json.loads((base/'port_profile.json').read_bytes())
        assert profile['frozen_result'] == sha(base/'final.json')
        (out/'port_profile.json').write_bytes((base/'port_profile.json').read_bytes())
        paths = [p for p in sorted(out.iterdir()) if p.is_file() and p.name not in ('analysis.lock','complete.json')]
        record = {'output_sha256':{p.name:sha(p) for p in paths},
                  'replay_sources_sha256':{name:sha(src/name) for name in
                    ('account_grouped_costs.py','export_cold_evidence.py','replay_cold_evidence.py',
                     'portable_board.py','profile_ports.py','finish_grouped_evidence.py')},
                  'final_sha256':sha(base/'final.json'),'tuning_sha256':sha(base/'tuning_seal.json'),
                  'confirmation_sha256':sha(base/'evaluation_seal.json')}
        tmp = finish.with_suffix('.tmp')
        tmp.write_text(json.dumps(record,sort_keys=True,indent=2)+'\n')
        tmp.replace(finish)
        print('finished',sha(finish),flush=True)


if __name__ == '__main__':
    main()
