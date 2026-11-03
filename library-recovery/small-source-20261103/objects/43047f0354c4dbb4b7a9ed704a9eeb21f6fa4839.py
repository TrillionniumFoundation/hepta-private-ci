from pathlib import Path
import hashlib, subprocess, yaml
root=Path('/mnt/data/hepta_hf519_abi_v17')
src=Path('/mnt/data/hepta_v16_2_type_census/.github/workflows/hepta-p0-mmbert-stage-census-v16.yml')
w=src.read_text()
def change(a,b):
 global w
 if w.count(a)!=1:raise ValueError(f'Expected one exact anchor, got {w.count(a)}')
 w=w.replace(a,b)
change("      - 'experiments/shared_stem_cell/P0_MMBERT_STAGE_CENSUS_V16.md'\n      - '.github/workflows/hepta-p0-mmbert-stage-census-v16.yml'", """      - 'experiments/shared_stem_cell/P0_MMBERT_STAGE_CENSUS_V16.md'
      - 'experiments/shared_stem_cell/p0_hf519_loading_report_abi_v17.py'
      - 'experiments/shared_stem_cell/test_p0_hf519_loading_report_abi_v17.py'
      - 'experiments/shared_stem_cell/P0_HF519_LOADING_REPORT_ABI_V17.md'
      - '.github/workflows/hepta-p0-mmbert-stage-census-v16.yml'""")
change('''          PYTHONPATH="$D" python -O -m unittest discover -s "$D" -p test_p0_mmbert_stage_census_v16.py -v
          mkdir -p "$RUNNER_TEMP/mmbert-stage-v16"''','''          PYTHONPATH="$D" python -O -m unittest discover -s "$D" -p test_p0_mmbert_stage_census_v16.py -v
          # Independent source-only 5.19 ABI fixture; the actual upstream ABI
          # is verified separately AFTER installing the pinned Python wheel.
          python -m py_compile "$D/p0_hf519_loading_report_abi_v17.py" \\
            "$D/test_p0_hf519_loading_report_abi_v17.py"
          PYTHONPATH="$D" python -m unittest discover -s "$D" -p test_p0_hf519_loading_report_abi_v17.py -v
          PYTHONPATH="$D" python -O -m unittest discover -s "$D" -p test_p0_hf519_loading_report_abi_v17.py -v
          mkdir -p "$RUNNER_TEMP/mmbert-stage-v16"''')
change('''          python -m pip freeze > "$RUNNER_TEMP/mmbert-stage-v16/pinned-runtime.txt"
      - name: Require original immutable revision and strict publisher LFS bytes''','''          python -m pip freeze > "$RUNNER_TEMP/mmbert-stage-v16/pinned-runtime.txt"
      - name: Verify actual pinned Transformers 5.19 loader-report ABI (no weights)
        shell: bash
        run: |
          set -euo pipefail
          D=experiments/shared_stem_cell
          PYTHONPATH="$D" python "$D/p0_hf519_loading_report_abi_v17.py" \\
            --output "$RUNNER_TEMP/mmbert-stage-v16/hf519-loader-report-abi-v17.json"
          python - <<'PY'
          import json,os
          from pathlib import Path
          p=Path(os.environ['RUNNER_TEMP'])/'mmbert-stage-v16/hf519-loader-report-abi-v17.json'
          a=json.loads(p.read_text())
          if (a['schema']!='hepta.p0.hf519-original-load-report-abi.v17' or
              a['installed_transformers_required_version']!='5.19.0' or
              a['strict_denial_cases_tested']!=5 or
              a['observed_report_collection_kinds']!={'missing_keys':'set',
                  'unexpected_keys':'set','mismatched_keys':'set','error_msgs':'list'} or
              a['actual_model_weights_loaded_by_this_probe'] or
              a['complete_original_tensor_byte_comparison_by_this_probe'] or
              a['production_accepted'] or a['model_selected'] or
              a['authority']!='DENY_ALL'):
              raise ValueError('unqualified pinned upstream HF loader ABI')
          PY
      - name: Require original immutable revision and strict publisher LFS bytes''')
change('''            ${{ runner.temp }}/mmbert-stage-v16/source-identity.txt
            ${{ runner.temp }}/mmbert-stage-v16/compact-preflight-v9.json''','''            ${{ runner.temp }}/mmbert-stage-v16/source-identity.txt
            ${{ runner.temp }}/mmbert-stage-v16/hf519-loader-report-abi-v17.json
            ${{ runner.temp }}/mmbert-stage-v16/compact-preflight-v9.json''')
p=root/'.github/workflows/hepta-p0-mmbert-stage-census-v16.yml'
p.write_text(w)
b=w.encode();blob=hashlib.sha1(f'blob {len(b)}\0'.encode()+b).hexdigest()
assert blob=='d410e2d66aa306c5c949ebd68885d5134f1fb677',f'workflow drift {blob}'
class UniqueLoader(yaml.SafeLoader):pass
def construct_mapping(loader, node, deep=False):
    vals={}
    for key_node,value_node in node.value:
        key=loader.construct_object(key_node,deep=deep)
        if key in vals:raise ValueError('duplicate YAML key '+str(key))
        vals[key]=loader.construct_object(value_node,deep=deep)
    return vals
UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)
wf=yaml.load(w,Loader=UniqueLoader)
runs=[st['run'] for job in wf['jobs'].values() for st in job['steps'] if 'run' in st]
for i,script in enumerate(runs):
 q=subprocess.run(['bash','-n'],text=True,input=script,capture_output=True)
 assert q.returncode==0,(i,q.stderr)
assert len(runs)==5,len(runs)
print('Exact remote Git Blob SHA:',blob)
print('Duplicate-safe YAML parsed, 5/5 bash run blocks passed syntax checks')
print('Source tests remain 23; V15 tests 17 + original physical Tied Byte suite 11; new V17 12 (normal/-O)')
