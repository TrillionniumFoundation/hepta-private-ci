// One capture contract shared by browser collection and mandatory offline QA.
export function captureSchedule(initialWidth,fixtures){
 if(![640,1280].includes(initialWidth))throw new Error('Unsupported capture viewport');
 const captures=[];let width=initialWidth;let hasDraft=false;
 const add=(name,theme,assertTheme=false,consoleView=false)=>captures.push({name,viewport:{width,height:800},theme,assertTheme,consoleView,fixtures,draft:hasDraft&&!consoleView,kept:name==='robrix-theme-round-trip',jump:name==='robrix-user-scrollback'||name==='robrix-scrollback-after-resize',lastMessage:name==='robrix-jump-to-latest'||(fixtures&&name===`robrix-Aurora-${initialWidth}`),cjk:fixtures&&!consoleView&&width>=1000});
 for(const theme of ['Aurora','Obsidian','Lunar']){
  add(`robrix-${theme}-${width}`,theme,true);
  width=width===1280?640:1280;
  add(`robrix-${theme}-after-resize`,theme,true);
  if(theme==='Aurora'){hasDraft=true;add('robrix-draft-before-theme',theme);}
 }
 add('robrix-theme-round-trip','Aurora',true);
 add('robrix-console','Aurora',false,true);
 add('robrix-console-round-trip','Aurora');
 if(fixtures){
  add('robrix-user-scrollback','Aurora');
  width=width===1280?640:1280;
  add('robrix-scrollback-after-resize','Aurora');
  add('robrix-jump-to-latest','Aurora');
 }
 return captures;
}
export function expectedPixelChecks(capture){
 const checks=capture.consoleView?['console-label','console-unavailable-reason']:['chat-readability'];
 if(!capture.consoleView&&capture.fixtures)checks.push('visible-message-count','owner-message-order');
 if(capture.draft)checks.push('draft-visible');
 if(capture.kept)checks.push('focus-kept-text');
 if(capture.lastMessage)checks.push('last-owner-message-visible');
 if(capture.fixtures&&!capture.consoleView&&!capture.jump)checks.push('last-owner-status-fully-visible');
 if(capture.jump)checks.push('jump-visible-in-rendered-area');
 if(capture.assertTheme)checks.push('exact-theme');
 if(capture.cjk)checks.push('exact-cjk');
 return checks;
}
