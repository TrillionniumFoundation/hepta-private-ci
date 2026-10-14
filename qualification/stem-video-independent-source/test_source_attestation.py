"""No-media source identity and exact bytes attestation, tamper and failure tests."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import source_attestation as a
from source_gate import SourceGateError


def blob(raw):
    return a.git_blob(raw)


def fixture():
    repo = 'publisher/open-video'
    revision = 'a' * 40
    tree_sha = 'b' * 40
    lic = b'Creative Commons CC0 1.0 Universal\nAll works dedicated.\n'
    readme = b'All original video assets are Creative Commons Zero CC0.\n'
    data = [bytes([j + 1]) * (3000 + j * 37) for j in range(6)]
    paths = [f'video/recording-{i}.mp4' for i in range(6)]
    sources = [{'path': path, 'git_blob_sha1': blob(raw), 'byte_count': len(raw),
                'split': ('train', 'train', 'calibration', 'calibration', 'holdout', 'holdout')[i],
                'group_id': f'camera-source-{i}'} for i, (path, raw) in enumerate(zip(paths, data))]
    plan = {'schema': 'hepta.independent-video-source-attestation.v1',
            'repository': repo, 'revision': revision,
            'prior_source_ids': a.prior_ids(),
            'license_path': 'LICENSE', 'license_git_blob_sha1': blob(lic),
            'readme_path': 'README.md', 'readme_git_blob_sha1': blob(readme),
            'sources': sources}
    objects = [('LICENSE', lic), ('README.md', readme)] + list(zip(paths, data))
    rows = [{'path': path, 'type': 'blob', 'mode': '100644',
             'sha': blob(raw), 'size': len(raw)} for path, raw in objects]
    prefix = f'https://api.github.com/repos/{repo}/git'
    raw_prefix = f'https://raw.githubusercontent.com/{repo}/{revision}/'
    responses = {
        f'{prefix}/commits/{revision}': a.canonical({'sha': revision, 'tree': {'sha': tree_sha}}),
        f'{prefix}/trees/{tree_sha}?recursive=1': a.canonical({'sha': tree_sha, 'truncated': False, 'tree': rows}),
    }
    for path, content in objects:
        responses[raw_prefix + path] = content

    def fetch(url, maximum):
        if url not in responses:
            raise AssertionError('unlisted URL: ' + url)
        raw = responses[url]
        if len(raw) > maximum:
            raise SourceGateError('oversized mocked response')
        return raw
    return plan, responses, fetch


class TestAttestation(unittest.TestCase):
    def setUp(self):
        self.plan, self.responses, self.fetch = fixture()

    def run_check(self, plan=None):
        return a.verify_attested_plan(self.plan if plan is None else plan,
                                      fetch=self.fetch, expected_prior_sha256=a.prior_pin())

    def assertRejected(self, *, plan=None, responses=None, reason=None):
        if responses is not None:
            self.responses.update(responses)
        with self.assertRaises(SourceGateError) as context:
            self.run_check(plan=plan)
        if reason:
            self.assertIn(reason, str(context.exception))

    def test_verified_video_bytes_and_license_stay_unpublished(self):
        result = self.run_check()
        self.assertTrue(result['publisher_original_bytes_verified'])
        self.assertEqual(result['publisher_declared_license'], 'CC0-1.0')
        self.assertEqual(result['legacy_and_exposed_cc0_prior_count'], 12)
        self.assertEqual(result['original_video_bytes_read'], sum(x['byte_count'] for x in self.plan['sources']))
        self.assertTrue(result['identity_preflight']['eligible_by_identity'])
        self.assertEqual(len(result['source_receipts']), 6)
        self.assertFalse(result['independent_model_quality_established'])
        self.assertFalse(result['production_accepted'])
        self.assertNotIn('recording-0.mp4', json.dumps(result['source_receipts'][0]['media_sha256']))
        self.assertEqual(result['source_receipts'][0]['source_id'], a.sha256(a.canonical([
            'publisher/open-video', 'a'*40, 'video/recording-0.mp4', self.plan['sources'][0]['git_blob_sha1']])))

    def test_old_source_id_construction_matches_research_code(self):
        self.assertEqual(len(a.prior_ids()), 12)
        self.assertEqual(a.prior_ids(), sorted(set(a.prior_ids())))
        self.assertEqual(a.prior_pin(), a.sha256(json.dumps(a.prior_ids(), separators=(',', ':')).encode()))

    def test_external_exposure_registry_matches_source_implementations(self):
        registry = json.loads(Path(__file__).with_name('EXPOSED_SOURCES.json').read_text())
        self.assertEqual(registry['source_count'], 12)
        self.assertEqual(registry['prior_source_ids'], a.prior_ids())
        self.assertEqual(registry['source_ids_sha256'], a.prior_pin())
        for row in registry['source_records']:
            if row['repository'] == 'ryukenzen/360action':
                self.assertEqual(row['source_id'], a.sha256(a.canonical([
                    row['revision'], Path(row['path']).name, row['git_blob_sha1']])))
            else:
                self.assertEqual(row['source_id'], a.sha256(a.canonical([
                    row['repository'], row['revision'], row['path'], row['git_blob_sha1']])))

    def test_external_pin_cannot_be_omitted_or_forged(self):
        with self.assertRaises(SourceGateError):
            a.verify_attested_plan(self.plan, fetch=self.fetch)
        with self.assertRaises(SourceGateError):
            a.verify_attested_plan(self.plan, fetch=self.fetch, expected_prior_sha256='0'*64)

    def test_old_10_only_missing_exposed_cc0_is_rejected(self):
        p = copy.deepcopy(self.plan)
        p['prior_source_ids'] = p['prior_source_ids'][:-2]
        self.assertRejected(plan=p, reason='full exposed-history')

    def test_exposed_original_cc0_source_rejected(self):
        from source_gate import verify
        original_path, original_blob = next(iter(a._EXPOSED_CC0.items()))
        old_id = a.sha256(a.canonical([a._EXPOSED_CC0_REPO, a._EXPOSED_CC0_REV,
                                       original_path, original_blob]))
        self.assertIn(old_id, a.prior_ids())
        candidate = {'schema': 'hepta.independent-video-source-gate.v1',
                     'prior_source_ids': a.prior_ids(),
                     'candidate_repository': a._EXPOSED_CC0_REPO,
                     'candidate_revision': a._EXPOSED_CC0_REV,
                     'candidate_sources': [
                         {'source_id': a.sha256(a.canonical(['new', i])),
                          'media_sha256': a.sha256(a.canonical(['bytes', i])),
                          'split': ['train','train','calibration','calibration','holdout','holdout'][i],
                          'group_id': str(i)} for i in range(6)]}
        candidate['candidate_sources'][0]['source_id'] = old_id
        with self.assertRaises(SourceGateError):
            verify(candidate, expected_prior_sha256=a.prior_pin())

    def test_exact_old_video_blob_cannot_be_rebranded_via_new_source_id(self):
        p = copy.deepcopy(self.plan)
        p['sources'][0]['git_blob_sha1'] = next(iter(a._OLD_360.values()))
        self.assertRejected(plan=p, reason='exposed original')

    def test_exact_exposed_cc0_blob_cannot_be_rebranded(self):
        p = copy.deepcopy(self.plan)
        p['sources'][0]['git_blob_sha1'] = next(iter(a._EXPOSED_CC0.values()))
        self.assertRejected(plan=p, reason='exposed original')

    def test_too_few_real_sources_not_eligible(self):
        p = copy.deepcopy(self.plan)
        p['sources'] = p['sources'][:2]
        self.assertRejected(plan=p, reason='at least six')

    def test_label_not_allowed_in_plan(self):
        p = copy.deepcopy(self.plan)
        p['sources'][0]['label'] = 1
        self.assertRejected(plan=p, reason='no-label')

    def test_predictive_fields_not_allowed_top_level(self):
        p = copy.deepcopy(self.plan)
        p['holdout_performance'] = 1.0
        self.assertRejected(plan=p, reason='exact attested')

    def test_wrong_tree_revision(self):
        p = copy.deepcopy(self.plan)
        p['revision'] = 'main'
        self.assertRejected(plan=p, reason='Git SHA-1')

    def test_truncated_tree_refused(self):
        tree_url = next(u for u in self.responses if '/trees/' in u)
        tree = a._decode(self.responses[tree_url])
        tree['truncated'] = True
        self.assertRejected(responses={tree_url: a.canonical(tree)}, reason='complete exact')

    def test_git_tree_size_drift_rejected_before_media_fetch(self):
        url = next(u for u in self.responses if '/trees/' in u)
        tree = a._decode(self.responses[url])
        tree['tree'][2]['size'] += 1
        self.assertRejected(responses={url: a.canonical(tree)}, reason='size drift')

    def test_wrong_git_tree_blob_rejected(self):
        url = next(u for u in self.responses if '/trees/' in u)
        tree = a._decode(self.responses[url])
        tree['tree'][4]['sha'] = 'c'*40
        self.assertRejected(responses={url: a.canonical(tree)}, reason='identity/size drift')

    def test_symlink_git_tree_rejected(self):
        url = next(u for u in self.responses if '/trees/' in u)
        tree = a._decode(self.responses[url])
        tree['tree'][2]['mode'] = '120000'
        self.assertRejected(responses={url: a.canonical(tree)}, reason='identity/size drift')

    def test_duplicate_git_tree_entry_rejected(self):
        url = next(u for u in self.responses if '/trees/' in u)
        tree = a._decode(self.responses[url]);tree['tree'].append(copy.deepcopy(tree['tree'][0]))
        self.assertRejected(responses={url: a.canonical(tree)}, reason='duplicate path')

    def test_license_not_present_in_exact_blob(self):
        url = next(u for u in self.responses if u.endswith('/LICENSE'))
        self.assertRejected(responses={url: b'pretend license'}, reason='license/attribution bytes')

    def test_declared_license_text_missing(self):
        p = copy.deepcopy(self.plan)
        text = b'Permission denied\n'
        p['license_git_blob_sha1'] = blob(text)
        url = next(u for u in self.responses if u.endswith('/LICENSE'))
        tree_url = next(u for u in self.responses if '/trees/' in u)
        tree = a._decode(self.responses[tree_url]); tree['tree'][0]['sha'] = blob(text);tree['tree'][0]['size']=len(text)
        self.assertRejected(plan=p, responses={url: text, tree_url: a.canonical(tree)}, reason='CC0 1.0')

    def test_readme_must_declare_cc0(self):
        p = copy.deepcopy(self.plan)
        text = b'Private source disclaimer\n'
        p['readme_git_blob_sha1'] = blob(text)
        url = next(u for u in self.responses if u.endswith('/README.md'))
        tree_url = next(u for u in self.responses if '/trees/' in u)
        tree = a._decode(self.responses[tree_url]); tree['tree'][1]['sha'] = blob(text);tree['tree'][1]['size']=len(text)
        self.assertRejected(plan=p, responses={url: text, tree_url: a.canonical(tree)}, reason='all-assets')

    def test_media_content_drift_cannot_claim_verified_bytes(self):
        url = next(u for u in self.responses if u.endswith('/recording-3.mp4'))
        text = self.responses[url];self.assertRejected(responses={url: b'X'+text[1:]}, reason='media bytes drift')

    def test_media_sha1_cannot_be_claimed_without_real_bytes(self):
        p = copy.deepcopy(self.plan)
        p['sources'][1]['git_blob_sha1'] = '0'*40
        self.assertRejected(plan=p, reason='identity/size drift')

    def test_duplicate_original_media_with_different_paths_rejected(self):
        p = copy.deepcopy(self.plan)
        left, right = p['sources'][0], p['sources'][1]
        right['git_blob_sha1'] = left['git_blob_sha1']
        right['byte_count'] = left['byte_count']
        rhs_url = next(u for u in self.responses if u.endswith('/recording-1.mp4'))
        lhs_url = next(u for u in self.responses if u.endswith('/recording-0.mp4'))
        tree_url = next(u for u in self.responses if '/trees/' in u)
        tree = a._decode(self.responses[tree_url]); tree['tree'][3]['sha']=left['git_blob_sha1'];tree['tree'][3]['size']=left['byte_count']
        self.assertRejected(plan=p, responses={rhs_url:self.responses[lhs_url],tree_url:a.canonical(tree)}, reason='duplicate')

    def test_same_family_split_overlap_rejected(self):
        p = copy.deepcopy(self.plan)
        p['sources'][5]['group_id'] = p['sources'][0]['group_id']
        self.assertRejected(plan=p, reason='source-family overlap')

    def test_malformed_relative_path_rejected_before_fetch(self):
        for invalid in ('../cross.mp4', '/abs.mp4', 'x//y.mp4', 'x\\evil.mp4', 'foo?secret.mp4'):
            with self.subTest(invalid=invalid):
                p = copy.deepcopy(self.plan);p['sources'][0]['path']=invalid
                self.assertRejected(plan=p)

    def test_bool_byte_count_rejected(self):
        p = copy.deepcopy(self.plan)
        p['sources'][0]['byte_count'] = True
        self.assertRejected(plan=p, reason='bounded')

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaises(SourceGateError):
            a._decode(b'{"sources":[],"sources":[]}')

    def test_nan_json_rejected(self):
        with self.assertRaises(SourceGateError):
            a._decode(b'{"bad":NaN}')

    def test_wrong_git_commit_sha_refused(self):
        url = next(u for u in self.responses if '/commits/' in u)
        self.assertRejected(responses={url:a.canonical({'sha':'f'*40,'tree':{'sha':'b'*40}})}, reason='commit drift')

    def test_attested_report_seals_only_after_success(self):
        # Fully offline command-line path, no source media in receipts, refuses overwrite.
        with tempfile.TemporaryDirectory() as d:
            plan_file = Path(d)/'plan.json'
            output = Path(d)/'receipt.json'
            plan_file.write_bytes(a.canonical(self.plan))
            args = ['prog', '--plan', str(plan_file), '--prior-sha256', a.prior_pin(), '--output', str(output)]
            with patch.object(a,'read_url',side_effect=self.fetch), patch('sys.argv', args):
                a.main()
            self.assertTrue(output.is_file())
            receipt = a._decode(output.read_bytes())
            self.assertFalse(receipt['production_accepted'])
            with patch.object(a,'read_url',side_effect=self.fetch), patch('sys.argv', args):
                with self.assertRaises(FileExistsError):a.main()

    def test_no_partial_receipt_on_network_failure(self):
        with tempfile.TemporaryDirectory() as d:
            plan_file=Path(d)/'plan.json';output=Path(d)/'out.json'
            plan_file.write_bytes(a.canonical(self.plan))
            def corrupted(url, maximum):
                if url.endswith('/recording-5.mp4'):
                    raise SourceGateError('network unavailable')
                return self.fetch(url,maximum)
            args=['prog','--plan',str(plan_file),'--prior-sha256',a.prior_pin(),'--output',str(output)]
            with patch.object(a,'read_url',side_effect=corrupted),patch('sys.argv',args):
                with self.assertRaises(SourceGateError):a.main()
            self.assertFalse(output.exists())

    def test_github_url_parser_refuses_arbitrary_url(self):
        with self.assertRaises(SourceGateError):
            a.read_url('https://example.com/repo',1000)


if __name__ == '__main__':
    unittest.main()
