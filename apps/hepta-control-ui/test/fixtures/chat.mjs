// Deterministic qualification fixture ONLY; never a production messaging backend.
let enabled = false;
let messages = [];
let sends = new Map();
export function resetChat() { enabled = false; messages = []; sends = new Map(); }
export function enableChat() { enabled = true; }
export function seedChatHistory() {
  enabled = true;
  messages = Array.from({length:120}, (_,i)=>({id:`history-${i+1}`,threadId:"chat-one",turnId:"historical-turn",sender:"assistant",body:`Historical message ${i+1}`}));
}
export function chatState() { return { sendCount: sends.size, messages }; }
export function chatReply(input) {
  if (!enabled) return null;
  const c = input.command;
  let result;
  const room = id => ({ id, title: id === "chat-one" ? "Engineering" : "Research", preview: "Authenticated fixture conversation" });
  if (c.type === "list") result = { type: "conversations", data: [room("chat-one"), room("chat-two")], nextCursor: null };
  else if (c.type === "create") result = { type: "conversation", data: {id:"chat-new",title:"",preview:""} };
  else if (c.type === "timeline") {
    const roomMessages = messages.filter(m=>m.threadId === c.threadId);
    const offset=Number(c.cursor ?? 0), end=Math.max(0,roomMessages.length-offset), start=Math.max(0,end-c.limit);
    result={type:"timeline",threadId:c.threadId,activeTurnId:roomMessages.some(m=>sends.has(m.id)) ? "turn-1" : null,data:roomMessages.slice(start,end).map(({threadId,...m})=>m),nextCursor:start>0 ? String(offset+c.limit) : null};
  }
  else if (c.type === "send" || c.type === "reconcile") {
    if (c.type === "send" && !sends.has(c.operationId)) {
      sends.set(c.operationId, c.text);
      messages.push({ id: c.operationId, threadId:c.threadId, turnId:"turn-1", sender:"user", body:c.text });
    }
    result = { type: "submission", operationId:c.operationId, state: sends.has(c.operationId) ? {type:"persisted",turnId:"turn-1"} : {type:"missing"} };
  } else if(c.type === "cancel") result = {type:"cancelRequested",threadId:c.threadId,turnId:c.turnId};
  else return null;
  return {approvalRequired:false, sessionId: input.sessionId, connectionGeneration: input.connectionGeneration, result};
}
