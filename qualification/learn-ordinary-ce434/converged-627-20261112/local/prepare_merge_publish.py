from pathlib import Path
import subprocess, json, hashlib, sys

left, right, output = sys.argv[1:]
def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()
assert git('rev-parse', 'HEAD') == left
assert git('rev-parse', 'MERGE_HEAD') == right
assert not git('diff', '--name-only', '--diff-filter=U')
subprocess.run(['git', 'diff', '--cached', '--check'], check=True)
def blobs(ref):
    return {x.split()[2] for x in git('ls-tree', '-r', ref).splitlines()
            if x.split()[1] == 'blob'}
known = blobs(left) | blobs(right)
changed = [x for x in subprocess.check_output(
    ['git', 'diff', '--cached', '--name-only', '-z'], text=True).split('\0') if x]
index = {line.split('\t', 1)[1]: (line.split()[0], line.split()[1])
         for line in git('ls-files', '-s').splitlines()}
entries = [{'path': p, 'mode': index[p][0], 'type': 'blob', 'sha': index[p][1]}
           for p in changed]
novel = []
for entry in entries:
    if entry['sha'] not in known:
        raw = Path(entry['path']).read_bytes()
        novel.append({**entry, 'bytes': len(raw), 'chars': len(raw.decode()),
                      'sha256': hashlib.sha256(raw).hexdigest()})
report = {'left': left, 'right': right, 'base_tree': git('rev-parse', left+'^{tree}'),
          'merge_base': git('merge-base', '--all', left, right),
          'tree': git('write-tree'), 'entries': entries, 'novel': novel}
Path(output).write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report))
