"""Search the complete previously enumerated HCSN program and narrative blob set."""
import csv,json,re,subprocess,sys
from pathlib import Path


def main(index,gitdir,output):
    patterns={
        'independent_first_hit':r'(?:condition\w* independent|independent(?:ly)?|iid|i\.i\.d\.).{0,60}(?:microdomains?|microchannels?|first.{0,5}hitt?\w*|first.{0,5}passage|competing risks?|survival.{0,15}power)|(?:first.{0,5}hitt?\w*|first.{0,5}passage|competing risks?|survival).{0,45}(?:independent copies|independent paths|independent micro)',
        'microdomain_lexical':r'(?:microdomains?|microchannels?|competing.{0,3}risk|minimum.{0,10}hitting time|earliest.{0,8}hitting time)',
        'survival_power':r'(?:surviv(?:al|or)|s_live|p_live)\s*(?:\.pow\(|\*\*|\^)\s*\(?\s*(?:n|k|copies|2|3)\b',
        'explicit_complement_product':r'1\s*[-−]\s*\(?\s*1\s*[-−]\s*(?:hit|risk|passage|p_hit|f_t|cdf)\s*\)?\s*(?:\*\*|\^)\s*(?:n|k|copies|2)\b'
    }; pats={n:re.compile(r,re.I) for n,r in patterns.items()}
    rows=list(csv.DictReader(index.open(),delimiter='\t'));p=subprocess.Popen(['git','--git-dir='+str(gitdir),'cat-file','--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    results={k:[] for k in pats};size=0
    for row in rows:
        oid=row['blob'] if 'blob' in row else list(row.values())[0];path=row.get('example_path',list(row.values())[2]);p.stdin.write((oid+'\n').encode());p.stdin.flush();header=p.stdout.readline().split();assert header[0].decode()==oid and header[1]==b'blob';n=int(header[2]);data=p.stdout.read(n);assert len(data)==n and p.stdout.read(1)==b'\n';size+=n
        source=data.decode('utf8','replace')
        for key,pat in pats.items():
            m=pat.search(source)
            if m:results[key].append({'sha':oid,'example_path':path,'matched_text':' '.join(m.group().split())[:150]})
    p.stdin.close();p.wait();assert p.returncode==0
    output.write_text(json.dumps({'catalogued_blobs':len(rows),'bytes':size,'patterns':patterns,'results':results},indent=2)+'\n')
    print(len(rows),size,{k:len(v) for k,v in results.items()})


if __name__=='__main__':main(*map(Path,sys.argv[1:]))
