// One capture contract shared by browser collection and mandatory offline QA.
export function captureSchedule(initialWidth,fixtures){
 if(![640,1280].includes(initialWidth))throw new Error('Unsupported capture viewport');
 const captures=[];let width=initialWidth;
 const add=(name,theme,assertTheme=false,consoleView=false)=>captures.push({name,viewport:{width,height:800},theme,assertTheme,consoleView,cjk:fixtures&&!consoleView&&width>=1000});
 for(const theme of ['Aurora','Obsidian','Lunar']){
  add(`robrix-${theme}-${width}`,theme,true);
  width=width===1280?640:1280;
  add(`robrix-${theme}-after-resize`,theme);
  if(theme==='Aurora')add('robrix-draft-before-theme',theme);
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
