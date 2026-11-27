"""Synthetic parity and replay tests without touching any RSICD target or fitting corpus model."""
import argparse
from construct import *


@torch.inference_mode()
def main():
    a=argparse.ArgumentParser();a.add_argument('out',type=Path);p=a.parse_args()
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    class Dummy:meta={'vocab_size':850}
    data=Dummy();g=torch.Generator().manual_seed(83117)
    pix=torch.randint(0,256,(8,32,32,3),generator=g,dtype=torch.uint8);x=torch.randint(1,850,(8,17),generator=g);y=torch.randint(1,850,(8,17),generator=g);y[:,8:]=0
    ids=np.arange(8);v={}
    for mode in ('forward','shuffle','feature_only','tied_only','frozen_probe'):
        m=original(125,data);direct=m(pix,x);manual=F.linear(hidden(m,pix,x),m.words.weight)
        assert torch.equal(direct,manual)
        rec,detail=construct(m,pix,x,y,ids,mode,125);b=rebuild(125,data,rec)
        live=Probe(m,rec['probe']) if 'probe' in rec else m
        z=live(pix,x);r=b(pix,x);assert torch.equal(z,r) and torch.isfinite(z).all()
        if mode in ('forward','shuffle','feature_only'):
            assert all(detail['matrix_writes'][f'ff.{i}.{k}.weight']['changed_coordinates']>0 for i in range(6) for k in (0,2))
        v[mode]={'direct_features_logits_max_abs':float((manual-direct).abs().max()),'recipe_logits_max_abs':float((r-z).abs().max()),
          'trained_tensor_count':len(rec['writes']),'solved_independent_coefficients':sum(u['free_coefficients'] for u in detail['matrix_writes'].values()),
          'dense_coordinates_changed':sum(u['changed_coordinates'] for u in detail['matrix_writes'].values()),'nominal_original_parameters':detail['nominal_base_parameters'],'seed':125}
    foo=torch.arange(8.).double();pr=torch.stack((foo,2*foo),1);assert torch.linalg.matrix_rank(pr)==1 and torch.equal(pr@torch.tensor([2.,0.]).double(),pr@torch.tensor([0.,1.]).double())
    write(p.out,{'scope':'8 synthetic random pixel images with synthetic vocabulary labels; engine parity/parameter-accounting test only','arms':v,
        'two_price_counterexample':'if observed tanh(L)=2*tanh(E), coefficients (2,0) and (0,1) yield exactly the same additive pressure; direct targets alone cannot identify both originals',
        'word_vocabulary':850,'source_model_sha':sha(BASE/'model.py'),'source_eval_sha':sha(BASE/'study.py')})


if __name__=='__main__':main()
