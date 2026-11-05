import {test,after} from 'node:test';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import {readFile,writeFile,mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';

const root=new URL('../',import.meta.url);
const platform=process.env.MAKEPAD_PLATFORM_ROOT ? pathToFileURL(process.env.MAKEPAD_PLATFORM_ROOT.replace(/\/$/,'')+'/') : new URL('rust/target/robrix-build/makepad-platform/',root);
const source=await readFile(new URL('src/os/web/web.js',platform),'utf8');
const metadata=JSON.parse(await readFile(new URL('rust/robrix-ui/patches/makepad-wasm-ime.json',root),'utf8'));
assert.equal(createHash('sha256').update(source).digest('hex'),metadata.files.find(file=>file.path==='src/os/web/web.js').afterSha256);
const start=source.indexOf('// BEGIN MAKEPAD WEB IME BRIDGE');
const end=source.indexOf('// END MAKEPAD WEB IME BRIDGE')+'// END MAKEPAD WEB IME BRIDGE'.length;
assert(start>=0&&end>start);
const directory=await mkdtemp(join(tmpdir(),'makepad-ime-test-'));
const modulePath=join(directory,'actual-platform-ime.mjs');
await writeFile(modulePath,source.slice(start,end));
const {MakepadWebIme,makepad_ime_codepoints,makepad_ime_string,makepad_ime_offset,MAKEPAD_WEB_IME_MAX_UNITS}=await import(pathToFileURL(modulePath));
after(()=>rm(directory,{recursive:true,force:true}));

function textarea(){
 let value='';
 return {
  writes:0,selectionStart:0,selectionEnd:0,selectionDirection:'none',readOnly:false,
  get value(){return value;},
  set value(next){value=next;this.writes++;this.selectionStart=this.selectionEnd=next.length;},
  setSelectionRange(start,end,direction='none'){
   this.selectionStart=start;this.selectionEnd=end;this.selectionDirection=direction;
  },
 };
}
function fixture(text='',start=text.length,end=start){
 const ta=textarea(), packets=[], events=[], queue=[];
 let dirty=false;
 let model={text,selection_start:start,selection_end:end,has_composition:false,composition_start:0,composition_end:0};
 const host={webgl_context_lost:false,text_copy_response:'',to_wasm:{
  ToWasmImeState(state){packets.push({...state});queue.push(['state',{...state}]);},
  ToWasmImeRequestState(){events.push('flush');queue.push(['flush']);},
  ToWasmTextCopy(){queue.push(['copy']);},
  ToWasmTextCut(){queue.push(['cut']);},
 },do_wasm_pump(){
  while(queue.length){
   const [kind,state]=queue.shift();
   if(kind==='state'){model={...state,text:makepad_ime_string(state.text)};events.push('state');}
   if(kind==='copy'||kind==='cut'){
    const start=Math.min(model.selection_start,model.selection_end),end=Math.max(model.selection_start,model.selection_end);
    host.text_copy_response=model.text.slice(start,end);
    if(kind==='cut'){
     model={...model,text:model.text.slice(0,start)+model.text.slice(end),selection_start:start,selection_end:start,selection_backward:false};
     dirty=true;
    }
   }
   if(kind==='flush'&&dirty){ime.sync({...model,text:makepad_ime_codepoints(model.text)});dirty=false;}
  }
 }};
 const ime=new MakepadWebIme(host,ta);
 ime.sync({...model,text:makepad_ime_codepoints(model.text)});ime.show();
 return {ime,ta,host,packets,events,get model(){return model;},
  ownerEdit(next){model={...model,...next};dirty=true;},
  nativeInput(next,a=next.length,b=a,type='insertText',data=null){
   ta.value=next;ta.setSelectionRange(a,b);ime.input({inputType:type,data,isComposing:false});
  },
 };
}
function clipboard(data=''){
 const writes=[];
 return {prevented:false,writes,preventDefault(){this.prevented=true;},clipboardData:{
  setData(type,value){writes.push([type,value]);},getData(type){assert.equal(type,'text/plain');return data;},
 }};
}

test('Rust sync mirrors full text and UTF-16 selection without an echo',()=>{
 const f=fixture('A😀B',1,3);
 assert.equal(f.ta.value,'A😀B');assert.equal(f.ta.selectionStart,1);assert.equal(f.ta.selectionEnd,3);
 f.ime.select();assert.equal(f.packets.length,0);
 const writes=f.ta.writes;f.ime.sync({...f.model,text:makepad_ime_codepoints(f.model.text)});assert.equal(f.ta.writes,writes);
});
test('ordinary multi-codepoint input is sent intact and emoji selection replaces exactly',()=>{
 const f=fixture('A😀B',1,3);
 f.nativeInput('A你好🧭B',6,6,'insertText','你好🧭');
 assert.equal(f.model.text,'A你好🧭B');assert.equal(f.model.selection_start,6);
 assert.equal(f.model.has_composition,false);
});
test('IME preview, commit and both duplicate end/input orders are idempotent',()=>{
 const f=fixture('say ',4);
 f.ime.start();f.ime.update('n');f.ime.update('你');
 assert.equal(f.model.text,'say 你');assert.equal(f.model.has_composition,true);
 assert.equal(f.model.composition_start,4);assert.equal(f.model.composition_end,5);
 f.ta.value='say 你';f.ta.setSelectionRange(5,5);
 f.ime.input({inputType:'insertCompositionText',data:'你',isComposing:true});
 f.ime.end('你');
 assert.equal(f.model.text,'say 你');assert.equal(f.model.has_composition,false);
 const count=f.packets.length;
 f.ime.end('你');f.ime.input({inputType:'insertFromComposition',data:'你',isComposing:false});
 f.ime.input({inputType:'insertText',data:'你',isComposing:false});
 assert.equal(f.packets.length,count);assert.equal(f.model.text,'say 你');
});
test('a subsequent identical composition is a new edit, never text-based deduplication',()=>{
 const f=fixture();
 for(let i=0;i<2;i++){f.ime.start();f.ime.update('你');f.ime.end('你');}
 assert.equal(f.model.text,'你你');assert.equal(f.model.has_composition,false);
});
test('empty compositionend cancels the preview without leaving a marked range',()=>{
 const f=fixture('before after',7);
 f.ime.start();f.ime.update('未提交');f.ime.end('');
 assert.equal(f.model.text,'before after');assert.equal(f.model.has_composition,false);
 assert.equal(f.model.selection_start,7);
});
test('non-BMP composition uses UTF-16 offsets and never writes through an active IME',()=>{
 const f=fixture('A😀B',3);
 f.ime.start();f.ime.update('𠮷');
 assert.equal(f.model.text,'A😀𠮷B');assert.equal(f.model.composition_start,3);assert.equal(f.model.composition_end,5);
 const writes=f.ta.writes;f.ime.sync({...f.model,text:makepad_ime_codepoints(f.model.text)});assert.equal(f.ta.writes,writes);
 f.ime.end('𠮷');assert.equal(f.model.text,'A😀𠮷B');assert.equal(f.ta.selectionStart,5);
});
test('a Rust edit outside the active composition survives its next preview and commit',()=>{
 const f=fixture('ab',1);f.ime.start();f.ime.update('你');
 f.ime.sync({text:makepad_ime_codepoints('A你b!'),selection_start:2,selection_end:2,has_composition:true,composition_start:1,composition_end:2});
 f.ime.update('你好');f.ime.end('你好');
 assert.equal(f.model.text,'A你好b!');assert.equal(f.ta.value,'A你好b!');
});
test('owner navigation/delete is flushed before the next DOM full state',()=>{
 const f=fixture('abc');
 f.ownerEdit({text:'ab',selection_start:1,selection_end:1});
 f.ime.flush();assert.equal(f.ta.value,'ab');assert.equal(f.ta.selectionStart,1);
 f.nativeInput('aXb',2,2,'insertText','X');assert.equal(f.model.text,'aXb');
 assert.equal(f.events[0],'flush');
});
test('cut deletes through the Rust event, copy does not mutate, paste replaces the selected range',()=>{
 const f=fixture('A😀B',1,3);
 const copy=clipboard();f.ime.clipboard(copy,false);
 assert.deepEqual(copy.writes,[['text/plain','😀']]);assert.equal(f.model.text,'A😀B');assert(copy.prevented);
 const cut=clipboard();f.ime.clipboard(cut,true);
 assert.deepEqual(cut.writes,[['text/plain','😀']]);assert.equal(f.model.text,'AB');assert.equal(f.ta.value,'AB');
 const paste=clipboard('中文🧭');f.ime.paste(paste);
 assert.equal(f.model.text,'A中文🧭B');assert.equal(f.model.was_paste,true);assert(paste.prevented);
});
test('clipboard requests reset the old response and never call async clipboard APIs',()=>{
 const f=fixture('none');f.host.text_copy_response='old selection';f.ta.setSelectionRange(0,0);
 f.ownerEdit({selection_start:0,selection_end:0});f.ime.flush();
 const copy=clipboard();f.ime.clipboard(copy,false);assert.deepEqual(copy.writes,[['text/plain','']]);
 assert(!source.includes('navigator.clipboard'));
});
test('hide retires composition and clears the native mirror before another field is used',()=>{
 const old=fixture('private draft');old.ime.start();old.ime.update('旧');old.ime.hide();
 assert.equal(old.ta.value,'');assert.equal(old.ime.active,false);assert.equal(old.ta.readOnly,true);
 const count=old.packets.length;
 old.ime.end('旧');old.ta.value='private draft旧';old.ime.input({inputType:'insertText',data:'旧'});
 assert.equal(old.packets.length,count);
 const next=fixture('new field');next.nativeInput('new field!');assert.equal(next.model.text,'new field!');
});
test('blur commits once and preserves the owner draft for focus restoration',()=>{
 const f=fixture('draft ');f.ime.start();f.ime.update('中文');f.ime.blur();
 assert.equal(f.model.text,'draft 中文');assert.equal(f.model.has_composition,false);
 const count=f.packets.length;f.ime.end('中文');assert.equal(f.packets.length,count);
 f.ime.sync({...f.model,text:makepad_ime_codepoints(f.model.text)});f.ime.show();f.nativeInput('draft 中文!');assert.equal(f.model.text,'draft 中文!');
});
test('a synced read-only field supports copy but cannot mutate through cut or paste',()=>{
 const f=fixture('read only',0,4);f.ime.hide();f.ime.sync({text:makepad_ime_codepoints('read only'),selection_start:0,selection_end:4,has_composition:false});
 const cut=clipboard();f.ime.clipboard(cut,true);assert.equal(f.model.text,'read only');
 f.ime.paste(clipboard('new'));assert.equal(f.model.text,'read only');assert.equal(f.ta.readOnly,true);
});
test('the source binds one actual owner-state path and preserves CSP packaging markers',async()=>{
 const rust=await readFile(new URL('src/os/web/web.rs',platform),'utf8');
 const dto=await readFile(new URL('src/os/web/to_wasm.rs',platform),'utf8');
 for(const name of ['ToWasmImeState','ToWasmImeRequestState','ToWasmTextCut']){
  assert(rust.includes(`live_id!(${name})`));assert(rust.includes(`${name}::to_js_code()`));
 }
 assert(rust.includes('FromWasmSyncImeState::to_js_code()'));
 assert(dto.includes('full_state_sync: Some(FullTextState'));
 assert(dto.includes('units += character.len_utf16()'));
 assert(rust.includes('selection.start.min(selection.end).to_utf16_index'));
 assert(source.includes("var style = document.createElement('style')"));
 assert(source.includes('document.body.appendChild(style)'));
 assert(!source.includes('substring(1, 2)'));
 assert(!source.includes('var ugly_ime_hack'));
 assert(source.includes('old_area.remove()'));
});

test('actual wire payload is Unicode scalars, not the broken pinned String codec',()=>{
 const text='A😀𠮷中';
 assert.deepEqual(makepad_ime_codepoints(text),[65,0x1f600,0x20bb7,0x4e2d]);
 assert.equal(makepad_ime_string(makepad_ime_codepoints(text)),text);
 const f=fixture();f.nativeInput(text);
 assert.deepEqual(f.packets.at(-1).text,[65,0x1f600,0x20bb7,0x4e2d]);
 assert.equal(f.model.text,text);assert.equal(f.model.selection_start,6);
});

test('malformed scalars are repaired explicitly and malformed/oversized payloads are rejected',()=>{
 assert.equal(makepad_ime_string([0x1f600,0xd800,0x110000,-1,1.5]),'😀����');
 assert.deepEqual(makepad_ime_codepoints('\ud800'),[0xfffd]);
 assert.throws(()=>makepad_ime_string('not an array'),TypeError);
 assert.throws(()=>makepad_ime_codepoints('x'.repeat(MAKEPAD_WEB_IME_MAX_UNITS+1)),RangeError);
 const f=fixture('safe');
 assert.throws(()=>f.nativeInput('x'.repeat(MAKEPAD_WEB_IME_MAX_UNITS+1)),RangeError);
 assert.equal(f.model.text,'safe');assert.equal(f.ta.value,'safe');
});
test('selection bounds clamp safely and never split a surrogate pair',()=>{
 assert.equal(makepad_ime_offset('A😀B',2),1);
 assert.equal(makepad_ime_offset('A😀B',100),4);
 assert.equal(makepad_ime_offset('A😀B',-5),0);
 assert.equal(makepad_ime_offset('A😀B',NaN),0);
 const f=fixture();
 f.ime.sync({text:makepad_ime_codepoints('A😀B'),selection_start:2,selection_end:999,has_composition:false});
 assert.equal(f.ta.selectionStart,1);assert.equal(f.ta.selectionEnd,4);
 f.ime.sync({text:[],selection_start:100,selection_end:100,has_composition:false});
 assert.equal(f.ta.value,'');assert.equal(f.ta.selectionStart,0);
});

test('reverse owner selection and direction-only updates preserve DOM selection and clipboard',()=>{
 const f=fixture('A😀BC',3,1);
 assert.equal(f.ta.selectionStart,1);assert.equal(f.ta.selectionEnd,3);assert.equal(f.ta.selectionDirection,'backward');
 const copy=clipboard();f.ime.clipboard(copy,false);assert.deepEqual(copy.writes,[['text/plain','😀']]);
 f.ownerEdit({selection_start:1,selection_end:3,selection_backward:false});f.ime.flush();
 assert.equal(f.ta.selectionDirection,'forward');
 f.ownerEdit({selection_start:1,selection_end:3,selection_backward:true});f.ime.flush();
 assert.equal(f.ta.selectionDirection,'backward');
 const cut=clipboard();f.ime.clipboard(cut,true);assert.deepEqual(cut.writes,[['text/plain','😀']]);
 assert.equal(f.model.text,'ABC');assert.equal(f.ta.selectionStart,1);assert.equal(f.ta.selectionEnd,1);
});
test('successive backward owner range updates survive the next native replacement',()=>{
 const f=fixture('A😀BC');
 f.ownerEdit({selection_start:4,selection_end:3,selection_backward:true});f.ime.flush();
 assert.equal(f.ta.selectionStart,3);assert.equal(f.ta.selectionEnd,4);assert.equal(f.ta.selectionDirection,'backward');
 f.ownerEdit({selection_start:4,selection_end:1,selection_backward:true});f.ime.flush();
 assert.equal(f.ta.selectionStart,1);assert.equal(f.ta.selectionEnd,4);assert.equal(f.ta.selectionDirection,'backward');
 f.nativeInput('A中C',2,2,'insertText','中');assert.equal(f.model.text,'A中C');
 assert.equal(f.model.selection_backward,false);
});
test('reversed composition ranges are normalized and empty ranges are unmarked',()=>{
 const f=fixture('ab',1);f.ime.start();f.ime.update('你');
 f.ime.sync({text:makepad_ime_codepoints('A你b!'),selection_start:2,selection_end:2,
  has_composition:true,composition_start:2,composition_end:1});
 f.ime.update('好');f.ime.end('好');assert.equal(f.model.text,'A好b!');
 const empty=f.ime.state('ab',1,1,[1,1]);assert.equal(empty.has_composition,false);
});

test('empty preedit plus an unmarked Rust echo keeps the native IME session alive',()=>{
 const f=fixture('prefix ',7);f.ime.start();f.ime.update('');
 const writes=f.ta.writes;
 f.ime.sync({...f.model,text:makepad_ime_codepoints(f.model.text)});
 assert(f.ime.composition);assert.equal(f.ta.writes,writes);
 f.ime.update('中文');f.ime.end('中文');
 assert.equal(f.model.text,'prefix 中文');assert.equal(f.model.has_composition,false);
});
test('IME deletion back to empty can receive an echo and continue another candidate',()=>{
 const f=fixture('前后',1);f.ime.start();f.ime.update('拼音');f.ime.update('');
 f.ime.sync({...f.model,text:makepad_ime_codepoints(f.model.text)});
 assert(f.ime.composition);f.ime.update('字');f.ime.end('字');
 assert.equal(f.model.text,'前字后');assert.equal(f.model.has_composition,false);
});
test('a filtered-to-empty Rust preview does not terminate the native session',()=>{
 const f=fixture('12',1);f.ime.start();f.ime.update('x');
 f.ime.sync({text:makepad_ime_codepoints('12'),selection_start:1,selection_end:1,
  has_composition:false,composition_start:0,composition_end:0});
 assert(f.ime.composition);f.ime.update('3');f.ime.end('3');assert.equal(f.model.text,'132');
});
test('actual sorted owner-sync contract cannot echo a changed DOM direction back into the Rust anchor',()=>{
 const f=fixture('ABCDE',2,4);f.ta.setSelectionRange(2,4,'backward');
 // TextInput sends sorted endpoints even for a backward Rust anchor/cursor.
 f.ownerEdit({selection_start:1,selection_end:4,selection_backward:false,owner_anchor:4,owner_cursor:1});
 f.ime.flush();const count=f.packets.length;
 f.ime.select();f.ime.select(); // deferred DOM select events, after the setter guard ended
 assert.equal(f.packets.length,count);assert.equal(f.model.owner_anchor,4);assert.equal(f.model.owner_cursor,1);
 f.ownerEdit({selection_start:0,selection_end:4,owner_anchor:4,owner_cursor:0});f.ime.flush();f.ime.select();
 assert.equal(f.packets.length,count);assert.equal(f.model.owner_anchor,4);assert.equal(f.model.owner_cursor,0);
});
