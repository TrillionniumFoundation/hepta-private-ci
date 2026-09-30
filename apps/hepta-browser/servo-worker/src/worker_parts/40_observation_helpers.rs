fn private_bridge_request_script(
    name: &str,
    secret: &str,
    request: &Value,
) -> Result<String, String> {
    if !name
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_')
    {
        return Err("private bridge name is not a safe JavaScript identifier".to_string());
    }
    let secret = serde_json::to_string(secret).map_err(|error| error.to_string())?;
    let request = canonical_json(request);
    Ok(format!(
        r#"(()=>{{if(typeof {name}!=="function")return "{{\"ok\":false,\"error\":\"bridge_unavailable\"}}";return {name}({secret},{request});}})()"#
    ))
}

fn parse_private_action_handles(
    response: &Value,
    expected_count: usize,
) -> Result<HashMap<String, String>, String> {
    if response.get("ok").and_then(Value::as_bool) != Some(true) {
        let error = response
            .get("error")
            .and_then(Value::as_str)
            .unwrap_or("invalid_response");
        return Err(format!("private action handle binding failed: {error}"));
    }
    let values = response
        .get("handles")
        .and_then(Value::as_array)
        .ok_or_else(|| "private action bridge response lacks handles".to_string())?;
    if values.len() != expected_count || values.len() > 256 {
        return Err("private action bridge handle count drifted".to_string());
    }
    let mut handles = HashMap::with_capacity(values.len());
    for value in values {
        let selector = value
            .get("selector")
            .and_then(Value::as_str)
            .ok_or_else(|| "private action handle lacks selector".to_string())?;
        let handle = value
            .get("handle")
            .and_then(Value::as_str)
            .ok_or_else(|| "private action handle lacks token".to_string())?;
        if selector.is_empty()
            || selector.len() > 2048
            || handle.is_empty()
            || handle.len() > 128
            || handles
                .insert(selector.to_string(), handle.to_string())
                .is_some()
        {
            return Err("private action handle response is invalid".to_string());
        }
    }
    Ok(handles)
}

fn semantic_snapshot_script(budget: usize) -> String {
    let script = r#"(()=>{
const budget=__BUDGET__;
const enc=new TextEncoder();
const clean=(value,max)=>String(value??"").replace(/\s+/g," ").trim().slice(0,max);
const selectorFor=(el)=>{
  const parts=[];
  let node=el;
  for(let depth=0;node&&node.nodeType===1&&depth<64;depth+=1,node=node.parentElement){
    const tag=node.tagName.toLowerCase();
    let index=1;
    for(let sibling=node.previousElementSibling;sibling;sibling=sibling.previousElementSibling){
      if(sibling.tagName===node.tagName) index+=1;
    }
    parts.push(`${tag}:nth-of-type(${index})`);
  }
  const selector=parts.reverse().join(">");
  if(!selector||selector.length>2048) return "";
  try{return document.querySelector(selector)===el?selector:"";}catch{return "";}
};
const visible=(el)=>{
  if(!el||typeof el.getClientRects!=="function"||el.getClientRects().length===0) return false;
  const style=getComputedStyle(el);
  return style.display!=="none"&&style.visibility!=="hidden"&&style.visibility!=="collapse";
};
const links=[];
for(const a of Array.from(document.querySelectorAll("a[href]")).slice(0,128)){
  if(!visible(a)||a.hasAttribute("download")) continue;
  const selector=selectorFor(a);
  if(!selector) continue;
  try{
    const u=new URL(a.href,document.baseURI);
    if(u.protocol!=="http:"&&u.protocol!=="https:") continue;
    links.push({text:clean(a.innerText||a.textContent,512),href:u.href.slice(0,4096),selector});
  }catch{}
}
const controls=[];
const nodes=document.querySelectorAll("a[href],button,input:not([type=password]),textarea,select,[role=button],[tabindex]");
for(const el of Array.from(nodes).slice(0,256)){
  if(!visible(el)||el.matches("a[download]")) continue;
  const selector=selectorFor(el);
  if(!selector) continue;
  const type=clean(el.getAttribute("type"),64).toLowerCase();
  if(type==="password"||type==="file") continue;
  controls.push({
    selector,
    tag:clean(el.tagName,32).toLowerCase(),
    role:clean(el.getAttribute("role"),64),
    type,
    name:clean(el.getAttribute("name"),128),
    ariaLabel:clean(el.getAttribute("aria-label"),512),
    placeholder:clean(el.getAttribute("placeholder"),512),
    disabled:Boolean(el.disabled),
    readOnly:Boolean(el.readOnly),
    checked:Boolean(el.checked)
  });
}
const forms=[];
for(const form of Array.from(document.forms).slice(0,64)){
  if(!visible(form)) continue;
  const selector=selectorFor(form);
  if(!selector) continue;
  let action="";
  try{const u=new URL(form.action||document.URL,document.baseURI);if(u.protocol==="http:"||u.protocol==="https:") action=u.href.slice(0,4096);}catch{}
  forms.push({method:clean(form.method||"get",16).toLowerCase(),action,controlCount:Math.min(form.elements?.length||0,4096),selector});
}
const out={
  schema:"hepta.browser.semantic-observation.v1",
  title:clean(document.title,1024),
  visibleText:clean(document.body?.innerText||"",Math.min(65536,Math.max(0,Math.floor(budget/2)))),
  links,
  controls,
  forms,
  viewport:{width:Math.max(0,Math.floor(innerWidth||0)),height:Math.max(0,Math.floor(innerHeight||0))},
  truncated:false
};
const bytes=()=>enc.encode(JSON.stringify(out)).byteLength;
if(bytes()>budget){out.forms=[];out.truncated=true;}
if(bytes()>budget){out.links=out.links.slice(0,32);out.controls=out.controls.slice(0,64);out.truncated=true;}
while(bytes()>budget&&out.visibleText.length>0){out.visibleText=out.visibleText.slice(0,Math.floor(out.visibleText.length/2));out.truncated=true;}
if(bytes()>budget){out.links=[];out.controls=[];out.forms=[];out.title="";out.visibleText="";out.truncated=true;}
return JSON.stringify(out);
})()"#;
    script.replace("__BUDGET__", &budget.to_string())
}

fn parse_allowed_origins(payload: &Value) -> Result<HashSet<String>, String> {
    let values = payload
        .get("allowedOrigins")
        .and_then(Value::as_array)
        .ok_or_else(|| "start.allowedOrigins must be an array".to_string())?;
    if values.len() > 128 {
        return Err("start.allowedOrigins exceeds bound".to_string());
    }
    let mut allowed = HashSet::new();
    for value in values {
        let raw = value
            .as_str()
            .ok_or_else(|| "allowed origin must be a string".to_string())?;
        let url = Url::parse(raw).map_err(|error| format!("allowed origin invalid: {error}"))?;
        let normalized = origin(&url).ok_or_else(|| "allowed origin must use HTTP(S)".to_string())?;
        if raw.trim_end_matches('/') != normalized || !allowed.insert(normalized) {
            return Err("allowed origin is non-canonical or duplicated".to_string());
        }
    }
    Ok(allowed)
}

fn origin(url: &Url) -> Option<String> {
    matches!(url.scheme(), "http" | "https").then(|| url.origin().ascii_serialization())
}

fn stored_receipt(value: &StoredOperation) -> Value {
    match &value.terminal {
        Some((status, outcome)) => json!({
            "terminalObserved": true,
            "status": status,
            "outcomeDigest": outcome,
        }),
        None => json!({"terminalObserved": false}),
    }
}

fn succeeded(action: &str, digest: &str) -> Value {
    json!({
        "terminalObserved": true,
        "status": "succeeded",
        "outcomeDigest": digest,
        "action": action,
    })
}

fn failed(action: &str, reason: &str) -> Value {
    json!({
        "terminalObserved": true,
        "status": "failed",
        "outcomeDigest": sha256_hex(format!("failed\0{action}\0{reason}").as_bytes()),
        "action": action,
    })
}

fn fixed_scroll(action: &Map<String, Value>) -> Result<String, String> {
    let x = action
        .get("deltaX")
        .and_then(Value::as_i64)
        .ok_or_else(|| "scroll.deltaX must be an integer".to_string())?;
    let y = action
        .get("deltaY")
        .and_then(Value::as_i64)
        .ok_or_else(|| "scroll.deltaY must be an integer".to_string())?;
    Ok(format!("(()=>{{window.scrollBy({x},{y});return true;}})()"))
}

fn string_field<'a>(value: &'a Value, name: &str) -> Result<&'a str, String> {
    value
        .get(name)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("{name} must be a string"))
}

fn action_surface_digest(observation: &Value) -> Result<String, String> {
    let object = observation
        .as_object()
        .ok_or_else(|| "semantic observation must be an object".to_string())?;
    let links = object
        .get("links")
        .cloned()
        .ok_or_else(|| "semantic observation lacks links".to_string())?;
    let controls = object
        .get("controls")
        .cloned()
        .ok_or_else(|| "semantic observation lacks controls".to_string())?;
    let forms = object
        .get("forms")
        .cloned()
        .ok_or_else(|| "semantic observation lacks forms".to_string())?;
    let surface = json!({
        "links": links,
        "controls": controls,
        "forms": forms,
    });
    validate_safe_json(&surface, 0)?;
    Ok(sha256_hex(canonical_json(&surface).as_bytes()))
}

fn observed_control<'a>(
    observation: &'a Value,
    selector: &str,
) -> Result<Option<&'a Map<String, Value>>, String> {
    let controls = observation
        .get("controls")
        .and_then(Value::as_array)
        .ok_or_else(|| "semantic observation lacks controls".to_string())?;
    for value in controls {
        let control = value
            .as_object()
            .ok_or_else(|| "semantic observation control must be an object".to_string())?;
        if control.get("selector").and_then(Value::as_str) == Some(selector) {
            return Ok(Some(control));
        }
    }
    Ok(None)
}