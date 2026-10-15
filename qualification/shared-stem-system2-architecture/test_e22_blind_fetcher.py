"""Fail-closed original Actions ZIP acquisition; never network in local tests."""
from __future__ import annotations
from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import e22_artifact_fetch as f
from e22_e16_question_gate import E16_FOLDS
from e21_whole_question import E15_FOLDS, E15_SCORES


class ExactRemoteManifest(TestCase):
    def test_01_original_blind_inventory_contains_no_human_scored_archives(self):
        blind=f.inventory('blind')
        self.assertEqual(len(blind),8)
        self.assertTrue(all('SCORE' not in key and 'HISTORICAL' not in key for key,_,_ in blind))
        self.assertFalse({i[1] for i in blind}&{i[0] for i in E15_SCORES})
        with self.assertRaises(ValueError):f.inventory('blind',with_e9=True)

    def test_02_full_original_inventory_is_exact_and_unique(self):
        all_items=f.inventory('full')
        self.assertEqual(len(all_items),12)
        self.assertEqual({i[1] for i in all_items},
            {i[0] for i in E15_FOLDS} | {i[0] for i in E16_FOLDS} |
            {i[0] for i in E15_SCORES} | {11953241456,11952742279})
        self.assertEqual(len(f.inventory('full',with_e9=True)),14)

    def test_03_never_accept_unknown_stage_or_noncreate_cache(self):
        with self.assertRaises(ValueError):f.inventory('unknown')
        with TemporaryDirectory() as td:
            with self.assertRaises(ValueError):f.fetch(td,'blind',source_archive='/missing',token='fake')

    def test_04_blind_fetch_locally_replays_same_source_hash_and_exact_original_ZIPs(self):
        # Fake file transport returns the actual immutable ZIP bytes; no HTTP.
        archive=os.environ.get('HEPTA_E22_ARCHIVE')
        if not archive or not Path(archive).is_file():
            raise ValueError('genuine original E22 source ZIP required, no placeholder')
        held={i[0]:os.environ.get(f'HEPTA_E22_E15_FOLD_{j}') for j,i in enumerate(E15_FOLDS)}
        held.update({i[0]:os.environ.get(f'HEPTA_E22_E16_FOLD_{j}') for j,i in enumerate(E16_FOLDS)})
        if any(not name or not Path(name).is_file() for name in held.values()):
            raise ValueError('entire original paired source inventory required')
        requested=[]
        def fake_fetch(req,timeout):
            item=int(req.full_url.split('/')[-2]);requested.append(item)
            return BytesIO(Path(held[item]).read_bytes())
        with TemporaryDirectory() as td, patch.object(f,'urlopen',fake_fetch):
            out=Path(td)/'new';env=Path(td)/'env'
            actual=f.fetch(str(out),'blind',source_archive=archive,
                           github_env=str(env),token='test-only-not-real')
            self.assertEqual(len(requested),8)
            self.assertTrue(all(Path(actual[k]).is_file() for k,_,_ in f.inventory('blind')))
            self.assertNotIn('HEPTA_E22_E16_SCORE_SOURCE',actual)
            self.assertIn('HEPTA_E21_FOLD_0',actual)
            self.assertIn('HEPTA_E20_ORIGINAL_MULTIRC_ARCHIVE',actual)
            self.assertIn('HEPTA_E22_ARCHIVE=',env.read_text())

    def test_05_reject_mutated_server_bytes_even_if_new_archive_is_readable(self):
        archive=os.environ.get('HEPTA_E22_ARCHIVE')
        if not archive or not Path(archive).is_file():
            raise ValueError('genuine original source required')
        with TemporaryDirectory() as td, patch.object(f,'urlopen',lambda req,timeout:BytesIO(b'forged!')):
            with self.assertRaises(ValueError):f.fetch(str(Path(td)/'new'),'blind',
                source_archive=archive,token='test-only')
