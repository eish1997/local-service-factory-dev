const fs=require('fs'),path=require('path');
function read(file){try{return JSON.parse(fs.readFileSync(file,'utf8'));}catch{return {};}}
function roots(root){const s=read(path.join(root,'.runtime','asset_settings.json'));return [...new Set([path.join(root,'output'),s.path,...(s.previous_paths||[])].filter(Boolean).map(p=>path.resolve(p)))];}
function inside(parent,file){const r=path.relative(path.resolve(parent),path.resolve(file));return !r||(!r.startsWith('..')&&!path.isAbsolute(r));}
function allowed(root,file){return roots(root).some(r=>inside(r,file));}
function batchOutput(root,category,batch){
 if(!/^[\w-]+$/.test(category)||!/^batch_[\w-]+$/.test(batch))throw Error('无效批次');
 const data=read(path.join(root,'prompts','library',category,batch,'batch.json'));
 const base=path.resolve(data.asset_root||path.join(root,'output'));
 if(!roots(root).includes(base))throw Error('资产根目录未登记');
 return path.join(base,category,'library',batch);
}
module.exports={roots,inside,allowed,batchOutput};
