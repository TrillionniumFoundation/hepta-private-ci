"""Create a fit/development-only token archive; read zero held-out answers into the fit workers."""
import argparse
import shutil
import subprocess
import tempfile
import time
from support import *


def main():
    ap=argparse.ArgumentParser();ap.add_argument('work',type=Path);a=ap.parse_args();a.work.mkdir(exist_ok=True,parents=True)
    tick=time.perf_counter();cpu=time.process_time()
    meta=json.loads((ROOT/'data.json').read_bytes());r={}
    with tempfile.TemporaryDirectory(dir=a.work) as temp:
        tmp=Path(temp)
        t=time.perf_counter()
        subprocess.run([sys.executable,str(BASE/'prepare.py'),'/tmp/hcsn-rsicd-processed','/tmp/hcsn-rsicd-inputs',str(tmp)],check=True,stdout=subprocess.DEVNULL)
        r['canonical_caption_prep_plus_hash_and_process_launch_wall']=time.perf_counter()-t
        for n in ('data.npz','vocabulary.json'):assert sha(tmp/n)==sha(ROOT/n),n
    t=time.perf_counter()
    with np.load(ROOT/'data.npz') as z:
        allowed=np.concatenate((z['train'],z['development']))
        x=np.zeros(z['inputs'].shape,dtype=np.int16);y=np.zeros_like(x)
        x[allowed]=z['inputs'][allowed];y[allowed]=z['targets'][allowed]
        assert not np.intersect1d(z['test'],allowed).size and not y[z['test']].any()
        np.savez_compressed(a.work/'fit_only.npz',inputs=x,targets=y,train=z['train'],development=z['development'])
    r.update({'fit_only_sha256':sha(a.work/'fit_only.npz'),'source_tokens_sha256':sha(ROOT/'data.npz'),'raw_pixels_sha256':sha(meta['pixels']),
            'law_sha256':sha(ROOT/'law4.npz'),'fit_only_packing_s':time.perf_counter()-t,'total_wall_s':time.perf_counter()-tick,
            'shared_original_decoding':'canonical arrays from author captions and byte-verified raw 32x32 RGB; initial image download, compression and resize not timed by this extension',
            'rows_held_out_zeroed':964,'fit_rows':6311,'development_rows':128})
    write(a.work/'prepared.json',r)


if __name__=='__main__':main()
