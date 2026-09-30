const fs=require('fs'),path=require('path'),crypto=require('crypto'),{spawn}=require('child_process');
const backend=require('./backend');
// Electron's patched fs treats app.asar as a directory; backups need its raw bytes.
const backupFs=process.versions.electron?require('original-fs'):fs;
function canonical(value){if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';return JSON.stringify(value);}
function verify(envelope,keys){
 const raw=keys[envelope?.key_id];if(!raw)throw Error('尚未配置可信发布公钥');
 const key=crypto.createPublicKey({key:Buffer.concat([Buffer.from('302a300506032b6570032100','hex'),Buffer.from(raw,'base64')]),format:'der',type:'spki'});
 if(!crypto.verify(null,Buffer.from(canonical(envelope.payload)),key,Buffer.from(envelope.signature,'base64')))throw Error('软件发布签名无效');return envelope.payload;
}
function command(root,family,operation){return new Promise((resolve,reject)=>{
 const child=spawn(backend.python(),['-X','utf8',backend.entry(root),family,operation],{cwd:root,windowsHide:true,shell:false,env:{...process.env,PYTHONIOENCODING:'utf-8'}});
 let output='',finished=false;const finish=(e,r)=>{if(finished)return;finished=true;clearTimeout(timer);e?reject(e):resolve(r);};
 const timer=setTimeout(()=>{child.kill();finish(Error('更新检查超时，继续使用本地版本'));},120000);
 child.stdout.on('data',s=>{output+=s;if(output.length>2*1024*1024){child.kill();finish(Error('更新响应过大'));}});child.stderr.on('data',()=>{});
 child.on('error',()=>finish(Error('无法启动本地更新服务')));child.on('close',()=>{try{const r=JSON.parse(output);if(!r.ok)throw Error(r.error);finish(null,r.data);}catch(e){finish(e);}});child.stdin.on('error',()=>{});child.stdin.end('{}');
});}
async function fetchManifest(url){
 // Electron's network stack respects the user's system proxy, unlike Node fetch.
 const response=await require('electron').net.fetch(url,{signal:AbortSignal.timeout(25000)});if(!response.ok)throw Error('软件版本检查失败：HTTP '+response.status);
 const reader=response.body.getReader();let size=0,chunks=[];
 while(true){const r=await reader.read();if(r.done)break;size+=r.value.length;if(size>1024*1024){await reader.cancel();throw Error('软件版本清单过大');}chunks.push(Buffer.from(r.value));}
 return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}
function createService({app,root,hasActiveTasks,updater,configuration,fetchRelease=fetchManifest,runCommand=command}){
 const cfg=configuration||JSON.parse(fs.readFileSync(path.join(process.env.FACTORY_ENGINE_HOME||path.resolve(__dirname,'..'),'distribution/update-config.json'),'utf8'));
 let state={state:'idle',version:cfg.app_version},checking=null,ready=false,timer=null,requestTimer=null,lastRequest='',installing=false,expected=null;
 const file=path.join(root,'.runtime/updates/software_status.json');
 function save(changes){state={...state,...changes,updated_at:Date.now()};fs.mkdirSync(path.dirname(file),{recursive:true});const temp=file+'.'+crypto.randomUUID()+'.tmp';fs.writeFileSync(temp,JSON.stringify(state));fs.renameSync(temp,file);}
 if(app.isPackaged){
  updater=updater||require('electron-updater').autoUpdater;
  updater.autoDownload=false;updater.autoInstallOnAppQuit=false;
  updater.setFeedURL({provider:'github',owner:cfg.owner,repo:cfg.software_repo,private:false});
  updater.on('error',()=>save({state:'error',message:'软件更新失败，保留当前版本'}));
  updater.on('download-progress',p=>save({state:'downloading',percent:Math.floor(p.percent)}));
  updater.on('update-downloaded',async event=>{
   try{
    if(!expected||event.version!==expected.version)throw Error('下载版本与签名清单不一致');
    const target=event.downloadedFile;
    if(!target)throw Error('缺少安装包路径');
    const hash=crypto.createHash('sha256');for await(const chunk of fs.createReadStream(target))hash.update(chunk);
    if(hash.digest('hex')!==expected.sha256)throw Error('安装包摘要与发布签名不一致');
    // Keep the verified installer for repair; never back up private runtime state into a release.
    const backup=path.join(root,'.runtime/updates/installers');fs.mkdirSync(backup,{recursive:true});
    fs.copyFileSync(target,path.join(backup,expected.version+'.exe'));
    const installed=path.dirname(app.getPath('exe')),previous=path.join(root,'.runtime/updates/previous-app',app.getVersion());
    const rel=path.relative(installed,previous);
    if(!rel.startsWith('..')&&!path.isAbsolute(rel))throw Error('恢复备份目录不能位于安装目录内');
    if(!backupFs.existsSync(previous)){
     const temporary=previous+'.'+crypto.randomUUID()+'.pending';
     await backupFs.promises.cp(installed,temporary,{recursive:true,errorOnExist:true,force:false});
     await backupFs.promises.rename(temporary,previous);
    }
    ready=true;save({state:'ready',message:'已下载并验证，退出且任务结束后安装',target_version:event.version});
   }catch(e){ready=false;save({state:'error',message:e.message});}
  });
  app.on('before-quit',event=>{
   if(!ready||installing)return;
   if(hasActiveTasks()){save({state:'ready',message:'后台仍有任务，本次退出不安装更新'});return;}
   const lock=path.join(root,'.runtime/task-admin.lock'),marker=path.join(root,'.runtime/updates/installing.json');let owned=false;
   try{
    const fd=fs.openSync(lock,'wx');owned=true;fs.writeFileSync(fd,JSON.stringify({pid:process.pid,created_at:new Date().toISOString()}));fs.closeSync(fd);
    if(hasActiveTasks()){save({state:'ready',message:'任务刚刚启动，暂不安装更新'});return;}
    fs.writeFileSync(marker,JSON.stringify({version:expected.version,previous:app.getVersion(),created_at:Date.now()}));
    event.preventDefault();installing=true;save({state:'installing'});updater.quitAndInstall(true,true);
   }catch(e){installing=false;if(owned)fs.rmSync(marker,{force:true});save({state:ready?'ready':'error',message:'本地操作尚未结束或安装未启动，保留当前版本'});}
   finally{if(owned)fs.rmSync(lock,{force:true});}
  });
 }
 async function checkSoftware(){
  if(!app.isPackaged){save({state:'development',message:'源码模式不下载或安装软件更新'});return state;}
  if(!Object.keys(cfg.public_keys).length)throw Error('尚未配置发布验证公钥');
  const signed=await fetchRelease(`http<local-path>`);
  const payload=verify(signed,cfg.public_keys);
  if(payload.kind!=='software'||!/^\d+\.\d+\.\d+$/.test(payload.version)||!/^[0-9a-f]{64}$/.test(payload.sha256))throw Error('软件发布清单格式无效');
  expected=payload;ready=false;save({state:'checking'});
  const result=await updater.checkForUpdates();
  if(result?.isUpdateAvailable===false||result?.updateInfo?.version===app.getVersion()){save({state:'current'});return state;}
  if(result?.updateInfo?.version!==payload.version)throw Error('GitHub 软件版本与签名清单不一致');
  await updater.downloadUpdate();return state;
 }
 function check(){if(checking)return checking;checking=(async()=>{
  const results=await Promise.allSettled([checkSoftware(),runCommand(root,'rules','sync')]);
  if(results[0].status==='rejected')save({state:'error',message:results[0].reason.message});
  return status();
 })().finally(()=>checking=null);return checking;}
 async function status(){return {...await runCommand(root,'updates','status'),software:state};}
 function start(){check().catch(()=>{});timer=setInterval(()=>check().catch(()=>{}),cfg.check_interval_hours*3600000);timer.unref();
  requestTimer=setInterval(()=>{try{const req=JSON.parse(fs.readFileSync(path.join(root,'.runtime/updates/check_request.json'),'utf8'));if(req.id!==lastRequest){lastRequest=req.id;check().catch(()=>{});}}catch{}},2000);requestTimer.unref();
 }
 return {start,check,status,syncRules:()=>runCommand(root,'rules','sync'),stop:()=>{clearInterval(timer);clearInterval(requestTimer);},getState:()=>state};
}
module.exports={createService,command,verify,canonical};
