fn read_frames(sender: mpsc::Sender<HostEvent>) {
    let mut input = io::stdin().lock();
    let mut expected_sequence = 1_u64;
    loop {
        let mut prefix = [0_u8; 4];
        match input.read_exact(&mut prefix) {
            Ok(()) => {}
            Err(error) if error.kind() == io::ErrorKind::UnexpectedEof => {
                let _ = sender.send(HostEvent::Eof);
                return;
            }
            Err(error) => {
                let _ = sender.send(HostEvent::Fatal(format!("private channel read failed: {error}")));
                return;
            }
        }
        let length = u32::from_be_bytes(prefix) as usize;
        if length == 0 || length > MAX_FRAME_BYTES {
            let _ = sender.send(HostEvent::Fatal("private channel frame length invalid".to_string()));
            return;
        }
        let mut bytes = vec![0_u8; length];
        if let Err(error) = input.read_exact(&mut bytes) {
            let _ = sender.send(HostEvent::Fatal(format!("private channel frame truncated: {error}")));
            return;
        }
        let raw = match String::from_utf8(bytes) {
            Ok(value) => value,
            Err(_) => {
                let _ = sender.send(HostEvent::Fatal("private channel frame is not UTF-8".to_string()));
                return;
            }
        };
        let value: Value = match serde_json::from_str(&raw) {
            Ok(value) => value,
            Err(error) => {
                let _ = sender.send(HostEvent::Fatal(format!("private channel JSON invalid: {error}")));
                return;
            }
        };
        if let Err(error) = validate_safe_json(&value, 0) {
            let _ = sender.send(HostEvent::Fatal(error));
            return;
        }
        if canonical_json(&value) != raw {
            let _ = sender.send(HostEvent::Fatal("private channel JSON is not canonical".to_string()));
            return;
        }
        let frame: Frame = match serde_json::from_value(value) {
            Ok(frame) => frame,
            Err(error) => {
                let _ = sender.send(HostEvent::Fatal(format!("private channel frame schema invalid: {error}")));
                return;
            }
        };
        if let Err(error) = validate_frame(&frame, expected_sequence) {
            let _ = sender.send(HostEvent::Fatal(error));
            return;
        }
        expected_sequence += 1;
        if sender.send(HostEvent::Command(frame)).is_err() {
            return;
        }
    }
}

fn validate_frame(frame: &Frame, sequence: u64) -> Result<(), String> {
    if frame.schema != SCHEMA || frame.protocol_version != PROTOCOL_VERSION {
        return Err("private channel protocol is unsupported".to_string());
    }
    if frame.sequence != sequence || frame.sequence == 0 {
        return Err("private channel sequence is not monotonic".to_string());
    }
    if frame.generation == 0 || frame.generation > MAX_SAFE_INTEGER {
        return Err("private channel generation is invalid".to_string());
    }
    if !stable_id(&frame.session_id) || !stable_id(&frame.request_id) {
        return Err("private channel identity is invalid".to_string());
    }
    if !matches!(frame.kind.as_str(), "start" | "observe" | "dispatch" | "reconcile" | "stop") {
        return Err("private channel command kind is not registered".to_string());
    }
    if !is_digest(&frame.payload_digest)
        || sha256_hex(canonical_json(&frame.payload).as_bytes()) != frame.payload_digest
    {
        return Err("private channel payload digest mismatch".to_string());
    }
    Ok(())
}

fn write_worker_frame(
    output: &mut impl Write,
    request: &Frame,
    sequence: u64,
    kind: &str,
    payload: Value,
) -> Result<(), String> {
    if !matches!(kind, "dispatch_boundary" | "response") {
        return Err("worker attempted to emit an unregistered frame kind".to_string());
    }
    let frame = json!({
        "schema": SCHEMA,
        "protocolVersion": PROTOCOL_VERSION,
        "sessionId": request.session_id,
        "generation": request.generation,
        "sequence": sequence,
        "kind": kind,
        "requestId": request.request_id,
        "payloadDigest": sha256_hex(canonical_json(&payload).as_bytes()),
        "payload": payload,
    });
    let body = canonical_json(&frame);
    if body.len() > MAX_FRAME_BYTES {
        return Err("response frame exceeds byte limit".to_string());
    }
    output
        .write_all(&(body.len() as u32).to_be_bytes())
        .and_then(|_| output.write_all(body.as_bytes()))
        .and_then(|_| output.flush())
        .map_err(|error| format!("private channel response failed: {error}"))
}

fn write_response(
    output: &mut impl Write,
    request: &Frame,
    sequence: u64,
    payload: Value,
) -> Result<(), String> {
    write_worker_frame(output, request, sequence, "response", payload)
}

#[cfg(unix)]
fn secure_random_hex(byte_count: usize) -> Result<String, String> {
    if byte_count == 0 || byte_count > 64 {
        return Err("private bridge random byte count is outside the bound".to_string());
    }
    let mut bytes = vec![0_u8; byte_count];
    File::open("/dev/urandom")
        .and_then(|mut file| file.read_exact(&mut bytes))
        .map_err(|error| format!("private bridge randomness unavailable: {error}"))?;
    let mut output = String::with_capacity(byte_count * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        let _ = write!(&mut output, "{byte:02x}");
    }
    Ok(output)
}

#[cfg(not(unix))]
fn secure_random_hex(_byte_count: usize) -> Result<String, String> {
    Err("the current private action bridge is qualified only on Unix".to_string())
}

fn private_action_bridge_script(name: &str, secret: &str, token_prefix: &str) -> String {
    let script = r#"(()=>{
"use strict";
const BRIDGE_NAME=__BRIDGE_NAME__;
const SECRET=__BRIDGE_SECRET__;
const TOKEN_PREFIX=__TOKEN_PREFIX__;
const apply=Reflect.apply;
const defineProperty=Object.defineProperty;
const getOwnPropertyDescriptor=Object.getOwnPropertyDescriptor;
const create=Object.create;
const setPrototypeOf=Object.setPrototypeOf;
const stringify=JSON.stringify;
const isArray=Array.isArray;
const nativeString=String;
const toLowerCase=String.prototype.toLowerCase;
const numberToString=Number.prototype.toString;
const querySelector=Document.prototype.querySelector;
const getClientRects=Element.prototype.getClientRects;
const matches=Element.prototype.matches;
const getAttribute=Element.prototype.getAttribute;
const hasAttribute=Element.prototype.hasAttribute;
const tagNameGetter=getOwnPropertyDescriptor(Element.prototype,"tagName").get;
const getComputedStyleNative=window.getComputedStyle;
const getPropertyValue=CSSStyleDeclaration.prototype.getPropertyValue;
const click=HTMLElement.prototype.click;
const focus=HTMLElement.prototype.focus;
const dispatchEvent=EventTarget.prototype.dispatchEvent;
const inputValueSetter=getOwnPropertyDescriptor(HTMLInputElement.prototype,"value").set;
const textareaValueSetter=getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value").set;
const inputReadOnlyGetter=getOwnPropertyDescriptor(HTMLInputElement.prototype,"readOnly").get;
const textareaReadOnlyGetter=getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"readOnly").get;
const NativeEvent=window.Event;
const weakGet=WeakMap.prototype.get;
const weakSet=WeakMap.prototype.set;
const ownerDocument=window.document;
const handles=new WeakMap();
let nextHandle=1;
const call=(fn,receiver,args)=>apply(fn,receiver,args);
const select=(selector)=>call(querySelector,ownerDocument,[selector]);
const text=(value)=>nativeString(value??"");
const lower=(value)=>call(toLowerCase,text(value),[]);
const record=()=>call(create,Object,[null]);
const bareArray=()=>{
  const value=[];
  call(setPrototypeOf,Object,[value,null]);
  return value;
};
const encode=(value)=>call(stringify,JSON,[value]);
const visible=(element)=>{
  if(!element||call(getClientRects,element,[]).length===0) return false;
  const style=call(getComputedStyleNative,window,[element]);
  const display=call(getPropertyValue,style,["display"]);
  const visibility=call(getPropertyValue,style,["visibility"]);
  return display!=="none"&&visibility!=="hidden"&&visibility!=="collapse";
};
const disabled=(element)=>call(matches,element,[":disabled"]);
const tag=(element)=>lower(call(tagNameGetter,element,[]));
const attribute=(element,name)=>lower(call(getAttribute,element,[name]));
const has=(element,name)=>call(hasAttribute,element,[name]);
const supportedTextInput=(element,elementTag,inputType)=>{
  if(elementTag==="textarea") return !call(textareaReadOnlyGetter,element,[]);
  if(elementTag!=="input") return false;
  if(call(inputReadOnlyGetter,element,[])) return false;
  return inputType===""||inputType==="text"||inputType==="search"||inputType==="email"||inputType==="url"||inputType==="tel";
};
const tokenFor=(element)=>{
  let token=call(weakGet,handles,[element]);
  if(token===undefined){
    token=TOKEN_PREFIX+":"+call(numberToString,nextHandle,[36]);
    nextHandle+=1;
    call(weakSet,handles,[element,token]);
  }
  return token;
};
const fail=(error)=>{
  const result=record();
  result.ok=false;
  result.error=error;
  return encode(result);
};
const bridge=(candidateSecret,request)=>{
  if(candidateSecret!==SECRET) return fail("unauthorized");
  try{
    if(request===null||typeof request!=="object") return fail("invalid_request");
    if(request.kind==="bind"){
      if(!isArray(request.selectors)||request.selectors.length>256) return fail("invalid_selectors");
      const output=bareArray();
      for(let index=0;index<request.selectors.length;index+=1){
        const selector=request.selectors[index];
        if(typeof selector!=="string"||selector.length===0||selector.length>2048) return fail("invalid_selector");
        const element=select(selector);
        if(!visible(element)) return fail("target_missing");
        const entry=record();
        entry.selector=selector;
        entry.handle=tokenFor(element);
        output[index]=entry;
      }
      const result=record();
      result.ok=true;
      result.handles=output;
      return encode(result);
    }
    if(request.kind!=="act") return fail("invalid_request_kind");
    if(typeof request.action!=="string"||typeof request.selector!=="string"||typeof request.handle!=="string") return fail("invalid_action_request");
    const element=select(request.selector);
    if(!element) return fail("target_missing");
    if(tokenFor(element)!==request.handle) return fail("target_identity_drift");
    if(!visible(element)||disabled(element)) return fail("target_not_actionable");
    const elementTag=tag(element);
    const inputType=attribute(element,"type");
    if(request.action==="click"){
      if((elementTag==="input"&&inputType==="file")||(elementTag==="a"&&has(element,"download"))) return fail("capability_not_connected");
      call(click,element,[]);
    }else if(request.action==="focus"){
      call(focus,element,[]);
    }else if(request.action==="type"){
      if(typeof request.text!=="string") return fail("invalid_type_text");
      if(!supportedTextInput(element,elementTag,inputType)) return fail("target_type_not_allowed");
      call(focus,element,[]);
      if(elementTag==="textarea") call(textareaValueSetter,element,[request.text]);
      else call(inputValueSetter,element,[request.text]);
      call(dispatchEvent,element,[new NativeEvent("input",{bubbles:true})]);
      call(dispatchEvent,element,[new NativeEvent("change",{bubbles:true})]);
    }else{
      return fail("unsupported_action");
    }
    const result=record();
    result.ok=true;
    result.acted=true;
    return encode(result);
  }catch(_error){
    return fail("bridge_failure");
  }
};
defineProperty(window,BRIDGE_NAME,{value:bridge,writable:false,enumerable:false,configurable:false});
})();"#;
    script
        .replace(
            "__BRIDGE_NAME__",
            &serde_json::to_string(name).expect("bridge name serialization cannot fail"),
        )
        .replace(
            "__BRIDGE_SECRET__",
            &serde_json::to_string(secret).expect("bridge secret serialization cannot fail"),
        )
        .replace(
            "__TOKEN_PREFIX__",
            &serde_json::to_string(token_prefix)
                .expect("bridge token serialization cannot fail"),
        )
}

