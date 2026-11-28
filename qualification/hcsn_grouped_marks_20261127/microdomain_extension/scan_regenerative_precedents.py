"""Test exact textual signatures across an existing, content-addressed HCSN source inventory."""
import argparse
import csv
import json
import re
import subprocess
from pathlib import Path


def main(index, git_dir, output):
    expressions={
        'named_fastest_or_first_to_hit':r'fastest.{0,32}(?:passage|hitt?|searcher)|(?:minimum|earliest).{0,20}(?:of.{0,4}(?:n|k).{0,15}hitting|independent.{0,15}(?:first|hit))|first.{0,14}(?:of|among).{0,24}independent.{0,16}(?:path|chain|particle|walker|unit)',
        'survival_power':r'(?:s_live|p_live|surviv(?:al|or))\s*(?:\.pow\(|\*\*|\^)\s*\(?\s*(?:n|k|copies|2|3)\b',
        'renewal_or_repeat_reset':r'\brenewal\b|repeated.{0,15}(?:hit|fire|reset|spik)|regenerati(?:on|ve)',
        'rounding_waits':r'(?:round(?:ing|ed)|floor|ceil).{0,35}(?:wait.{0,6}time|interarrival|inter.arrival|inter.spike interval)|(?:wait.{0,6}time|interarrival|inter.spike interval).{0,35}(?:round(?:ing|ed)|floor|ceil)'
    }
    patterns={k:re.compile(v,re.I) for k,v in expressions.items()}
    rows=list(csv.DictReader(index.open(),delimiter='\t'))
    proc=subprocess.Popen(['git','--git-dir='+str(git_dir),'cat-file','--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    hits={k:[] for k in expressions}; joint=[];total=0
    for row in rows:
        oid=row['blob'];proc.stdin.write((oid+'\n').encode());proc.stdin.flush()
        h=proc.stdout.readline().split();assert h[:2]==[oid.encode(),b'blob']
        size=int(h[-1]);raw=proc.stdout.read(size);assert len(raw)==size and proc.stdout.read(1)==b'\n';total+=size
        txt=raw.decode('utf8','replace');local={k for k,p in patterns.items() if p.search(txt)}
        for k in local:hits[k].append(oid)
        if 'renewal_or_repeat_reset' in local and {'survival_power','named_fastest_or_first_to_hit'} & local:
            joint.append({'oid':oid,'path':row['example_path']})
    proc.stdin.close();assert proc.wait()==0
    output.write_text(json.dumps({'unique_selected_blobs':len(rows),'bytes':total,'expressions':expressions,
      'counts':{k:len(v) for k,v in hits.items()},'joint_reset_and_multi_searcher_matches':joint,
      'limits':'Lexical signals over prior selected code and narratives. Unrelated wording or code without matching names may conceal an equivalent implementation.'},indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('index',type=Path);p.add_argument('git_dir',type=Path);p.add_argument('output',type=Path);a=p.parse_args();main(a.index,a.git_dir,a.output)
