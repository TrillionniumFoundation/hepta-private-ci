"""Source-only mock Hub metadata tests: no pretrained weights or network."""
from __future__ import annotations
import copy
import unittest
from types import SimpleNamespace as S
import gate
import preflight


def good_meta(name):
    needed=preflight.WANTED[name]
    names=set(needed)
    if name.startswith('laya'):
        names.add('tokenizer/tokenizer.json')
    else:
        names.add('tokenizer.json')
    entries=[]
    for path in sorted(names):
        tensor=path.endswith(('.bin','.safetensors'))
        entries.append(S(rfilename=path,size=1500000000 if tensor else 100,
                         lfs={'sha256':'a'*64} if tensor else None))
    return S(sha=gate.MODELS[name][1],siblings=entries)


class PreflightTests(unittest.TestCase):
    def test_full_four_metadata_only(self):
        revmap={v[0]:k for k,v in gate.MODELS.items()}
        def resolver(*,repo_id,revision,files_metadata):
            k=revmap[repo_id]
            self.assertEqual(revision,gate.MODELS[k][1])
            self.assertIs(files_metadata,True)
            return good_meta(k)
        result=preflight.run(resolver)
        self.assertEqual(len(result['models']),4)
        self.assertEqual(result['disposition'],'HOLD_NO_GO')
        self.assertIs(result['production_promotion_permitted'],False)
        self.assertIs(result['all_original_weights_downloaded'],False)
        self.assertTrue([r for r in result['models'] if r['model']=='ettin400'][0]['requires_safe_weights_only_conversion'])
    def test_wrong_sha(self):
        x=good_meta('ettin400');x.sha='0'*40
        with self.assertRaises(gate.Denied):preflight.inspect_model('ettin400',x)
    def test_missing_weight(self):
        x=good_meta('ettin400');x.siblings=[v for v in x.siblings if v.rfilename!='pytorch_model.bin']
        with self.assertRaises(gate.Denied):preflight.inspect_model('ettin400',x)
    def test_missing_lfs(self):
        x=good_meta('ettin400');x.siblings[1].lfs=None
        # Choose exact weight by name rather than a brittle assumed sort order.
        for v in x.siblings:
            if v.rfilename=='pytorch_model.bin':v.lfs=None
        with self.assertRaises(gate.Denied):preflight.inspect_model('ettin400',x)
    def test_unsafe_parent_path(self):
        x=good_meta('ettin400');x.siblings.append(S(rfilename='../weights.bin',size=500,lfs={'sha256':'a'*64}))
        with self.assertRaises(gate.Denied):preflight.inspect_model('ettin400',x)
    def test_duplicate_file(self):
        x=good_meta('ettin400');x.siblings.append(copy.copy(x.siblings[0]))
        with self.assertRaises(gate.Denied):preflight.inspect_model('ettin400',x)
    def test_missing_tokenizer(self):
        x=good_meta('ettin400');x.siblings=[v for v in x.siblings if 'tokenizer' not in v.rfilename]
        with self.assertRaises(gate.Denied):preflight.inspect_model('ettin400',x)
    def test_missing_head_bundle(self):
        x=good_meta('openjev434');x.siblings=[v for v in x.siblings if v.rfilename!='head.safetensors']
        with self.assertRaises(gate.Denied):preflight.inspect_model('openjev434',x)
    def test_unbounded_weight(self):
        x=good_meta('ettin400');next(v for v in x.siblings if v.rfilename=='pytorch_model.bin').size=1+preflight.MAX_WEIGHT_BYTES
        with self.assertRaises(gate.Denied):preflight.inspect_model('ettin400',x)
    def test_wrong_model(self):
        with self.assertRaises(gate.Denied):preflight.inspect_model('evil',good_meta('ettin400'))
    def test_malformed_lfs(self):
        x=good_meta('ettin400');next(v for v in x.siblings if v.rfilename=='pytorch_model.bin').lfs={'sha256':'NO'}
        with self.assertRaises(gate.Denied):preflight.inspect_model('ettin400',x)
    def test_no_remote_code_path(self):
        result=preflight.inspect_model('laya421',good_meta('laya421'))
        self.assertIs(result['remote_code_execution_allowed'],False)
        self.assertIs(result['loaded_model_tensors_verified'],False)

if __name__=='__main__':unittest.main()
