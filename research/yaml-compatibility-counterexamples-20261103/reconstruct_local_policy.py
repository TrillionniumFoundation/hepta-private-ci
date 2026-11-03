#!/usr/bin/env python3
"""Reconstruct the tested three-file policy diff from checksum-verified 2.1.0 inputs.
This recovery script was created after the execution environment reset. It does
not claim the former probe logs or rlib bytes survived, and does not run a parser.
"""
from pathlib import Path
import difflib,hashlib,json,shutil
ROOT=Path(__file__).resolve().parent
UPSTREAM=ROOT/'upstream'
SOURCE=ROOT/'patched'
BEFORE={'src/de/live_events.rs':'982d820f6fb25640c034b93384d36b40c0011d736da90b39ff51e93353016f35','src/de/options.rs':'08f561f903052111b2114e3f7739d37c036d049fae8348246d0513732e876c16','src/de/tags.rs':'e93aefa221a3ac91454095f62533ebfc73271ee01dcafc7ababfc6c468daca44'}
AFTER={'src/de/live_events.rs':'272f9cb9bf0b745fdbde2f11ba50561459090aa28431207ad6b3d4ac6b462fab','src/de/options.rs':'41e5d33bee2bea6ecae198403601e90f0428d248f1a53c5b94f5606ba5e5e6b3','src/de/tags.rs':'acb457cdea3baeb2a4f0c2487fbeafee9bd182ac45b1ff3b2f9bb7bb7f29125f'}
for relative,digest in BEFORE.items():
 p=UPSTREAM/relative;assert hashlib.sha256(p.read_bytes()).hexdigest()==digest
 target=SOURCE/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
def replace(relative,old,new,count=1):
 p=SOURCE/relative;text=p.read_text();assert text.count(old)==count,(p,old,text.count(old));p.write_text(text.replace(old,new))
options='src/de/options.rs'
replace(options,'    pub strict_booleans: bool,\n','''    pub strict_booleans: bool,
    /// Preserve resolved local application tags such as `!int` or `!include`
    /// without interpreting their names as aliases for built-in YAML types.
    /// Genuine global core tags such as `!!int` retain their existing behavior.
    /// The non-specific `!` tag is unchanged. Default: false.
    #[cfg_attr(feature = "serde_derived_types", serde(default))]
    pub preserve_local_application_tags: bool,
''')
replace(options,'            strict_booleans: false,\n','            strict_booleans: false,\n            preserve_local_application_tags: false,\n')
replace(options,'            .field("strict_booleans", &self.strict_booleans)\n','''            .field("strict_booleans", &self.strict_booleans)
            .field("preserve_local_application_tags", &self.preserve_local_application_tags)
''')
live='src/de/live_events.rs'
replace(live,'    angle_conversions: bool,\n','    angle_conversions: bool,\n    preserve_local_application_tags: bool,\n')
replace(live,'        let angle_conversions = options.angle_conversions;\n','        let angle_conversions = options.angle_conversions;\n        let preserve_local_application_tags = options.preserve_local_application_tags;\n',2)
replace(live,'            angle_conversions,\n','            angle_conversions,\n            preserve_local_application_tags,\n',2)
replace(live,'SfTag::from_optional_cow(&tag)','SfTag::from_optional_cow_with_local_policy(&tag, self.preserve_local_application_tags)',3)
replace('src/de/tags.rs','impl SfTag {\n','''impl SfTag {
    /// Classify resolved local application tags independently of core-like names.
    pub(crate) fn from_optional_cow_with_local_policy(
        tag: &Option<Cow<Tag>>,
        preserve_local_application_tags: bool,
    ) -> SfTag {
        if preserve_local_application_tags
            && tag.as_ref().is_some_and(|tag| {
                tag.suffix_in_namespace("!").is_some_and(|suffix| !suffix.is_empty())
            })
        {
            return SfTag::Other;
        }
        Self::from_optional_cow(tag)
    }

''')
patch=[];changes=[]
for relative in BEFORE:
 a=(UPSTREAM/relative).read_bytes();b=(SOURCE/relative).read_bytes()
 actual=hashlib.sha256(b).hexdigest();assert actual==AFTER[relative],(relative,actual)
 changes.append({'path':relative,'before_sha256':BEFORE[relative],'after_sha256':actual})
 patch.extend(difflib.unified_diff(a.decode().splitlines(True),b.decode().splitlines(True),fromfile='a/'+relative,tofile='b/'+relative))
patch=''.join(patch);assert len(patch.encode())==5633
(ROOT/'local-application-tags.patch').write_text(patch)
(ROOT/'PATCH_RECOVERY.json').write_text(json.dumps({'schema':'hash-verified-upstream-patch-recovery-v1','source':'official serde-saphyr 2.1.0 package','archive_sha256':'3f4dc2714fc5632417a6e979602d7044bad8f2880c63fc7217087180acec31b6','changes':changes,'after_hashes_match_pre_reset_tool_output':True,'patch_bytes':len(patch.encode()),'patch_sha256':hashlib.sha256(patch.encode()).hexdigest(),'compile_or_probe_rerun':False,'production_accepted':False},indent=2)+'\n')
print(json.dumps({'patch_bytes':len(patch.encode()),'patch_sha256':hashlib.sha256(patch.encode()).hexdigest(),'all_3_after_hashes_match_pre_reset':True}))
