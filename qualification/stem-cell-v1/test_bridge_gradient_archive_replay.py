"""Real Torch-generated FP32 tensors + optional ORIGINAL V6 evidence ZIP tests.

The test generator never fabricates pretrained task-quality evidence. The
HEPTA_ORIGINAL_V6_ZIP opt-in reopens the actual external 20.9MB archival bytes.
"""
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from collections import OrderedDict
import torch

from bridge_gradient_archive_replay import (
    SHAPES, SEEDS, V6_ZIP_SHA256, audit_v6_archive, audit_candidate_checkpoints,
    decode_fp32_checkpoint, validate_original_plan, sha_file, read_regular_file,
)
from bridge_gradient_review import review_complete, file_hash
from test_bridge_gradient_review import CompleteReviewerTests, write


def weight_bytes(seed):
    generator=torch.Generator().manual_seed(seed)
    tensors=OrderedDict((name,torch.randn(shape,generator=generator,dtype=torch.float32))
                        for name,shape in SHAPES.items())
    stream=io.BytesIO()
    torch.save(tensors,stream)
    return stream.getvalue()


class OriginalTensorMath(unittest.TestCase):
    def test_recompute_both_named_digest_encodings_on_real_cpu_fp32_state(self):
        data=weight_bytes(41)
        report=decode_fp32_checkpoint(data)
        self.assertEqual(report["tensor_count"],22)
        self.assertEqual(report["parameter_count"],42562)
        self.assertNotEqual(report["training_parameter_sha256"],report["execution_parameter_sha256"])
        self.assertFalse(report["torch_imported"])
        self.assertEqual(decode_fp32_checkpoint(data),report)

    def test_tensor_byte_tamper_rejected_even_when_file_sha_recomputed(self):
        before=decode_fp32_checkpoint(weight_bytes(41))
        after=decode_fp32_checkpoint(weight_bytes(42))
        self.assertNotEqual(before["training_parameter_sha256"],after["training_parameter_sha256"])
        self.assertNotEqual(before["execution_parameter_sha256"],after["execution_parameter_sha256"])

    def test_wrong_shape_missing_tensor_nonfinite_refused(self):
        base=OrderedDict((name,torch.ones(shape)) for name,shape in SHAPES.items())
        for action in ("missing", "shape", "nan"):
            s=copy.deepcopy(base)
            key=next(iter(s))
            if action=="missing":s.pop(key)
            elif action=="shape":s[key]=torch.ones(1)
            else:s[key].flatten()[0]=float('nan')
            blob=io.BytesIO();torch.save(s,blob)
            with self.subTest(action=action),self.assertRaises(ValueError):
                decode_fp32_checkpoint(blob.getvalue())

    def test_pickle_global_is_rejected_before_execution(self):
        class Evil:
            def __reduce__(self):
                import os
                return (os.system,("echo forbidden",))
        blob=io.BytesIO();torch.save({"arbitrary":Evil()},blob)
        with self.assertRaisesRegex(ValueError,"forbidden pickle global"):
            decode_fp32_checkpoint(blob.getvalue())

    def test_disallowed_dtype_and_spoofed_checkpoint_prefix_rejected(self):
        s=OrderedDict((name,torch.ones(shape,dtype=torch.float16)) for name,shape in SHAPES.items())
        blob=io.BytesIO();torch.save(s,blob)
        with self.assertRaises(ValueError):decode_fp32_checkpoint(blob.getvalue())
        with self.assertRaises(ValueError):decode_fp32_checkpoint(b'not torch')


class RealV6ArchiveOnlyWhenAvailable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.archive=os.environ.get('HEPTA_ORIGINAL_V6_ZIP')
        if not cls.archive:
            raise unittest.SkipTest('actual V6 archive not mounted (optional)')
        cls.result=audit_v6_archive(cls.archive)

    def test_true_original_v6_all_212_entries_and_12_checkpoint_tensors(self):
        self.assertEqual(sha_file(self.archive),V6_ZIP_SHA256)
        self.assertEqual(self.result['original_entries_verified'],211)
        self.assertEqual(self.result['checkpoint_count'],12)
        self.assertEqual(self.result['original_source_panel_verified'],128)
        self.assertEqual(self.result['original_natural_train_verified'],3909)
        self.assertTrue(all(x['parameter_count']==42562 for x in self.result['checkpoints']))
        self.assertTrue(all(x['independent_schedule_recomputed'] for x in self.result['plans']))
        self.assertFalse(self.result['new_v7_1_gradient_training_executed'])
        self.assertFalse(self.result['production_authorized'])

    def test_historical_replay_refuses_byte_edit(self):
        with tempfile.TemporaryDirectory() as d:
            new=Path(d)/'altered.zip'
            data=Path(self.archive).read_bytes()
            new.write_bytes(data[:-1] + bytes([data[-1]^1]))
            with self.assertRaisesRegex(ValueError,'SHA-pinned'):
                audit_v6_archive(new)


class FullNineTrainedTensorReview(CompleteReviewerTests):
    """Fixture setup deliberately inherited, but EVERY .pt is true Torch FP32."""
    def setUp(self):
        super().setUp()
        for seed in SEEDS:
            original=self.previous/f'seed-{seed}'/'bridge'
            old=weight_bytes(seed)
            old_check=decode_fp32_checkpoint(old)
            (original/'warmup.pt').write_bytes(old)
            base=json.loads((original/'warmup-model.json').read_text())
            base.update({k:old_check[k] for k in
                         ('training_parameter_sha256','execution_parameter_sha256','parameter_count')})
            base['file_sha256']=file_hash(original/'warmup.pt')
            write(original/'warmup-model.json',base)
            for offset,arm in enumerate(('joint','protect_old','protect_old_guarded')):
                folder=self.output/f'seed-{seed}'/arm
                weight=weight_bytes(seed*100+offset)
                decoded=decode_fp32_checkpoint(weight)
                (folder/'candidate.pt').write_bytes(weight)
                metadata=json.loads((folder/'candidate-model.json').read_text())
                metadata.update({k:decoded[k] for k in
                                 ('training_parameter_sha256','execution_parameter_sha256','parameter_count')})
                metadata['file_sha256']=file_hash(folder/'candidate.pt')
                metadata['initial_execution_parameter_sha256']=base['execution_parameter_sha256']
                receipt=json.loads((folder/'candidate-training.json').read_text())
                receipt['initial_model_sha256']=base['training_parameter_sha256']
                receipt['final_model_sha256']=decoded['training_parameter_sha256']
                write(folder/'candidate-training.json',receipt)
                metadata['training_receipt_sha256']=file_hash(folder/'candidate-training.json')
                write(folder/'candidate-model.json',metadata)
                attempt=json.loads((folder/'attempt.json').read_text())
                attempt['original_warmup_sha256']=file_hash(original/'warmup-model.json')
                write(folder/'attempt.json',attempt)
                completed=json.loads((self.output/'completed.json').read_text())
                completed['results'][f'{seed}/{arm}']['model_sha256']=decoded['training_parameter_sha256']
                write(self.output/'completed.json',completed)

    def test_real_cli_requires_immutable_pinned_v6_parent(self):
        # A compatible, fully rehashed synthetic parent must NEVER pass
        # real-run admission. The CLI exposes no synthetic override.
        with self.assertRaisesRegex(ValueError,'original V6 design/warmup SHA-pinned'):
            review_complete(self.output,self.previous)

    def test_nine_real_candidate_tensors_plus_ledger(self):
        result=review_complete(self.output,self.previous,_synthetic_test_only=True)
        self.assertTrue(result['trained_weight_numerical_replay_performed'])
        self.assertEqual(len(result['tensor_replay']['model_tensor_checkpoints']),9)
        self.assertFalse(result['production_authorized'])

    def test_rehashed_weight_tamper_still_rejects_actual_tensor_digest(self):
        folder=self.output/'seed-41'/'protect_old'
        altered=weight_bytes(9999)
        (folder/'candidate.pt').write_bytes(altered)
        model=json.loads((folder/'candidate-model.json').read_text())
        model['file_sha256']=file_hash(folder/'candidate.pt')
        write(folder/'candidate-model.json',model)
        with self.assertRaisesRegex(ValueError,'tensor content|Torch tensor'):
            review_complete(self.output,self.previous,_synthetic_test_only=True)

    def test_false_original_v6_parent_tensor_rejected(self):
        path=self.previous/'seed-47'/'bridge'/'warmup.pt'
        path.write_bytes(weight_bytes(9999))
        with self.assertRaisesRegex(ValueError,'warmup tensor'):
            review_complete(self.output,self.previous,_synthetic_test_only=True)

    def test_symlink_candidate_checkpoint_is_denied(self):
        src=self.output/'seed-41'/'joint'/'candidate.pt'
        copied=src.with_suffix('.saved')
        src.rename(copied)
        try:
            src.symlink_to(copied)
        except (OSError,NotImplementedError):
            self.skipTest('file symlinks unsupported by host')
        with self.assertRaisesRegex(ValueError,'symlink'):
            review_complete(self.output,self.previous,_synthetic_test_only=True)

    def test_symlink_original_warmup_is_denied(self):
        src=self.previous/'seed-41'/'bridge'/'warmup.pt'
        copied=src.with_suffix('.saved')
        src.rename(copied)
        try:
            src.symlink_to(copied)
        except (OSError,NotImplementedError):
            self.skipTest('file symlinks unsupported by host')
        with self.assertRaisesRegex(ValueError,'symlink'):
            review_complete(self.output,self.previous,_synthetic_test_only=True)

    def test_original_fixture_only_ledger_reviews_do_not_claim_tensors(self):
        from bridge_gradient_review import review
        result=review(self.output,self.previous)
        self.assertFalse(result['trained_weight_numerical_replay_performed'])


if __name__=='__main__':
    unittest.main()
