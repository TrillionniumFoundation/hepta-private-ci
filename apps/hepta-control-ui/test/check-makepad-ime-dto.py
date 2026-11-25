from pathlib import Path
import subprocess,tempfile,os,json,hashlib
root=Path(__file__).resolve().parents[1]
platform=Path(os.environ.get('MAKEPAD_PLATFORM_ROOT',str(root/'rust/target/robrix-build/makepad-platform')))
text=(platform/'src/os/web/to_wasm.rs').read_text()
metadata=json.loads((root/'rust/robrix-ui/patches/makepad-wasm-ime.json').read_text())
assert hashlib.sha256(text.encode()).hexdigest()==next(file['afterSha256'] for file in metadata['files'] if file['path']=='src/os/web/to_wasm.rs')
a=text.index('pub struct ToWasmImeState {')
b=text.index('\n}\n',a)+3
c=text.index('impl From<ToWasmImeState> for TextInputEvent {',b)
level=0;end=None
for index in range(c,len(text)):
    if text[index]=='{':level+=1
    if text[index]=='}':
        level-=1
        if level==0:end=index+1;break
code='''#![allow(dead_code)]
mod event {
    use std::ops::Range;
    #[derive(Debug,Clone,Copy,PartialEq,Eq,PartialOrd,Ord)] pub struct CharOffset(pub usize);
    #[derive(Debug)] pub struct FullTextState {
        pub text:String,pub selection:Range<CharOffset>,pub composition:Option<Range<CharOffset>>,
    }
}
#[derive(Default)] struct TextInputEvent { was_paste:bool, full_state_sync:Option<event::FullTextState> }
'''+text[a:b]+text[c:end]+'''
fn state(text:Vec<u32>,start:u32,end:u32)->event::FullTextState {
    TextInputEvent::from(ToWasmImeState {text,selection_start:start,selection_end:end,
        selection_backward:false,has_composition:false,composition_start:0,
        composition_end:0,was_paste:false}).full_state_sync.unwrap()
}
#[test] fn non_bmp_roundtrip_and_offsets(){
    let text="A😀𠮷中";
    let result=state(text.chars().map(|c|c as u32).collect(),3,5);
    assert_eq!(result.text,text);assert_eq!(result.selection,event::CharOffset(2)..event::CharOffset(3));
}
#[test] fn invalid_scalars_and_out_of_range_offsets(){
    let result=state(vec![65,0xd800,0x110000,0x1f600],999,999);
    assert_eq!(result.text,"A��😀");assert_eq!(result.selection,event::CharOffset(4)..event::CharOffset(4));
}
#[test] fn split_surrogate_is_floored(){
    let result=state(vec![65,0x1f600,66],2,4);
    assert_eq!(result.selection,event::CharOffset(1)..event::CharOffset(3));
}
#[test] fn backward_selection_and_reversed_composition(){
    let result=TextInputEvent::from(ToWasmImeState {text:vec![65,0x1f600,66],
        selection_start:1,selection_end:3,selection_backward:true,has_composition:true,
        composition_start:3,composition_end:1,was_paste:false}).full_state_sync.unwrap();
    assert_eq!(result.selection,event::CharOffset(2)..event::CharOffset(1));
    assert_eq!(result.composition,Some(event::CharOffset(1)..event::CharOffset(2)));
}
#[test] fn empty_text_clamps(){
    let result=state(vec![],20,30);
    assert_eq!(result.text,"");assert_eq!(result.selection,event::CharOffset(0)..event::CharOffset(0));
}
'''
with tempfile.TemporaryDirectory(prefix='makepad-ime-dto-') as directory:
    path=Path(directory)/'dto.rs';path.write_text(code)
    binary=Path(directory)/'dto-tests'
    subprocess.run([os.environ.get('RUSTC','rustc'),'--edition=2021','--test',str(path),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
