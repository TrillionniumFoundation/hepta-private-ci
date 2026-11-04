// Test tooling only: retain the shipping reader byte-for-byte. The pinned
// cargo-makepad cp_brotli minifies JavaScript before the UI packaging step.
import {createHash} from 'node:crypto';

const sha256=bytes=>createHash('sha256').update(bytes).digest('hex');
const SDK_REVISION='337566c8b25d47f7e4fff6a202157b65bf183330';
const METHODS_SHA256='4694a1d1de93b18c2eb14efdbccc8e13fe6fc2eeea106676c7dee236689bb9d1';
const BOUNDARIES=[
 '\nnetwork_http_dispatch(entry){\n',
 '\nnetwork_http_finish(entry){\n',
 '\njs_network_http_cancel(request_id_lo,request_id_hi){\n',
 '\njs_network_ws_open(socket_id_lo,socket_id_hi,url_ptr,url_len,_headers_ptr,_headers_len){\n',
];

export function extractHttpBoundaryMethods(asset,manifest){
 if(manifest.fixtures!==false)throw new Error('Boundary qualification requires the ordinary product build before fixture replacement');
 const pin=manifest.files?.['makepad_platform/web.js'];
 if(!pin||pin.bytes!==asset.length||pin.sha256!==sha256(asset))throw new Error('Shipping SDK does not match the built manifest');
 if(manifest.packagerSource!==SDK_REVISION)throw new Error('Unreviewed SDK revision');
 const source=asset.toString('utf8');
 const positions=BOUNDARIES.map(boundary=>{
  const position=source.indexOf(boundary);
  if(position<0||source.indexOf(boundary,position+1)!==-1)throw new Error('SDK method boundary changed');
  return position;
 });
 if(positions.some((position,index)=>index>0&&position<=positions[index-1]))throw new Error('SDK method boundary changed');
 // End at the next uniquely identified method, not the first closing brace:
 // minification puts nested block closures at the same indentation as methods.
 const methods=source.slice(positions[0]+1,positions[3]);
 if(sha256(methods)!==METHODS_SHA256)throw new Error('Shipping SDK reader changed; re-review its stream/cancel/limit contract');
 return methods;
}
