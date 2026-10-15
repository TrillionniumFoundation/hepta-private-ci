"""Actual-safe-tensor numeric replay, only synthetic source/features; never authoritative."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import torch
from safetensors.torch import load_file,save_file

import e2_token_query_ablation as train
import e2_head_replay as replay
from test_e2_token_query_ablation import fixture

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        rows,bank=fixture()
        for row in rows:
            row['group_id']=f"public-group:{row['case_id']}"
        states={}
        learned=train.study(rows,bank,width=384,replay_head_states=states)
        cls.rows,cls.bank,cls.states=rows,bank,states
        cls.report={'head_study':learned,'feature_bank':learned['feature_bank']}
        cls.report_sha=hashlib.sha256(b'original separate E2 report').hexdigest()

    def folder(self):
        ctx=tempfile.TemporaryDirectory()
        root=Path(ctx.name)/'new'
        replay.write_bundle(root,self.rows,self.bank,self.states,self.report,self.report_sha)
        return ctx,root

    def test_real_safetensors_all_heads_frozen_learned_replayed(self):
        ctx,root=self.folder()
        with ctx:
            got=replay.review(root,self.rows,self.report,self.report_sha)
            self.assertEqual(got['heads_replayed'],6)
            self.assertEqual(got['predictions_replayed'],576)
            self.assertLess(got['max_probability_absolute_error'],1e-5)
            self.assertFalse(got['real_pretrained_execution_independently_verified'])
            self.assertFalse(got['production_promotion_permitted'])
            self.assertEqual(got['authority'],'DENY_ALL')

    def test_rekey_frozen_source_cannot_replay(self):
        ctx,root=self.folder()
        with ctx:
            changed=copy.deepcopy(self.rows)
            changed[0]['joint_input_digest']='0'*64
            with self.assertRaisesRegex(replay.Invalid,'original case'):
                replay.review(root,changed,self.report,self.report_sha)

    def test_forged_report_sha_denied(self):
        ctx,root=self.folder()
        with ctx:
            with self.assertRaisesRegex(replay.Invalid,'provenance'):
                replay.review(root,self.rows,self.report,'e'*64)

    def test_head_checkpoint_changed_and_rehashed_still_denied(self):
        ctx,root=self.folder()
        with ctx:
            file=root/'heads.safetensors'
            weights=load_file(str(file),device='cpu')
            weights['token_query.learned.query'][0]+=.25
            save_file(weights,str(file))
            manifest=json.loads((root/'manifest.json').read_text())
            manifest['files_sha256']['heads.safetensors']=hashlib.sha256(file.read_bytes()).hexdigest()
            (root/'manifest.json').write_bytes(replay._canonical(manifest))
            with self.assertRaisesRegex(replay.Invalid,'serialized Head tensors'):
                replay.review(root,self.rows,self.report,self.report_sha)

    def test_original_report_probability_changed_denied(self):
        ctx,root=self.folder()
        with ctx:
            corrupt=copy.deepcopy(self.report)
            corrupt['head_study']['arms']['token_query']['predictions'][0]['positive_probability']+=.05
            with self.assertRaisesRegex(replay.Invalid,'independent probability replay'):
                replay.review(root,self.rows,corrupt,self.report_sha)

    def test_duplicate_or_missing_original_source_denied(self):
        ctx,root=self.folder()
        with ctx:
            altered=copy.deepcopy(self.rows)
            altered[1]['case_id']=altered[0]['case_id']
            with self.assertRaises(replay.Invalid):
                replay.review(root,altered,self.report,self.report_sha)

    def test_rehashed_feature_mutation_still_rejected(self):
        ctx,root=self.folder()
        with ctx:
            part=root/'features.safetensors'
            payload=load_file(str(part),device='cpu')
            payload['pooled'][0,0]+=1.0/256
            save_file(payload,str(part))
            manifest=json.loads((root/'manifest.json').read_text())
            manifest['files_sha256']['features.safetensors']=hashlib.sha256(part.read_bytes()).hexdigest()
            (root/'manifest.json').write_bytes(replay._canonical(manifest))
            with self.assertRaisesRegex(replay.Invalid,'canonical Q24 frozen bank|producer frozen feature'):
                replay.review(root,self.rows,self.report,self.report_sha)

    def test_rehashed_missing_head_is_rejected(self):
        ctx,root=self.folder()
        with ctx:
            path=root/'heads.safetensors'
            payload=load_file(str(path),device='cpu')
            del payload['token_query.learned.query']
            save_file(payload,str(path))
            manifest=json.loads((root/'manifest.json').read_text())
            manifest['files_sha256']['heads.safetensors']=hashlib.sha256(path.read_bytes()).hexdigest()
            (root/'manifest.json').write_bytes(replay._canonical(manifest))
            with self.assertRaisesRegex(replay.Invalid,'missing or injected'):
                replay.review(root,self.rows,self.report,self.report_sha)

    def test_768_head_full_state_replay(self):
        rows,bank=fixture(768)
        for row in rows:
            row['group_id']=f"group:{row['case_id']}"
        states={}
        learned=train.study(rows,bank,width=768,replay_head_states=states)
        report={'head_study':learned,'feature_bank':learned['feature_bank']}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'modernbert-like'
            replay.write_bundle(root,rows,bank,states,report,self.report_sha)
            out=replay.review(root,rows,report,self.report_sha)
            self.assertEqual(out['predictions_replayed'],576)
            self.assertEqual(out['heads_replayed'],6)

    def test_symlinked_sidecar_rejected_without_following(self):
        ctx,root=self.folder()
        with ctx:
            for name in ('features.safetensors','heads.safetensors','case-identity.json'):
                file=root/name
                moved=root/(name+'.saved')
                file.rename(moved)
                file.symlink_to(moved)
                with self.assertRaisesRegex(replay.Invalid,'linked or unreadable'):
                    replay.review(root,self.rows,self.report,self.report_sha)
                file.unlink()
                moved.rename(file)

    def test_path_replacement_after_read_uses_verified_original_bytes(self):
        ctx,root=self.folder()
        with ctx:
            original=replay._checked
            changed=[]
            def replace_after_snapshot(path,limit):
                raw=original(path,limit)
                if path.name=='features.safetensors' and not changed:
                    # After the exact inode's bytes were checked and copied,
                    # replace the mutable on-disk name. The independent
                    # computation must use the pinned original bytes.
                    changed.append(True)
                    path.write_bytes(b'corrupted after bounded verified read')
                return raw
            with patch.object(replay,'_checked',side_effect=replace_after_snapshot):
                result=replay.review(root,self.rows,self.report,self.report_sha)
            self.assertTrue(changed)
            self.assertEqual(result['predictions_replayed'],576)
            with self.assertRaisesRegex(replay.Invalid,'changed replay'):
                replay.review(root,self.rows,self.report,self.report_sha)

    def test_corrupted_but_rehashed_safetensors_rejected_as_invalid(self):
        ctx,root=self.folder()
        with ctx:
            path=root/'heads.safetensors'
            path.write_bytes(b'corrupted-but-rehashed-unsafe-blob')
            manifest=json.loads((root/'manifest.json').read_text())
            manifest['files_sha256']['heads.safetensors']=hashlib.sha256(path.read_bytes()).hexdigest()
            (root/'manifest.json').write_bytes(replay._canonical(manifest))
            with self.assertRaisesRegex(replay.Invalid,'invalid verified safe tensor payload'):
                replay.review(root,self.rows,self.report,self.report_sha)

    def test_nonregular_or_oversized_descriptor_rejected(self):
        ctx,root=self.folder()
        with ctx:
            with self.assertRaisesRegex(replay.Invalid,'nonregular'):
                replay._checked(root,512)
            with self.assertRaisesRegex(replay.Invalid,'excessive'):
                replay._checked(root/'features.safetensors',16)

    def test_create_only(self):
        ctx,root=self.folder()
        with ctx:
            with self.assertRaises(FileExistsError):
                replay.write_bundle(root,self.rows,self.bank,self.states,self.report,self.report_sha)

if __name__=='__main__': unittest.main()
