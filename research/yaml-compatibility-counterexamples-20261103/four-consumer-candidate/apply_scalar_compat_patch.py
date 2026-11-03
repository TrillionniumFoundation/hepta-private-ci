#!/usr/bin/env python3
"""Opt-in scalar dispatch on the existing budgeted YAML traversal; no raw parser."""
from pathlib import Path
import argparse,difflib,hashlib,json,shutil
ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--legacy-source',type=Path,required=True);a=ap.parse_args()
shutil.copytree(a.base,a.output)
def replace(rel,old,new,count=1):
 p=a.output/rel;s=p.read_text();assert s.count(old)==count,(rel,s.count(old),old);p.write_text(s.replace(old,new))
options='src/de/options.rs';cfg='src/de/cfg.rs';des='src/de/deserializer.rs';live='src/de/live_events.rs'
replace(options,'    pub legacy_string_semantics: bool,\n','''    pub legacy_string_semantics: bool,
    /// Retain serde_yaml 0.9 scalar inference plus the typed bool and u32
    /// conversion rules needed by the compatibility consumers. Default: false.
    /// This does not change the scanner, aliases, budgets, or other typed targets.
    #[cfg_attr(feature = "serde_derived_types", serde(default))]
    pub legacy_serde_yaml_scalars: bool,
    /// Ignore tag/node-kind mismatch in the legacy compatibility traversal and
    /// accept empty documents as empty sequences or maps. Default: false.
    /// Actual target type checks and all event/depth/alias budgets still apply.
    #[cfg_attr(feature = "serde_derived_types", serde(default))]
    pub legacy_serde_yaml_node_tags: bool,
''')
replace(options,'            legacy_string_semantics: false,\n','            legacy_string_semantics: false,\n            legacy_serde_yaml_scalars: false,\n            legacy_serde_yaml_node_tags: false,\n')
replace(options,'            .field("legacy_string_semantics", &self.legacy_string_semantics)\n','            .field("legacy_string_semantics", &self.legacy_string_semantics)\n            .field("legacy_serde_yaml_scalars", &self.legacy_serde_yaml_scalars)\n            .field("legacy_serde_yaml_node_tags", &self.legacy_serde_yaml_node_tags)\n')
replace(cfg,'    pub(crate) legacy_string_semantics: bool,\n','    pub(crate) legacy_string_semantics: bool,\n    pub(crate) legacy_serde_yaml_scalars: bool,\n    pub(crate) legacy_serde_yaml_node_tags: bool,\n')
replace(cfg,'            legacy_string_semantics: options.legacy_string_semantics,\n','            legacy_string_semantics: options.legacy_string_semantics,\n            legacy_serde_yaml_scalars: options.legacy_serde_yaml_scalars,\n            legacy_serde_yaml_node_tags: options.legacy_serde_yaml_node_tags,\n')
replace(live,'    preserve_local_application_tags: bool,\n','    preserve_local_application_tags: bool,\n    legacy_serde_yaml_node_tags: bool,\n')
replace(live,'        let preserve_local_application_tags = options.preserve_local_application_tags;\n','        let preserve_local_application_tags = options.preserve_local_application_tags;\n        let legacy_serde_yaml_node_tags = options.legacy_serde_yaml_node_tags;\n',2)
replace(live,'            preserve_local_application_tags,\n','            preserve_local_application_tags,\n            legacy_serde_yaml_node_tags,\n',2)
replace(live,'        if tag_kind\n            .requires()','        if !self.legacy_serde_yaml_node_tags && tag_kind\n            .requires()')
replace('src/de/mod.rs','mod key_nodes;\n','mod key_nodes;\nmod legacy_scalars;\n')
# Use the existing effective decoded scalar and original resolved tag. Aliases,
# source locations, interpolation, depth and budget accounting remain upstream.
needle='    fn take_scalar_view(&mut self) -> Result<ScalarView<\'de>, Error> {\n'
helper='''    fn legacy_scalar<V: Visitor<'de>>(
        &mut self,
        target: super::legacy_scalars::Target,
        visitor: V,
    ) -> Result<V::Value, Error> {
        let raw_tag = match self.ev.peek()? {
            Some(Ev::Scalar { raw_tag, .. }) => raw_tag.as_deref().map(str::to_owned),
            Some(other) => return Err(Error::unexpected("scalar").with_location(other.location())),
            None => return Err(eof_with_loc(self.ev)),
        };
        let view = self.take_scalar_view()?;
        super::legacy_scalars::visit(view.effective, raw_tag.as_deref(), view.style, view.location, target, visitor)
    }

'''
replace(des,needle,helper+needle)
needle="    fn deserialize_any<V: Visitor<'de>>(mut self, visitor: V) -> Result<V::Value, Self::Error> {\n"
replace(des,needle,needle+'''        if self.cfg.legacy_serde_yaml_scalars && matches!(self.ev.peek()?, Some(Ev::Scalar { .. })) {
            return self.legacy_scalar(super::legacy_scalars::Target::Any, visitor);
        }
''')
for method,target in [('bool','Bool'),('u32','U32')]:
 needle="    fn deserialize_"+method+"<V: Visitor<'de>>(mut self, visitor: V) -> Result<V::Value, Self::Error> {\n"
 replace(des,needle,needle+'''        if self.cfg.legacy_serde_yaml_scalars {
            return self.legacy_scalar(super::legacy_scalars::Target::'''+target+''', visitor);
        }
''')
needle='''        if self.cfg.legacy_string_semantics {
            let view = self.take_scalar_view()?;
'''
replace(des,needle,'''        if self.cfg.legacy_string_semantics {
            if self.ev.peek()?.is_none() {
                return Err(eof_with_loc(self.ev));
            }
            let view = self.take_scalar_view()?;
''')
for method,access,empty in [('seq','SeqDeserializer','u8'),('map','MapDeserializer','(u8, u8)')]:
 needle="    fn deserialize_"+method+"<V: Visitor<'de>>(mut self, visitor: V) -> Result<V::Value, Self::Error> {\n"
 replace(des,needle,needle+'''        if self.cfg.legacy_serde_yaml_node_tags {
            let empty = match self.ev.peek()? {
                None => true,
                Some(Ev::Scalar { value, style, .. }) => value.is_empty() && matches!(style, ScalarStyle::Plain),
                Some(_) => false,
            };
            if empty {
                let _ = self.ev.next()?;
                return visitor.visit_'''+method+'''(serde_core::de::value::'''+access+'''::<_, Error>::new(std::iter::empty::<'''+empty+'''>()));
            }
        }
''')
legacy=a.legacy_source.read_text()
# These small pure numeric helpers are adapted from the pinned legacy parser;
# unlike that parser implementation, they contain no unsafe FFI or YAML scanner.
unsigned=legacy[legacy.index('fn parse_unsigned_int<T>('):legacy.index('fn parse_signed_int<T>(')]
negative=legacy[legacy.index('fn parse_negative_int<T>('):legacy.index('pub(crate) fn parse_f64(')]
floats=legacy[legacy.index('pub(crate) fn parse_f64('):legacy.index("pub(crate) fn visit_int<'de, V>(")]
module='''// Scalar-resolution helpers adapted from serde_yaml 0.9.34+deprecated src/de.rs.
// SPDX-License-Identifier: MIT OR Apache-2.0
// The scanner, alias replay and budget traversal remain serde-saphyr/granit-parser.
use std::borrow::Cow;
use std::num::ParseIntError;
use serde_core::de::Visitor;
use granit_parser::ScalarStyle;
use super::{Error, Location};
#[derive(Clone, Copy)]
pub(super) enum Target { Any, Bool, U32 }
fn boolean(s:&str)->Option<bool>{match s{"true"|"True"|"TRUE"=>Some(true),"false"|"False"|"FALSE"=>Some(false),_=>None}}
fn null(s:&str)->bool{matches!(s,"null"|"Null"|"NULL"|"~")}
fn string<'de,V:Visitor<'de>>(s:Cow<'de,str>,v:V)->Result<V::Value,Error>{match s{Cow::Borrowed(s)=>v.visit_borrowed_str(s),Cow::Owned(s)=>v.visit_string(s)}}
fn integer<'de,V:Visitor<'de>>(s:&str,v:V)->Result<Result<V::Value,Error>,V>{
 if let Some(n)=parse_unsigned_int(s,u64::from_str_radix){return Ok(v.visit_u64(n));}
 if let Some(n)=parse_negative_int(s,i64::from_str_radix){return Ok(v.visit_i64(n));}
 if let Some(n)=parse_unsigned_int(s,u128::from_str_radix){return Ok(v.visit_u128(n));}
 if let Some(n)=parse_negative_int(s,i128::from_str_radix){return Ok(v.visit_i128(n));}
 Err(v)
}
pub(super) fn visit<'de,V:Visitor<'de>>(s:Cow<'de,str>,tag:Option<&str>,style:ScalarStyle,location:Location,target:Target,v:V)->Result<V::Value,Error>{
 let error=|ty|Error::InvalidScalar{ty,location};
 match target {
  Target::Bool|Target::U32=>{
   let expected=match target{Target::Bool=>"tag:yaml.org,2002:bool",_=>"tag:yaml.org,2002:int"};
   if !(matches!(style,ScalarStyle::Plain)||(matches!(style,ScalarStyle::Literal)&&tag==Some(expected))){return Err(error("legacy scalar style"));}
   return match target {
    Target::Bool=>v.visit_bool(boolean(&s).ok_or_else(||error("boolean"))?),
    Target::U32=>v.visit_u64(parse_unsigned_int(&s,u64::from_str_radix).ok_or_else(||error("u32"))?),
    Target::Any=>unreachable!(),
   };
  }
  Target::Any=>{}
 }
 match tag {
  Some("tag:yaml.org,2002:bool")=>return v.visit_bool(boolean(&s).ok_or_else(||error("boolean"))?),
  Some("tag:yaml.org,2002:int")=>return integer(&s,v).unwrap_or_else(|_|Err(error("integer"))),
  Some("tag:yaml.org,2002:float")=>return v.visit_f64(parse_f64(&s).ok_or_else(||error("floating point"))?),
  Some("tag:yaml.org,2002:null")=>{if !null(&s){return Err(error("null"));}return v.visit_unit();}
  Some(tag) if !tag.starts_with('!')=>return string(s,v),
  _=>{}
 }
 if !matches!(style,ScalarStyle::Plain){return string(s,v);}
 if s.is_empty()||null(&s){return v.visit_unit();}
 if let Some(b)=boolean(&s){return v.visit_bool(b);}
 let v=match integer(&s,v){Ok(result)=>return result,Err(v)=>v};
 if !digits_but_not_number(&s){if let Some(n)=parse_f64(&s){return v.visit_f64(n);}}
 string(s,v)
}
'''+unsigned+negative+floats
(a.output/'src/de/legacy_scalars.rs').write_text(module)
changes=[];patch=[]
for p in sorted(a.output.rglob('*.rs')):
 q=a.base/p.relative_to(a.output);x=q.read_bytes() if q.exists() else b'';y=p.read_bytes()
 if x==y:continue
 rel=str(p.relative_to(a.output));changes.append({'path':rel,'before_sha256':hashlib.sha256(x).hexdigest() if q.exists() else None,'after_sha256':hashlib.sha256(y).hexdigest()})
 patch.extend(difflib.unified_diff(x.decode().splitlines(True),y.decode().splitlines(True),fromfile='a/'+rel if q.exists() else '/dev/null',tofile='b/'+rel))
(a.output.parent/'scalar-compat.patch').write_text(''.join(patch))
(a.output.parent/'SOURCE_CHANGES.json').write_text(json.dumps({'changes':changes,'legacy_helper_source':str(a.legacy_source),'legacy_helper_source_sha256':hashlib.sha256(a.legacy_source.read_bytes()).hexdigest(),'migration_accepted':False},indent=2)+'\n')
print(json.dumps({'changed_files':len(changes),'patch_bytes':len(''.join(patch).encode()),'helper_lines':len(module.splitlines())}))
