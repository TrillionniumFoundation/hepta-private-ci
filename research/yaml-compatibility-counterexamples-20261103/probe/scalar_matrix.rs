#![allow(dead_code)]
mod safe_yaml;
use serde::de::DeserializeOwned;
use serde_json::json;
fn check<T:DeserializeOwned+std::fmt::Debug>(kind:&str,input:&str) {
 let old=serde_yaml::from_str::<T>(input).map(|x|format!("{x:?}")).map_err(|e|e.to_string());
 let new=safe_yaml::from_str::<T>(input).map(|x|format!("{x:?}")).map_err(|e|e.to_string());
 let equal=match (&old,&new) {(Ok(a),Ok(b))=>a==b,(Err(_),Err(_))=>true,_=>false};
 println!("{}",json!({"kind":kind,"input":input,"baseline":old,"candidate":new,"equal":equal}));
}
fn main(){
 let texts=["hello","true","tRuE","null","","007","1","1e999",".nan","aGVsbG8="];
 let tags=["","!custom ","!int ","!bool ","!null ","!str ","!!str ","!!int ","!!float ","!!bool ","!!null ","!!binary ","!<tag:example.org,2026:custom> "];
 for text in texts { for tag in tags { for style in 0..3 {
   let input=match style {0=>format!("{tag}{text}"),1=>format!("{tag}'{text}'"),_=>format!("{tag}|-\n  {text}\n")};
   check::<String>("String",&input);check::<Option<String>>("Option<String>",&input);
   check::<bool>("bool",&input);check::<u32>("u32",&input);
 }}}
 for input in ["!map [one]","!seq {one: two}","!!int [one]","!!str {one: two}","", "null", "!!seq [one]"]{
 check::<Vec<String>>("Vec<String>",input);check::<std::collections::BTreeMap<String,String>>("BTreeMap<String,String>",input);
 }
}
