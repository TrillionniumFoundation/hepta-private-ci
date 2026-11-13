#!/usr/bin/env python3
"""Prepare a read-reviewable admission module only. No H, source work, or module main."""
from pathlib import Path
import ast
import difflib
import hashlib
import json

HERE = Path('/tmp/hepta-36fa-isolated-native-admission-v1')
OLD = Path('/tmp/hepta-36fa-cc57-admission-successor-v2')


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


old = (OLD / 'qualification-admission.cc57.HOLD.py').read_bytes()
assert identity(old)['git_blob'] == 'a8be08b6cb00536817e2d68c42fa4b90d1e9ff72'
code = old.decode()
constants = '''
HISTORICAL_REPO = '/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1'
CURRENT_REPO = '/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1'
MATERIALIZATION_CONTROL = Path('/home/qian-qi/hepta-utility-36fa-evidence/cc57-isolated-materialization-v1')
MATERIALIZER_PIN = {'bytes': 57607, 'sha256': '5717afe87597089462b685014d0687f0d45a3416f5a1d65580f69f26c9650436', 'git_blob': '972ec74449b113a95b4ec098e562a565f23aa82f'}
MATERIALIZATION_PACKET_PIN = {'bytes': 13764, 'sha256': 'b2a62c45873fe6c37257df5561accd9d30dcf2d7ca969de6968fec7ac1e3acc3', 'git_blob': '06503652a2895120daf8b66e42b3a01cefeaf4fb'}
MATERIALIZER_CONFIG_PIN = {'bytes': 992, 'sha256': '414a52cdd7802f5d84de65ee70422a14eb93d799ca46912a9d618f734bffe6a0', 'git_blob': '692d2b825dcbb38eb95e91c0fb5f67afa39d0518'}
NATIVE_INVENTORY_PIN = {'bytes': 3530181, 'sha256': '20008a0cb7bbfd5ed67396a301e2bfdbbd30f336d0f962cac23e5d1601f660d9', 'git_blob': '2def77faf50ba6d74d923732182dcb3cad916e53'}
'''
replacements = [
    ("C0F = 'c0f78493f815780f68b9bf5e390a21314d79311f'\n", "C0F = 'c0f78493f815780f68b9bf5e390a21314d79311f'\n" + constants),
    ("        self.m = load(cfg['maintenance_guard_path'], V5_PIN, 'original_maintenance_v5_environment_only')\n        m = self.m\n        check(str(m.REPO) == cfg['repo'] and str(m.TARGET) == cfg['target'], 'original actual source/target paths')\n        m.OUT = self.output\n        m.cfg = cfg['runtime_guard']\n",
     """        check(cfg.get('historical_source_repo') == HISTORICAL_REPO and cfg.get('repo') == CURRENT_REPO,
              'explicit reviewed historical and isolated current source paths')
        check(cfg.get('source') == 'cc57c7198db6293ccca562253c42fffbe2a04633'
              and cfg.get('tree') == 'b7b357c07b5539769a068c6b9b009629f5612d1e'
              and cfg.get('parents') == ['246d8cb614770252ee42029a5c014f2a4904176a'],
              'unchanged canonical native qualification subject')
        self.h = load(cfg['maintenance_guard_path'], V5_PIN, 'original_v5_historical_runtime_environment')
        self.m = load(cfg['maintenance_guard_path'], V5_PIN, 'original_v5_current_source_observation')
        m = self.m
        check(str(m.REPO) == str(self.h.REPO) == HISTORICAL_REPO
              and str(m.TARGET) == str(self.h.TARGET) == cfg['target'], 'original V5 historical source/target constants')
        # Only this separate observation instance follows the new current repository.
        # The unmodified historical instance retains its original 86dd SEED and path.
        m.REPO = Path(cfg['repo']); m.HEAD = cfg['source']; m.TREE = cfg['tree']
        m.OUT = self.output
        m.cfg = cfg['runtime_guard']
        self.h.OUT = self.output / 'historical-runtime'
        self.h.cfg = cfg['runtime_guard']
"""),
    ("        os.mkdir(self.output, 0o700)\n", "        os.mkdir(self.output, 0o700)\n        os.mkdir(self.h.OUT, 0o700)\n"),
    ("        m.read_input(cfg['inventory_driver_path'], INVENTORY_PIN)\n", "        m.read_input(cfg['inventory_driver_path'], INVENTORY_PIN)\n        self.h.read_input(cfg['maintenance_guard_path'], V5_PIN)\n"),
    ("              and final_format['source_repo'] == cfg['repo']\n", "              and final_format['source_repo'] == HISTORICAL_REPO\n"),
    ("              and aligned['source_repo'] == cfg['repo']\n", "              and aligned['source_repo'] == HISTORICAL_REPO\n"),
    ("        self.initial_git = m.git_state()\n        check(self.initial_git == after['git_state'], 'actual exact canonical raw Git state')\n", "        self.materialized = self.validate_materialization(aligned)\n        self.initial_git = m.git_state()\n        check(self.initial_git == self.materialized['current_git_state_after'], 'actual new materialization raw Git state')\n"),
    ("            self.environment = m.environment_preflight()\n", """            self.environment = self.h.environment_preflight()
            # Re-check path separation for the current repository too; no creation.
            desired = cfg['runtime_guard']['environment']
            external = {'target': m.external_directory(m.TARGET, 'current source external target')}
            for name in ('UV_PROJECT_ENVIRONMENT', 'UV_CACHE_DIR', 'RUFF_CACHE_DIR'):
                external[name] = m.external_directory(desired[name], 'current source external ' + name)
            m.jwrite('CURRENT_SOURCE_EXTERNAL_DIRECTORIES.json', external)
"""),
    ("                 'qualification': False, 'at': m.now()})\n", "                 'qualification': False, 'at': m.now(),\n                 'historical_source_repo': HISTORICAL_REPO,\n                 'actual_isolated_materialization': cfg['isolated_materialization']})\n"),
    ("        check(self.m.verify_original_inputs()['unchanged'] is True, 'original inputs before native stage')\n", "        check(self.m.verify_original_inputs()['unchanged'] is True, 'original inputs before native stage')\n        check(self.h.verify_original_inputs()['unchanged'] is True, 'historical runtime proof inputs before native stage')\n"),
    ("        self.m.verify_original_inputs()\n        current_git = self.m.git_state()\n", "        self.m.verify_original_inputs()\n        self.h.verify_original_inputs()\n        self.h.jwrite('INPUTS.final.json', self.h.input_pins)\n        self.h.jwrite('READONLY_COMMANDS.json', self.h.commands)\n        current_git = self.m.git_state()\n"),
]
for before, after in replacements:
    assert code.count(before) == 1, before
    code = code.replace(before, after)
needle = '    def before_native_stage(self, name):\n'
assert code.count(needle) == 1
code = code.replace(needle, (HERE / 'VALIDATE_MATERIALIZATION.py.txt').read_text() + '\n' + needle)
compile(code, 'qualification-admission.isolated.HOLD.py', 'exec')
raw = code.encode()
cfg = json.loads((OLD / 'QUALIFICATION_INPUT.cc57-v2.HOLD.json').read_bytes())
base = '/home/qian-qi/hepta-utility-36fa-evidence/final-native-cc57-isolated-v1'
cfg.update(state='HOLD_AWAIT_ACTUAL_ISOLATED_MATERIALIZATION_AND_ROOT_EXACT_LAUNCH', root_execution_approved=False,
           historical_source_repo='/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1',
           repo='/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1',
           admission_path=base + '/qualification-admission.py', admission_pin=identity(raw),
           records=base + '/native-records', native_driver_path=base + '/native-driver.original.py',
           plan_path=base + '/PLAN.original.json', root_parent='/run/hepta-utility-36fa-final-cc57-isolated-v1',
           run_identity='hepta-utility-36fa-native-cc57-isolated-v1',
           isolated_materialization={'job_id': None, 'result': None,
               'result_path': '/home/qian-qi/hepta-utility-36fa-evidence/cc57-isolated-materialization-v1/run/RESULT.json',
               'supervisor': None, 'supervisor_path': base + '/ISOLATED_MATERIALIZATION_NORMAL.original.json'})
assert cfg['runtime_guard'] == json.loads((OLD / 'QUALIFICATION_INPUT.cc57-v2.HOLD.json').read_bytes())['runtime_guard']
diff = ''.join(difflib.unified_diff(old.decode().splitlines(keepends=True), code.splitlines(keepends=True),
                                  fromfile='actual-a8be-admission', tofile='isolated-dual-instance-admission')).encode()
outputs = {'qualification-admission.isolated.HOLD.py': raw, 'WAITING_QUALIFICATION_INPUT.json': encode(cfg),
           'FROM_A8BE.diff': diff}
for name, data in outputs.items():
    with (HERE / name).open('xb') as f:
        f.write(data)
print(json.dumps({name: identity(data) for name, data in outputs.items()}, indent=2))
