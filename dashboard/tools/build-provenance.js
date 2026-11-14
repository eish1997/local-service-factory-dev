const fs=require('fs'),path=require('path'),crypto=require('crypto'),{execFileSync}=require('child_process');
function sourceIdentity(root){
 const git=(...args)=>execFileSync('git',['-C',root,...args],{encoding:'utf8',windowsHide:true}).trim();
 if(git('status','--porcelain','--untracked-files=normal'))throw Error('正式构建需要干净且已提交的源码工作树');
 const sha=git('rev-parse','HEAD');
 if(!/^[a-f0-9]{40}$/.test(sha))throw Error('无法识别构建源码提交');
 return sha;
}
function recordBuild(folder,cfg,sourceSha){
 const files={};
 for(const name of [`LocalServiceFactory-${cfg.app_version}-setup.exe`,`LocalServiceFactory-${cfg.app_version}-setup.exe.blockmap`,'latest.yml'])files[name]=crypto.createHash('sha256').update(fs.readFileSync(path.join(folder,name))).digest('hex');
 const value={schema_version:1,source_sha:sourceSha,version:cfg.app_version,repository:{owner:cfg.owner,repo:cfg.software_repo},files};
 fs.writeFileSync(path.join(folder,'build-provenance.json'),JSON.stringify(value,null,2));
 return value;
}
function validateStage(stage,sourceSha){
 const record=JSON.parse(fs.readFileSync(path.join(stage,'stage-provenance.json'),'utf8'));
 if(record.source_sha!==sourceSha)throw Error('暂存引擎与构建源码提交不一致');
 const files={};
 function visit(folder,prefix=''){
  for(const entry of fs.readdirSync(folder,{withFileTypes:true})){
   if(entry.name==='__pycache__'||entry.name.endsWith('.pyc'))continue;
   if(entry.isSymbolicLink())throw Error('暂存引擎不能包含符号链接');
   const relative=prefix+entry.name,file=path.join(folder,entry.name);
   if(entry.isDirectory())visit(file,relative+'/');
   else files[relative]=crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  }
 }
 visit(path.join(stage,'engine'));
 const expected=record.engine_files;
 if(!expected||Object.keys(files).length!==Object.keys(expected).length||Object.entries(files).some(([name,digest])=>expected[name]!==digest))throw Error('暂存引擎内容已变化，请重新暂存');
}
module.exports={sourceIdentity,recordBuild,validateStage};
