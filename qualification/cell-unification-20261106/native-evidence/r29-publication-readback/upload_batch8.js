async function uploadR29Batch8() {
 const r=await tools.exec_command({cmd:"python r29-formal-root-preparation/next_upload_batch.py",login:false,max_output_tokens:6500});if(r.exit_code!==0)throw Error(r.output);const p=JSON.parse(r.output);if(!p.next.length){text({completed:p.completed,total:p.total});return;}
 const h=new Function(load("recovery/root-byte-helper.js")+";return {sha256,gitBlob,encodeUTF8,decodeUTF8,sha1};")(),reader=new Function(load("recovery/runtime-cache-20261106/read-local-bytes.js")+";return readLocalBytes;")();
 const results=await Promise.allSettled(p.next.map(async row=>{
  if(row.known_actual_git_blob)return {repo_path:row.repo_path,git_blob:row.git_blob,binary:row.binary,reused:true,origin:"verified_checkpoint6_or_registered_blob_or_prior_batch"};
  const bytes=await reader(row.local_path,row,tools,h),content=row.binary?bytes.toBase64():h.decodeUTF8(bytes);if(!row.binary&&h.sha256(Uint8Array.from(h.encodeUTF8(content)))!==row.sha256)throw Error("UTF8 mismatch "+row.path);
  const actual_response=await tools.mcp__codex_apps__github_create_blob({repository_full_name:"TrillionniumFoundation/hepta-private-ci",content,encoding:row.binary?"base64":"utf-8"});if(actual_response.isError||actual_response.structuredContent?.sha!==row.git_blob)throw Error("actual blob differs "+row.path);
  return {repo_path:row.repo_path,git_blob:row.git_blob,binary:row.binary,reused:false,actual_response};
 }));
 const staged=[],errors=[];for(const v of results){if(v.status==="fulfilled")staged.push(v.value);else errors.push(String(v.reason));}
 const batch={schema:"hepta.root-r29-formal-actual-upload-batch.v1",completed_paths:p.completed+staged.length,total_paths:p.total,staged,errors};const save=new Function("return "+load("root_save_json_js"))();await save("r29-formal-root-preparation/upload-batches/batch-"+String(batch.completed_paths).padStart(3,"0")+".json",batch);
 const overlay=load("source50_artifact_overlay")||{};for(const row of staged)overlay[row.repo_path]=row.git_blob;store("source50_artifact_overlay",overlay);
 text({completed:batch.completed_paths,total:p.total,created:staged.filter(x=>!x.reused).length,reused:staged.filter(x=>x.reused).length,errors});if(errors.length)throw Error("Some uploads failed; original receipts preserved.");
}
