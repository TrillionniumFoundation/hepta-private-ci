"""Independently recompute nonzero square-minor determinant by partial-pivot row swaps."""
import hashlib,json,sys
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parent
def det(rows,prime):
    mat=[]
    for line in rows:
        a=[]
        for v in line:
            x,y=float(v).as_integer_ratio();a.append(x*pow(y,prime-2,prime)%prime)
        mat.append(a)
    out=1
    for i in range(len(rows)):
        pivot=next((j for j in range(i,len(rows)) if mat[j][i]),None)
        if pivot is None:return 0
        if i!=pivot:
            out=-out;mat[i],mat[pivot]=mat[pivot],mat[i]
        coef=mat[i][i];out=out*coef%prime;inverse=pow(coef,prime-2,prime)
        for j in range(i+1,len(rows)):
            scale=mat[j][i]*inverse%prime
            for k in range(i,len(rows)):mat[j][k]=(mat[j][k]-scale*mat[i][k])%prime
    return out%prime
def main():
    sys.path.insert(0,str(P.parent/'allparams'))
    import smallpack
    src=P/'results';allres=json.loads((src/'results.json').read_text());out=P.parent/'publish_nullspace';out.mkdir(exist_ok=True)
    for row in allres['rows']:
        base=src/str(row['seed']);assert smallpack.file_digest(base/'matrices.npz')==row['data_sha256']
        with np.load(base/'matrices.npz',allow_pickle=False) as z:
            ids=z['source_ids'];steps=z['steps']
            for k,entry in row['observed'].items():
                a=z[k];index=entry['retained_row_indices'];minor=a[index].astype('<f4')
                assert hashlib.sha256(minor.tobytes()).hexdigest()==entry['minor_sha256']
                if entry['certified_full_rational_rank']:
                    value=det(minor,allres['prime']);assert value==entry['det_mod_prime'] and value>0
                singular=np.linalg.svd(a.astype('float64'),compute_uv=False);assert np.array_equal(singular,entry['singular_values'])
                assert entry['source_ids']==[str(ids[i if k=='first_input' else i//len(steps)]) for i in index]
    import shutil
    for n in ('PROTOCOL.md','audit_rank.py','verify.py'):shutil.copyfile(P/n,out/n)
    shutil.copyfile(P.parent/'allparams'/'smallpack.py',out/'smallpack.py');shutil.copyfile(src/'results.json',out/'results.json')
    idx=smallpack.pack({str(f.relative_to(src)):f for f in src.glob('*/*')},out);smallpack.restore(out)
    print('verified',smallpack.file_digest(out/'results.json'),len(idx['archives']))
if __name__=='__main__':main()
