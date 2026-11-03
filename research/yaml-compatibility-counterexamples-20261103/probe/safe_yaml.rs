// RECONSTRUCTED_NOT_RERUN after the 2026-11-03 execution environment reset.
// This intentionally retains the incomplete compatibility wrapper under review.
use std::fmt;
use serde::{Deserialize,Deserializer};
use serde::de::{MapAccess,SeqAccess,Visitor};
pub use serde_saphyr::Error;
pub fn from_str<'de,T:Deserialize<'de>>(input:&'de str)->Result<T,Error>{
 serde_saphyr::from_str_with_options(input,options())
}
pub fn from_slice<'de,T:Deserialize<'de>>(input:&'de [u8])->Result<T,Error>{
 serde_saphyr::from_slice_with_options(input,options())
}
fn options()->serde_saphyr::Options {
 #[allow(unused_mut)]
 let mut options=serde_saphyr::options!{
  merge_keys:serde_saphyr::MergeKeyPolicy::AsOrdinary,
  strict_booleans:true,
  duplicate_keys:serde_saphyr::DuplicateKeyPolicy::PassThrough,
  leading_zero_numbers_as_strings:true,
  underscored_numbers_as_strings:true,
  ignore_binary_tag_for_string:true,
  reject_non_finite_typeless_float:false,
 };
 #[cfg(local_tag_policy)] {options.preserve_local_application_tags=true;}
 options
}
#[derive(Debug)]
pub enum Value{Null,Bool(bool),Number(String),String(String),Sequence(Vec<Value>),Mapping(Vec<(Value,Value)>),Tagged(Box<TaggedValue>)}
#[derive(Debug)]
pub struct TaggedValue{pub tag:String,pub value:Value}
impl Value{
 pub fn as_str(&self)->Option<&str>{match self{Self::String(s)=>Some(s),_=>None}}
 pub fn as_mapping(&self)->Option<&Vec<(Self,Self)>>{match self{Self::Mapping(v)=>Some(v),_=>None}}
}
impl<'de> Deserialize<'de> for Value{
 fn deserialize<D:Deserializer<'de>>(deserializer:D)->Result<Self,D::Error>{
  let serde_saphyr::Tagged(RawValue(value),tag)=serde_saphyr::Tagged::<RawValue>::deserialize(deserializer)?;
  match tag{Some(tag) if !is_core_tag(&tag)=>Ok(Self::Tagged(Box::new(TaggedValue{tag,value}))),_=>Ok(value)}
 }
}
fn is_core_tag(tag:&str)->bool{matches!(tag,"tag:yaml.org,2002:null"|"tag:yaml.org,2002:bool"|"tag:yaml.org,2002:int"|"tag:yaml.org,2002:float"|"tag:yaml.org,2002:str"|"tag:yaml.org,2002:seq"|"tag:yaml.org,2002:map")}
struct RawValue(Value);
impl<'de> Deserialize<'de> for RawValue{
 fn deserialize<D:Deserializer<'de>>(deserializer:D)->Result<Self,D::Error>{deserializer.deserialize_any(ValueVisitor).map(Self)}
}
struct ValueVisitor;
impl<'de> Visitor<'de> for ValueVisitor{
 type Value=Value;
 fn expecting(&self,f:&mut fmt::Formatter<'_>)->fmt::Result{f.write_str("a YAML value")}
 fn visit_unit<E:serde::de::Error>(self)->Result<Value,E>{Ok(Value::Null)}
 fn visit_none<E:serde::de::Error>(self)->Result<Value,E>{Ok(Value::Null)}
 fn visit_bool<E:serde::de::Error>(self,v:bool)->Result<Value,E>{Ok(Value::Bool(v))}
 fn visit_i64<E:serde::de::Error>(self,v:i64)->Result<Value,E>{Ok(Value::Number(v.to_string()))}
 fn visit_u64<E:serde::de::Error>(self,v:u64)->Result<Value,E>{Ok(Value::Number(v.to_string()))}
 fn visit_f64<E:serde::de::Error>(self,v:f64)->Result<Value,E>{
  let number=if v.is_nan(){".nan".to_owned()}else if v.is_infinite(){if v.is_sign_negative(){"-.inf"}else{".inf"}.to_owned()}else{ryu::Buffer::new().format_finite(v).to_owned()};Ok(Value::Number(number))
 }
 fn visit_str<E:serde::de::Error>(self,v:&str)->Result<Value,E>{Ok(Value::String(v.to_owned()))}
 fn visit_string<E:serde::de::Error>(self,v:String)->Result<Value,E>{Ok(Value::String(v))}
 fn visit_seq<A:SeqAccess<'de>>(self,mut a:A)->Result<Value,A::Error>{let mut v=Vec::new();while let Some(x)=a.next_element()?{v.push(x);}Ok(Value::Sequence(v))}
 fn visit_map<A:MapAccess<'de>>(self,mut a:A)->Result<Value,A::Error>{let mut v=Vec::new();while let Some(x)=a.next_entry()?{v.push(x);}Ok(Value::Mapping(v))}
}
