
function splitLines(s){return s.match(/[^\n]*\n|[^\n]+$/g)||[];}
function strictApply(input,patch,gitBlob){
 const original=splitLines(patch),lines=[];
 for(const line of original){if(line.startsWith("\\ No newline at end of file")){if(!lines.length||!/^[ +\-]/.test(lines[lines.length-1]))throw Error("invalid EOF marker");if(!lines[lines.length-1].endsWith("\n"))throw Error("repeated EOF marker");lines[lines.length-1]=lines[lines.length-1].slice(0,-1);}else lines.push(line);}
 const result={...input},records=[];let i=0;
 while(i<lines.length){
  const m=/^diff --git a\/(\S+) b\/(\S+)\n?$/.exec(lines[i++]);if(!m||m[1]!==m[2])throw Error("unsupported patch path header");
  const path=m[1];if(records.some(x=>x.path===path))throw Error("repeated file section");
  let oldPath,newPath,indexBefore,indexAfter;
  while(i<lines.length&&!lines[i].startsWith("@@ ")){
   const line=lines[i++];if(line.startsWith("diff --git "))throw Error("file without hunks");
   let a;if((a=/^index ([0-9a-f]+)\.\.([0-9a-f]+)(?: 100644)?\n?$/.exec(line))){indexBefore=a[1];indexAfter=a[2];}
   else if(line.startsWith("--- "))oldPath=line.slice(4).replace(/\n$/,"");
   else if(line.startsWith("+++ "))newPath=line.slice(4).replace(/\n$/,"");
   else if(line!=="new file mode 100644\n")throw Error("unsupported patch metadata "+line);
  }
  if(oldPath!=="/dev/null"&&oldPath!=="a/"+path)throw Error("old path mismatch");
  if(newPath!=="b/"+path)throw Error("new path mismatch");
  const exists=Object.prototype.hasOwnProperty.call(input,path)&&input[path]!==null;
  if((oldPath==="/dev/null")===exists)throw Error("base existence mismatch "+path);
  const before=exists?input[path]:"",src=splitLines(before),out=[],hunks=[];let cursor=0;
  if(indexBefore&&exists&&!gitBlob(before).startsWith(indexBefore))throw Error("old blob mismatch");
  while(i<lines.length&&lines[i].startsWith("@@ ")){
   const h=/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:[^\n]*)\n?$/.exec(lines[i++]);
   if(!h)throw Error("invalid hunk");
   const oldStart=+h[1],oldCount=h[2]===undefined?1:+h[2],newStart=+h[3],newCount=h[4]===undefined?1:+h[4];
   const target=oldCount===0?oldStart:oldStart-1,newTarget=newCount===0?newStart:newStart-1;
   if(target<cursor||target>src.length)throw Error("old line coordinate out of bounds");
   while(cursor<target)out.push(src[cursor++]);if(out.length!==newTarget)throw Error("new line coordinate mismatch");
   let consumed=0,produced=0;
   while(i<lines.length&&!lines[i].startsWith("@@ ")&&!lines[i].startsWith("diff --git ")){
    const line=lines[i++],tag=line[0],value=line.slice(1);
    if(tag===" "||tag==="-"){if(src[cursor]!==value)throw Error("exact hunk source mismatch at "+path+":"+(cursor+1));cursor++;consumed++;if(tag===" "){out.push(value);produced++;}}
    else if(tag==="+"){out.push(value);produced++;}
    else throw Error("invalid hunk line prefix");
   }
   if(consumed!==oldCount||produced!==newCount)throw Error("hunk counts mismatch");
   hunks.push({old_start:oldStart,old_count:oldCount,new_start:newStart,new_count:newCount});
  }
  while(cursor<src.length)out.push(src[cursor++]);
  const after=out.join("");if(indexAfter&&!gitBlob(after).startsWith(indexAfter))throw Error("new blob mismatch");
  result[path]=after;records.push({path,hunks});
 }
 return{files:result,records};
}
return {strictApply};
