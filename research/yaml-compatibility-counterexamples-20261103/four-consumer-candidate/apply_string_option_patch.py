#!/usr/bin/env python3
"""Bounded typed-string/Option compatibility policy on the existing event traversal."""
from pathlib import Path
import argparse,hashlib,json,difflib,shutil
ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
shutil.copytree(a.base,a.output)
def replace(rel,old,new,count=1):
 p=a.output/rel;s=p.read_text();assert s.count(old)==count,(rel,s.count(old),old);p.write_text(s.replace(old,new))
def replace_in_option(old,new):
 p=a.output/'src/de/deserializer.rs';s=p.read_text()
 begin=s.index("    fn deserialize_option<V:")
 end=s.index("    fn deserialize_unit<V:",begin)
 section=s[begin:end];assert section.count(old)==1
 p.write_text(s[:begin]+section.replace(old,new)+s[end:])

replace('src/de/options.rs','    pub preserve_local_application_tags: bool,\n','''    pub preserve_local_application_tags: bool,
    /// Retain serde_yaml 0.9 typed String and Option scalar handling.
    /// Strings preserve decoded text irrespective of scalar tags. Only untagged
    /// plain nulls and valid plain global !!null scalars become Option::None.
    /// Default: false. This does not claim complete YAML grammar compatibility.
    #[cfg_attr(feature = "serde_derived_types", serde(default))]
    pub legacy_string_semantics: bool,
''')
replace('src/de/options.rs','            preserve_local_application_tags: false,\n','            preserve_local_application_tags: false,\n            legacy_string_semantics: false,\n')
replace('src/de/options.rs','            .field("preserve_local_application_tags", &self.preserve_local_application_tags)\n','            .field("preserve_local_application_tags", &self.preserve_local_application_tags)\n            .field("legacy_string_semantics", &self.legacy_string_semantics)\n')
replace('src/de/cfg.rs','    pub(crate) no_schema: bool,\n','    pub(crate) no_schema: bool,\n    pub(crate) legacy_string_semantics: bool,\n')
replace('src/de/cfg.rs','            no_schema: options.no_schema,\n','            no_schema: options.no_schema,\n            legacy_string_semantics: options.legacy_string_semantics,\n')
needle="    fn deserialize_str<V: Visitor<'de>>(mut self, visitor: V) -> Result<V::Value, Self::Error> {\n"
replace('src/de/deserializer.rs',needle,needle+'''        if self.cfg.legacy_string_semantics {
            let view = self.take_scalar_view()?;
            return match view.effective {
                Cow::Borrowed(value) => visitor.visit_borrowed_str(value),
                Cow::Owned(value) => visitor.visit_string(value),
            };
        }
''')
needle="    fn deserialize_string<V: Visitor<'de>>(mut self, visitor: V) -> Result<V::Value, Self::Error> {\n"
replace('src/de/deserializer.rs',needle,needle+'''        if self.cfg.legacy_string_semantics {
            return self.deserialize_str(visitor);
        }
''')
needle='''        if let Some((value, tag, style, _location)) = self.peek_effective_scalar()?
            && scalar_is_null(&tag, &value, &style)
'''
replace_in_option(needle,'''        if self.cfg.legacy_string_semantics {
            let is_none = match self.ev.peek()? {
                None => true,
                Some(Ev::Scalar { value, raw_tag, style, location, .. })
                    if matches!(style, ScalarStyle::Plain) =>
                {
                    let explicit_null = matches!(value.as_ref(), "null" | "Null" | "NULL" | "~");
                    match raw_tag.as_deref() {
                        None => value.is_empty() || explicit_null,
                        Some("tag:yaml.org,2002:null") => {
                            if !explicit_null {
                                return Err(Error::InvalidScalar { ty: "null", location: *location });
                            }
                            true
                        }
                        Some(_) => false,
                    }
                }
                Some(_) => false,
            };
            return if is_none {
                let _ = self.ev.next()?;
                visitor.visit_none()
            } else {
                visitor.visit_some(self)
            };
        }

'''+needle)
changes=[];patch=[]
for p in sorted(a.output.rglob('*.rs')):
 q=a.base/p.relative_to(a.output);x=q.read_bytes();y=p.read_bytes()
 if x==y:continue
 rel=str(p.relative_to(a.output));changes.append({'path':rel,'before_sha256':hashlib.sha256(x).hexdigest(),'after_sha256':hashlib.sha256(y).hexdigest()})
 patch.extend(difflib.unified_diff(x.decode().splitlines(True),y.decode().splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
(a.output.parent/'string-option.patch').write_text(''.join(patch))
(a.output.parent/'SOURCE_CHANGES.json').write_text(json.dumps({'changes':changes,'migration_accepted':False},indent=2)+'\n')
print(json.dumps({'changed_files':len(changes),'patch_bytes':len(''.join(patch).encode())}))
