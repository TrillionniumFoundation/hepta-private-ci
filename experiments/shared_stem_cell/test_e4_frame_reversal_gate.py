"""Frame byte identity and sequence manipulation cases; entirely synthetic fixtures."""
import copy,hashlib,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import e4_frame_reversal_gate as e
H='a'*64

def setup(root):
    files=[];digests=[]
    for i in range(3):
        name=f'frame{i}.png';content=b'png-byte-probe-'+str(i).encode()
        (root/name).write_bytes(content);files.append(name);digests.append(hashlib.sha256(content).hexdigest())
    item={'pair_id':'p0','source_group':'g0','scope':'s','split':'test','observed_at':1,
          'source_video_sha256':H,'question_sha256':H,'forward':{'files':files,'frame_sha256s':digests},
          'reversed':{'files':files[::-1],'frame_sha256s':digests[::-1]},
          'labels':{'forward':1,'reversed':0},'predictions':{
              'order_invariant':{'forward':.5,'reversed':.5,'prelabel_sealed':True},
              'frozen_temporal':{'forward':.5,'reversed':.5,'prelabel_sealed':True},
              'learned_temporal':{'forward':.9,'reversed':.1,'prelabel_sealed':True}}}
    return {'schema':e.SCHEMA,'authority':'DENY_ALL','production_promotion_permitted':False,
            'scope':'s','plan_sha256':H,'source_sha256':H,'temporal_model_sha256':H,'frame_preprocessor_sha256':H,'pairs':[item]}
class Tests(unittest.TestCase):
 def accept(self):
    with tempfile.TemporaryDirectory() as d:
        path=Path(d);p=setup(path);r=e.review(p,path)
        self.assertFalse(r['model_weights_or_temporal_forwards_verified'])
        self.assertEqual(r['split_metrics']['test']['arms']['learned_temporal']['both_correct_pairs'],1)
 def deny(self,change):
    with tempfile.TemporaryDirectory() as d:
        root=Path(d);p=setup(root);change(p,root)
        with self.assertRaises((e.Invalid,ValueError,KeyError,TypeError)):
            e.review(p,root)
 def test_matched_reversal_synthetic(self):self.accept()
 def test_identity_order_reuse(self):self.deny(lambda p,r:p['pairs'][0].update(reversed=copy.deepcopy(p['pairs'][0]['forward'])))
 def test_changed_source_hash(self):self.deny(lambda p,r:p['pairs'][0]['forward']['frame_sha256s'].__setitem__(0,H))
 def test_changed_frame_content(self):self.deny(lambda p,r:(r/'frame0.png').write_bytes(b'tampered'))
 def test_bad_label_flip(self):self.deny(lambda p,r:p['pairs'][0]['labels'].update(reversed=1))
 def test_unsealed_prediction(self):self.deny(lambda p,r:p['pairs'][0]['predictions']['learned_temporal'].update(prelabel_sealed=False))
 def test_fake_temporal_baseline(self):self.deny(lambda p,r:p['pairs'][0]['predictions']['order_invariant'].update(reversed=.2))
 def test_missing_frames(self):self.deny(lambda p,r:p['pairs'][0]['reversed']['files'].pop())
 def test_unsafe_parent_traversal(self):self.deny(lambda p,r:p['pairs'][0]['forward']['files'].__setitem__(0,'../escape.png'))
 def test_wrong_modality(self):self.deny(lambda p,r:p['pairs'][0]['forward']['files'].__setitem__(0,'frame0.exe'))
 def test_missing_frame(self):self.deny(lambda p,r:(r/'frame0.png').unlink())
 def test_symlink(self):
    def change(p,r):
        (r/'link.png').symlink_to(r/'frame0.png')
        p['pairs'][0]['forward']['files'][0]='link.png'
    self.deny(change)
 def test_invalid_nan(self):self.deny(lambda p,r:p['pairs'][0]['predictions']['learned_temporal'].update(forward=float('nan')))
 def test_production_promotion(self):self.deny(lambda p,r:p.update(production_promotion_permitted=True))
 def test_changed_group(self):self.deny(lambda p,r:p['pairs'][0].update(scope='different'))
if __name__=='__main__':unittest.main()
