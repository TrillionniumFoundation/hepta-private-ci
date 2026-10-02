#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/qian-qi/rog-ai-smu-ab
STAGE=$ROOT/smu_ab_stage.py
APPLY=/usr/local/sbin/rog-ai-smu-apply
PRODUCTION=/usr/local/sbin/rog-ai-production-profile
MONITOR=rog-ai-safety-monitor.service
LATCH=/var/lib/rog-ai-production/safe-latch
OWNER=/var/lib/rog-ai-production/smu-ab-owner-20261002
COMPLETE=/var/lib/rog-ai-production/smu-ab-complete-20261002
OVERRIDE=20261002
START_EPOCH=$(date +%s)
SUCCESS=$ROOT/qualification-success-20261002

finish() {
  rc=$?
  trap - EXIT
  set +e
  if sudo -n test -e "$LATCH"; then
    sudo -n "$APPLY" safe
  else
    sudo -n "$PRODUCTION"
  fi
  sudo -n systemctl restart "$MONITOR"
  test "$(systemctl is-active "$MONITOR")" = active || rc=1
  if test -f "$SUCCESS"; then
    sudo -n mv -f "$OWNER" "$COMPLETE"
  else
    sudo -n rm -f "$OWNER"
  fi
  sudo -n /usr/local/src/RyzenAdj/build/ryzenadj --info \
    > "$ROOT/final-smu-info-20261002.txt" 2>&1
  if sudo -n journalctl -k -b --since "@$START_EPOCH" --no-pager | \
      grep -Ei 'amdgpu.*(reset|timeout|fault|wedged)|hardware error|mce:|thermal.*critical'; then
    rc=1
  fi
  exit "$rc"
}
trap finish EXIT

mkdir -p "$ROOT"
exec 9>"$ROOT/qualification-20261002.lock"
flock -n 9 || { echo 'another SMU qualification owns the host'; exit 75; }
rm -f "$SUCCESS"

test "$GITHUB_REPOSITORY" = TrillionniumFoundation/hepta-private-ci
test "$GITHUB_REF" = refs/heads/ops/rog-smu-ab-20261002
test "$GITHUB_ACTOR" = ProfHepta
test "$(cat /sys/class/dmi/id/board_name)" = GZ302EA
test "$(uname -r)" = 7.0.0-34-generic
sudo -n true
test -d /sys/kernel/ryzen_smu_drv
test "$(cat /sys/kernel/ryzen_smu_drv/drv_version)" = 0.1.7
modinfo -F signer ryzen_smu | grep -F \
  'qian-qi-ROG-Flow-Z13-GZ302EA-GZ Secure Boot Module Signature key'
test "$(systemctl is-active "$MONITOR")" = active
sudo -n test ! -e "$LATCH"
test -x "$APPLY"
test -x "$PRODUCTION"
test -f "$STAGE"
test -x /usr/local/src/RyzenAdj/build/ryzenadj
test -x /home/qian-qi/pocket4-gfx1150-bench/gfx1151_bench

sudo -n install -d -o root -g root -m 0750 /var/lib/rog-ai-production
sudo -n install -d -o root -g root -m 0700 \
  /var/backups/rog-ai-smu/ops-20261002
if ! sudo -n test -f \
    /var/backups/rog-ai-smu/ops-20261002/rog-ai-smu-apply.before; then
  sudo -n cp -a "$APPLY" \
    /var/backups/rog-ai-smu/ops-20261002/rog-ai-smu-apply.before
fi

sudo -n python3 - "$APPLY" "$OWNER" "$COMPLETE" <<'PY'
import pathlib, sys
path, owner, complete = map(pathlib.Path, sys.argv[1:])
source = path.read_text()
if 'ROG_AI_SMU_AB_OVERRIDE' not in source:
    anchor = 'case "${1:-}" in\n'
    replacement = '''profile="${1:-}"
if [[ ( -e "''' + str(owner) + '''" || -e "''' + str(complete) + '''" ) &&
      "${ROG_AI_SMU_AB_OVERRIDE:-}" != "20261002" &&
      "$profile" != baseline && "$profile" != safe ]]; then
  echo "SMU qualification is exclusively owned or already complete" >&2
  exit 75
fi
case "$profile" in
'''
    if anchor not in source:
        raise SystemExit('helper guard anchor missing')
    path.write_text(source.replace(anchor, replacement, 1))
PY
sudo -n chmod 0755 "$APPLY"
sudo -n touch "$OWNER"
sudo -n rm -f "$COMPLETE"

python3 - "$STAGE" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
source = path.read_text()
source = source.replace(
    "def restore():\n    if LATCH.exists():",
    "def is_latched():\n    return sudo('test', '-e', LATCH, check=False).returncode == 0\n\ndef restore():\n    if is_latched():")
source = source.replace("        'latched': LATCH.exists(),\n", "")
source = source.replace(
    "    if LATCH.exists():\n        raise SystemExit('safety latch present before stage')",
    "    if is_latched():\n        raise SystemExit('safety latch present before stage')")
source = source.replace("            if p.returncode or LATCH.exists():",
                        "            if p.returncode or is_latched():")
source = source.replace("        summary['latched'] = LATCH.exists()",
                        "        summary['latched'] = is_latched()")
source = source.replace(
    "        applied = sudo('/usr/local/sbin/rog-ai-smu-apply', args.profile, check=False)",
    "        applied = sudo('/usr/bin/env', 'ROG_AI_SMU_AB_OVERRIDE=20261002', '/usr/local/sbin/rog-ai-smu-apply', args.profile, check=False)")
if 'LATCH.exists()' in source:
    raise SystemExit('unpatched direct latch access remains')
compile(source, str(path), 'exec')
path.write_text(source)
PY

cool() {
  python3 - <<'PY'
import pathlib, time
def sensor(name):
    for root in pathlib.Path('/sys/class/hwmon').glob('hwmon*'):
        try:
            if (root/'name').read_text().strip() == name:
                return root
        except OSError:
            pass
    raise SystemExit('missing '+name)
cpu, gpu = sensor('k10temp'), sensor('amdgpu')
for _ in range(30):
    ct=int((cpu/'temp1_input').read_text())
    gt=int((gpu/'temp1_input').read_text())
    print(f'cooldown cpu={ct/1000:.1f}C gpu={gt/1000:.1f}C', flush=True)
    if ct < 85000 and gt < 85000:
        break
    time.sleep(2)
PY
}

stage() {
  local profile=$1 label=$2 loops=$3 mode=${4:-screen}
  python3 "$STAGE" --profile "$profile" --label "$label" --loops "$loops" \
    2>&1 | tee "$ROOT/workflow-$label-$profile.log"
  local summary
  summary=$(ls -1dt "$ROOT"/*-"$label"-"$profile"/summary.json | head -n1)
  python3 - "$summary" "$mode" <<'PY'
import json, sys
d=json.load(open(sys.argv[1])); mode=sys.argv[2]
print(json.dumps({'label':d.get('label'),'profile':d.get('profile'),
                  'status':d.get('status'),'wmma':d.get('rocwmma_TFLOPs'),
                  'telemetry':d.get('telemetry'),'faults':d.get('kernel_faults'),
                  'latched':d.get('latched')}, indent=2))
if d.get('kernel_faults') or d.get('latched') or d.get('status') == 'failed':
    raise SystemExit(2)
if mode == 'canary' and d.get('status') != 'passed':
    raise SystemExit(3)
PY
  cool
}

stage baseline canary 5 canary
sequence=(
  baseline:A0 apu90:B-apu90 baseline:A1 apu120:C-apu120 baseline:A2
  co-neg5:D-co5 baseline:A3 co-neg10:E-co10 baseline:A4
  co-neg15:F-co15 baseline:A5 combined-neg5:G-combined5 baseline:A6
  combined-neg10:H-combined10 baseline:A7 thermal100:I-thermal100 baseline:A8
)
for item in "${sequence[@]}"; do
  stage "${item%%:*}" "${item#*:}" 20 screen
done

python3 - "$ROOT" <<'PY'
import json, pathlib, statistics, sys
root=pathlib.Path(sys.argv[1])
sequence=[
 ('baseline','A0'),('apu90','B-apu90'),('baseline','A1'),
 ('apu120','C-apu120'),('baseline','A2'),('co-neg5','D-co5'),
 ('baseline','A3'),('co-neg10','E-co10'),('baseline','A4'),
 ('co-neg15','F-co15'),('baseline','A5'),
 ('combined-neg5','G-combined5'),('baseline','A6'),
 ('combined-neg10','H-combined10'),('baseline','A7'),
 ('thermal100','I-thermal100'),('baseline','A8')]
stages=[]
for profile,label in sequence:
    candidates=sorted(root.glob(f'*-{label}-{profile}/summary.json'),
                      key=lambda p:p.stat().st_mtime)
    if not candidates: raise SystemExit(f'missing stage {label}/{profile}')
    stages.append(json.load(open(candidates[-1])))
comparisons=[]
for i,s in enumerate(stages):
    if s['profile']=='baseline': continue
    refs=[]
    for n in (i-1,i+1):
        if 0<=n<len(stages) and stages[n]['profile']=='baseline':
            refs.append(stages[n]['rocwmma_TFLOPs']['mean'])
    baseline=statistics.fmean(refs)
    candidate=s['rocwmma_TFLOPs']['mean']
    comparisons.append({'label':s['label'],'profile':s['profile'],
      'status':s['status'],'baseline':baseline,'candidate':candidate,
      'percent':(candidate/baseline-1)*100,
      'cpu_max_C':s['telemetry']['cpu_C']['max'],
      'gpu_max_C':s['telemetry']['gpu_C']['max'],
      'package_mean_W':s['telemetry']['package_W']['mean']})
accepted=[x for x in comparisons if x['status']=='passed']
accepted.sort(key=lambda x:x['percent'],reverse=True)
matrix={'stages':stages,'comparisons':comparisons,
        'best_screened':accepted[0] if accepted else None}
(root/'matrix-20261002.json').write_text(json.dumps(matrix,indent=2)+'\n')
print('MATRIX_RESULT='+json.dumps({'comparisons':comparisons,
      'best_screened':matrix['best_screened']},sort_keys=True))
PY
touch "$SUCCESS"
