#![allow(dead_code)]
mod safe_yaml;
use std::path::PathBuf;
use serde::{Deserialize,Serialize};
use serde::de::DeserializeOwned;
use serde_json::json;
#[derive(Debug, Default, Deserialize)]
pub(crate) struct SkillMetadataFile {
    #[serde(default)]
    interface: Option<SkillInterfaceFile>,
    #[serde(default)]
    pub(crate) dependencies: Option<Dependencies>,
    #[serde(default)]
    pub(crate) policy: Option<Policy>,
}


#[derive(Debug, Default, Deserialize)]
pub(crate) struct Dependencies {
    #[serde(default)]
    tools: Vec<DependencyTool>,
}

#[derive(Debug, Deserialize)]
pub(crate) struct Policy {
    #[serde(default)]
    allow_implicit_invocation: Option<bool>,
    #[serde(default)]
    products: Vec<Product>,
}

#[derive(Debug, Default, Deserialize)]
struct DependencyTool {
    #[serde(rename = "type")]
    kind: Option<String>,
    value: Option<String>,
    description: Option<String>,
    transport: Option<String>,
    command: Option<String>,
    url: Option<String>,
    oauth: Option<DependencyOAuth>,
}

#[derive(Debug, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DependencyOAuth {
    #[serde(alias = "callback_port")]
    callback_port: Option<u16>,
}


#[derive(Debug, Default, Deserialize)]
pub struct SkillInterfaceFile {
    display_name: Option<String>,
    short_description: Option<String>,
    icon_small: Option<PathBuf>,
    icon_large: Option<PathBuf>,
    brand_color: Option<String>,
    default_prompt: Option<String>,
}


#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Product {
    #[serde(alias = "CHATGPT")]
    Chatgpt,
    #[serde(alias = "CODEX")]
    Codex,
    #[serde(alias = "ATLAS")]
    Atlas,
}
fn observe<T: DeserializeOwned + std::fmt::Debug>(kind:&str,input:&str,counts:&mut [usize;2]) {
 let old=serde_yaml::from_str::<T>(input).map(|v|format!("{v:?}")).map_err(|e|e.to_string());
 let new=safe_yaml::from_str::<T>(input).map(|v|format!("{v:?}")).map_err(|e|e.to_string());
 let equal=match(&old,&new){(Ok(a),Ok(b))=>a==b,(Err(_),Err(_))=>true,_=>false};counts[0]+=1;counts[1]+=usize::from(!equal);
 println!("{}",json!({"kind":kind,"input":input,"baseline":old,"candidate":new,"equal":equal}));
}
fn main(){
 let mut counts=[0,0];
 let tags=["","!custom ","!int ","!str ","!bool ","!null ","!codex ","!CODEX ","!!int ","!!str ","!!bool ","!!float ","!!null ","!!map ","!!seq ","!<tag:example.org,2026:unknown> ","! "];
 for raw in ["","null","~","true","false","yes","0","-0","+0","007","0x10","0o77","0b11","65535","65536","-1","1.0","1e3","1_000","18446744073709551616",".nan","hello"]{
  for tag in tags{for style in 0..5{
   let input=match style{0=>format!("{tag}{raw}"),1=>format!("{tag}'{raw}'"),2=>format!("{tag}\"{raw}\""),3=>format!("{tag}|-\n  {raw}\n"),_=>format!("{tag}|\n  {raw}\n")};
   observe::<Option<u16>>("Option<u16>",&input,&mut counts);
  }}
 }
 for raw in ["","codex","CODEX","chatgpt","CHATGPT","atlas","ATLAS","Codex","bad","null","true","1"]{
  for tag in tags{for style in 0..5{
   let input=match style{0=>format!("{tag}{raw}"),1=>format!("{tag}'{raw}'"),2=>format!("{tag}\"{raw}\""),3=>format!("{tag}|-\n  {raw}\n"),_=>format!("{tag}|\n  {raw}\n")};
   observe::<Product>("Product",&input,&mut counts);
  }}
 }
 for input in ["{codex: null}","{CODEX: null}","!codex [x]","!codex {}","!codex true","!codex null","!codex ~","!codex ''","[codex]","!!str {codex: null}"]{observe::<Product>("Product_shape",input,&mut counts);}
 for input in [
  "{}", "interface: {}", "interface: {display_name: null, icon_small: !str 007}",
  "dependencies: {tools: [{type: mcp, oauth: {callbackPort: 007}}]}",
  "dependencies: {tools: [{oauth: {callback_port: 65535}}]}",
  "dependencies: {tools: [{oauth: {callbackPort: 65536}}]}",
  "dependencies: {tools: [{oauth: {callbackPort: !!int '7'}}]}",
  "policy: {allow_implicit_invocation: true, products: [codex, CHATGPT, atlas]}",
  "policy: {allow_implicit_invocation: !bool true, products: [!codex null]}",
  "policy: {products: [{codex: null}]}", "policy: {products: [!str codex]}",
  "interface: {icon_small: 42, icon_large: false}",
  "unknown: !custom {nested: [1,2,3]}", "unknown: &a {x: x}\nother: *a",
  "policy: {allow_implicit_invocation: null}", "policy: {allow_implicit_invocation: 'true'}",
  "policy: {products: [codex], products: [atlas]}", "interface: {display_name: first, display_name: second}",
 ]{observe::<SkillMetadataFile>("actual_extension_metadata",input,&mut counts);}
 eprintln!("{}",json!({"observations":counts[0],"differences":counts[1],"migration_accepted":false}));if counts[1]>0{std::process::exit(1);}
}
