"""Source-only anti-downgrade contracts for V26; not pretrained model acceptance."""
from __future__ import annotations

from pathlib import Path
import re
import unittest

WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/hepta-stem-v26-original-pixel-lesion.yml'


def validate(content: str) -> None:
    if not isinstance(content, str) or not content:
        raise ValueError('missing actual checked-out workflow')
    fixed = (
        'b8b2f10fe38506972301e77e3836729a90200673',
        '3ca8f55ed6b7143729258e4a1e53693614460950',
        'bd6d95ff957c3855b71a8778d7c13f61ff4d6a7a',
        'b99c99d8e13a4d1899a0597d7733753fb3ce092a',
        '733da82a4bbbde1b256dfd1dbe4c05832dcd4856',
        '11945106672',
        '7807b82d6c747b0b13666b330145e3801a8c8a0aadeee3f2ff7ab5f5c8c00a30',
        'a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202',
        'e8506bc65f96501b6b2fa4e4ae04c094c2b6b17b353de528a051136569e2849e',
        'b15cb81cbce3ff500ec58bb7da59c92801170bbce3b7995d689342505161f6d3',
        'research/stem-v26-physical-vision-lesions-20261016',
    )
    for token in fixed:
        if token not in content:
            raise ValueError('immutable dataset/model/workflow identity absent')
    for token in (
        'on:', 'pull_request:', 'push:', 'permissions:', 'contents: read', 'actions: read',
        'persist-credentials: false', 'source-only', 'if-no-files-found: error',
        'test_v26_original_pixel_lesion.SourceOnly',
        'test_v26_original_pixel_lesion',
        'v26_real_pixel_lesion.py', 'v26_original_pixel_review.py',
        'sealed-conditional-before-full-images.json',
        'sealed-interventions-before-labels.json',
        'original-model-venv',
        'v26-sanitized-review.json',
        'sha256sum -c -',
    ):
        if token not in content:
            # Older explanatory workflow uses different job names and venv label;
            # the *committed* V26 owner must maintain the current source contract.
            raise ValueError('missing strict physical / independent-review stage: '+token)
    if not re.search(r'(?m)^\s+if: github\.repository == .+&& github\.event_name == [\x27\x22]push[\x27\x22]',content):
        raise ValueError('pretrained-model job must not execute on ordinary PR checks')
    if not re.search(r'(?m)^\s+needs: source-only\s*$',content):
        raise ValueError('physical original cannot bypass source-only failure')
    if not re.search(r'(?m)^\s+path: \$\{\{ runner\.temp \}\}/v26-sanitized-review\.json\s*$',content):
        raise ValueError('media/label/raw prediction artifact exfiltration or missing report')
    for forbidden in ('continue-on-error:', '|| true', 'production_authorized: true',
                      'trust_remote_code=True', 'if-no-files-found: warn'):
        if forbidden in content:
            raise ValueError('fail-open or unsafe owner behavior')
    if content.count('actions/upload-artifact@') != 1:
        raise ValueError('exactly one sanitized upload is permitted')


class SourceOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding='utf-8')

    def test_current_source_present_and_valid(self):
        validate(self.workflow)

    def test_no_unpinned_legacy_loader(self):
        for x in ('b8b2f10fe38506972301e77e3836729a90200673',
                  '7807b82d6c747b0b13666b330145e3801a8c8a0aadeee3f2ff7ab5f5c8c00a30'):
            with self.subTest(x=x), self.assertRaises(ValueError):
                validate(self.workflow.replace(x, '0' * len(x)))

    def test_all_three_original_source_label_seals_mandatory(self):
        for x in ('a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202',
                  'e8506bc65f96501b6b2fa4e4ae04c094c2b6b17b353de528a051136569e2849e',
                  'b15cb81cbce3ff500ec58bb7da59c92801170bbce3b7995d689342505161f6d3'):
            with self.subTest(x=x),self.assertRaises(ValueError):
                validate(self.workflow.replace(x, '0'*64))

    def test_no_real_model_step_deletion(self):
        for x in ('v26_real_pixel_lesion.py','v26_original_pixel_review.py'):
            with self.subTest(x=x),self.assertRaises(ValueError):
                validate(self.workflow.replace(x,'deleted.py'))

    def test_pr_path_cannot_trigger_physical_original(self):
        with self.assertRaises(ValueError):
            validate(self.workflow.replace("github.event_name == 'push'", "github.event_name == 'pull_request'"))

    def test_private_raw_artifact_not_allowed(self):
        with self.assertRaises(ValueError):
            validate(self.workflow.replace('path: ${{ runner.temp }}/v26-sanitized-review.json',
                                           'path: ${{ runner.temp }}/v26-private'))

    def test_no_fail_open(self):
        for s in ('continue-on-error: true', '|| true', 'if-no-files-found: warn'):
            with self.subTest(s=s),self.assertRaises(ValueError):
                validate(self.workflow+'\n'+s+'\n')

    def test_lost_deny_or_missing_label_stage_is_not_success(self):
        for s in ('sha256sum -c -', 'sealed-interventions-before-labels.json'):
            with self.subTest(s=s),self.assertRaises(ValueError):
                validate(self.workflow.replace(s,'REMOVED'))


if __name__ == '__main__':
    unittest.main()
