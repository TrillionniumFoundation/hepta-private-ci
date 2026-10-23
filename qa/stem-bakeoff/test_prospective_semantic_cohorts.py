"""P44 synthetic and adversarial source/replay tests; no model quality claim."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

# Real CI must use the existing P39 module. Standalone authoring tests use a
# separately provided local-only fixture module, never a runtime fallback.
import multimodal_cohorts

import prospective_semantic_cohorts as m


def fixture():
    classes={'cat':1,'dog':2,'horse':3,'cow':4}
    original={"images":[{"image_id":i,"flickr_url":f"prior-{i}",
          "image_sha256":m.sha(f"old-image-{i}".encode()),
          "decoded_rgb_sha256":m.sha(f"old-rgb-{i}".encode()),
          "dhash64":m.sha(f"old-dhash-{i}".encode())[:16]} for i in range(1,385)]}
    instances={"categories":[{"id":v,"name":k} for k,v in classes.items()],
               "annotations":[],"images":[]}
    captions={"annotations":[]}
    for j,(cat,catid) in enumerate(classes.items()):
        for i in range(120):
            image_id=10000+j*1000+i
            instances['images'].append({"id":image_id,"file_name":f"{image_id:012d}.jpg",
                                        "flickr_url":f"original-{image_id}","license":4,
                                        "width":48,"height":48})
            instances['annotations'].append({"image_id":image_id,"category_id":catid})
            captions['annotations'].append({"id":image_id+100_000,"image_id":image_id,
                "caption":f"human sourced caption {cat} image {i}"})
    return instances,original,captions


def prepared():
    instances,registry,captions=fixture()
    selection=m.choose_sources(instances,registry,captions)
    sources={}
    fingerprints={}
    for s, groups in selection['selection'].items():
        sources[s]={}
        for c, ims in groups.items():
            sources[s][c]=[]
            for im in ims:
                j=im['image_id']
                fp={"image_sha256":m.sha(f"image-{j}".encode()),
                    "image_bytes":90+j%53,
                    "decoded_rgb_sha256":m.sha(f"rgb-{j}".encode()),
                    "dhash64":m.sha(f"dh-{j}".encode())[:16]}
                fingerprints[im['file_name']]=fp
                sources[s][c].append({**im,**fp})
    sealed={"original_photos":sources,"total_photo_bytes":sum(p['image_bytes'] for g in sources.values() for v in g.values() for p in v),
            "original_photo_count":m.EXPECTED_PHOTOS,"acquired_from_official_bucket":True}
    rows=m.make_rows(sealed)
    identity={"instances_sha256":"d"*64,"captions_sha256":m.CAPTIONS_SHA256}
    manifest=m.manifest_of(selection,sealed,rows,identity['instances_sha256'],identity['captions_sha256'])
    return instances,registry,captions,selection,sealed,rows,manifest,fingerprints,identity


class ProspectiveSemanticCohortTests(unittest.TestCase):
    def test_balanced_genuine_source_and_category_family_splits(self):
        *_,sel,sealed,rows,manifest,fp,identity=prepared()
        sources=set()
        for split,(a,b,n) in m.PLAN.items():
            self.assertEqual(len(rows[split]),4*n)
            self.assertEqual(sum(x['label'] for x in rows[split]),2*n)
            self.assertEqual(set(x['query_category'] for x in rows[split]),{a,b})
            groups={}
            for x in rows[split]:
                groups.setdefault(x['pair_block_id'],[]).append(x)
                self.assertNotIn(x['image_id'],sources)
                self.assertEqual(x['label'],int(x['source_category']==x['query_category']))
                self.assertNotEqual(x['text'],sealed['original_photos'][split][x['source_category']][0].get('source_human_caption_text'))
            self.assertEqual(len(groups),n)
            for g in groups.values():
                self.assertEqual(len(g),4)
                self.assertEqual(set(x['label'] for x in g),{0,1})
            sources.update(x['image_id'] for x in rows[split])
        self.assertEqual(len(sources),m.EXPECTED_PHOTOS)
        self.assertFalse(manifest['new_blind_model_trial_executed'])
        self.assertFalse(manifest['independently_published_source_seal'])
        self.assertFalse(manifest['multimodal_quality_qualified'])
        self.assertEqual(manifest['authority'],'DENY_ALL')

    def test_missing_ontology_category_rejected(self):
        instances,registry,captions=fixture()
        instances['categories'].pop()
        with self.assertRaisesRegex(m.SemanticCohortError,'four declared'):
            m.choose_sources(instances,registry,captions)

    def test_prior_photo_id_and_flickr_entity_exclusion(self):
        instances,registry,captions=fixture()
        protected=registry['images'][0]
        instances['images'][0]['id']=protected['image_id']
        instances['annotations'][0]['image_id']=protected['image_id']
        captions['annotations'][0]['image_id']=protected['image_id']
        choice=m.choose_sources(instances,registry,captions)
        self.assertNotIn(protected['image_id'],[x['image_id'] for gs in choice['selection'].values() for im in gs.values() for x in im])

    def test_new_duplicate_and_cross_category_image_rejected(self):
        instances,registry,captions=fixture()
        instances['images'].append(dict(instances['images'][0]))
        with self.assertRaisesRegex(m.SemanticCohortError,'duplicate image'):
            m.choose_sources(instances,registry,captions)
        instances,registry,captions=fixture()
        first=instances['images'][0]['id']
        instances['annotations'].append({'image_id':first,'category_id':2})
        selection=m.choose_sources(instances,registry,captions)
        self.assertNotIn(first,[x['image_id'] for gs in selection['selection'].values() for im in gs.values() for x in im])

    def test_new_caption_not_model_input_and_mutations_change_selection(self):
        instances,registry,captions=fixture()
        first=m.choose_sources(instances,registry,captions)
        row=first['selection']['train']['cat'][0]
        self.assertIn('source_human_caption_sha256',row)
        self.assertIn('source_human_caption_text',row)
        for caption in captions['annotations']:
            if caption['id'] == row['source_human_caption_id']:
                caption['caption']='changed upstream caption'
                break
        second=m.choose_sources(instances,registry,captions)
        all_first=[x for gs in first['selection'].values() for ims in gs.values() for x in ims]
        all_second=[x for gs in second['selection'].values() for ims in gs.values() for x in ims]
        self.assertNotEqual(all_first,all_second)

    def test_boolean_identifiers_duplicate_json_and_nonfinite_rejected(self):
        self.assertFalse(m.positive_id(True))
        with self.assertRaisesRegex(m.SemanticCohortError,'duplicate JSON'):
            m.strict_json('{"label":1,"label":0}')
        with self.assertRaisesRegex(m.SemanticCohortError,'nonfinite JSON'):
            m.strict_json('{"n":NaN}')
        instances,registry,captions=fixture()
        instances['annotations'][0]['image_id']=True
        with self.assertRaisesRegex(m.SemanticCohortError,'image/category'):
            m.choose_sources(instances,registry,captions)

    def test_image_fingerprint_exact_and_near_duplicate_rejected(self):
        fp={"image_sha256":"a"*64,"decoded_rgb_sha256":"b"*64,
            "image_bytes":123,"dhash64":"abcdef0000000000"}
        self.assertTrue(m.fingerprint_check({},fp,[]))
        with self.assertRaisesRegex(m.SemanticCohortError,'near-duplicate'):
            m.fingerprint_check({},fp,[fp])
        near={**fp,"image_sha256":"c"*64,"decoded_rgb_sha256":"d"*64,
              "dhash64":"abcdef0000000001"}
        with self.assertRaisesRegex(m.SemanticCohortError,'near-duplicate'):
            m.fingerprint_check({},near,[fp])
        bad={**fp,"image_bytes":True}
        with self.assertRaisesRegex(m.SemanticCohortError,'photo hash or byte'):
            m.fingerprint_check({},bad,[])

    def test_external_archive_replay_rejects_corrupt_manifest_rows_and_source(self):
        instances,registry,captions,selection,sealed,rows,manifest,fps,identity=prepared()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'images').mkdir()
            def restore():
                (root/'source-seal.json').write_bytes(m.canonical({'selection':selection,'source':sealed,'manifest':manifest})+b'\n')
                (root/'manifest.json').write_bytes(m.canonical(manifest)+b'\n')
                for split,r in rows.items():
                    (root/(split+'.jsonl')).write_bytes(b''.join(m.canonical(x)+b'\n' for x in r))
            restore()
            receipt=(root/'source-seal.json').read_bytes()
            h=m.sha(receipt)
            with patch.object(m,'validate_original_archive',return_value=(identity,instances,registry,captions)):
                with patch.object(m,'image_fingerprint',side_effect=lambda path,record: fps[Path(path).name]):
                    got=m.audit('stub',root)
                    self.assertFalse(got['independent_prepublication_verified'])
                    self.assertEqual(got['status'],'SOURCE_REPLAY_VERIFIED')
                    self.assertTrue(m.audit('stub',root,h)['matches_supplied_seal_digest'])
                    with self.assertRaisesRegex(m.SemanticCohortError,'digest mismatched'):
                        m.audit('stub',root,'0'*64)
                    (root/'test.jsonl').write_bytes((root/'test.jsonl').read_bytes().replace(b'"label":1',b'"label":0',1))
                    with self.assertRaisesRegex(m.SemanticCohortError,'labels/questions'):
                        m.audit('stub',root)
                    restore()
                    (root/'manifest.json').write_bytes((root/'manifest.json').read_bytes().replace(b'"DENY_ALL"',b'"ALLOW_ALL"'))
                    with self.assertRaisesRegex(m.SemanticCohortError,'manifest'):
                        m.audit('stub',root)
                    restore()
                    damaged=dict(sealed)
                    damaged['total_photo_bytes']+=1
                    (root/'source-seal.json').write_bytes(m.canonical({'selection':selection,'source':damaged,'manifest':manifest})+b'\n')
                    with self.assertRaisesRegex(m.SemanticCohortError,'resource bytes'):
                        m.audit('stub',root)


if __name__=='__main__':unittest.main()
