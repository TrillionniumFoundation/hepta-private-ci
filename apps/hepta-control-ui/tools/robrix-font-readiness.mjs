// This fixture-only observation is a renderer-readiness assertion, not owner authority.
export function sharedFontFamilyReady(text){
 if(typeof text!=='string'||text.length>8192)return false;
 const match=text.match(/HEPTA_FIXTURE_FONT_STATE index=\d+ loaded_fonts=4 complete=true members=(\[[^\n]+\])$/);
 if(!match)return false;
 try{return JSON.stringify(JSON.parse(match[1]))===JSON.stringify(['latin','cjk','rare','emoji']);}
 catch{return false;}
}
