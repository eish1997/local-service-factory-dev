const fs=require('fs'),path=require('path'),{spawnSync}=require('child_process');
function initialize(app,resources=process.resourcesPath){
 const engine=path.join(resources,'engine'),python=path.join(resources,'python','python.exe');
 if(!fs.existsSync(path.join(engine,'factory.py'))||!fs.existsSync(python))throw Error('安装不完整：缺少独立生成引擎，请重新安装');
 const root=path.join(app.getPath('userData'),'workspace');
 for(const part of ['.runtime/updates','prompts/library','output','projects'])fs.mkdirSync(path.join(root,part),{recursive:true});
 const prepared=spawnSync(python,['-X','utf8',path.join(engine,'factory.py'),'rules','bootstrap'],{cwd:root,input:'{}',encoding:'utf8',windowsHide:true,timeout:90000,env:{...process.env,FACTORY_DATA_HOME:root,PYTHONIOENCODING:'utf-8'}});
 let result;try{result=JSON.parse(prepared.stdout);}catch{throw Error('无法准备兼容规则，请检查安装完整性后重试');}
 if(prepared.status!==0||!result.ok)throw Error('无法准备兼容规则：'+(result.error||'本地更新操作尚未结束，请重试'));
 const env=path.join(root,'.env');
 if(!fs.existsSync(env))fs.writeFileSync(env,'FACTORY_KEY_POOL_MANAGED=1\nOPENAI_PROVIDER=relay\nOPENAI_BASE_URL=https://tinysnow.one/v1\nOPENAI_IMAGE_MODEL=gpt-image-2.5-flare\nOPENAI_API_KEY=\n',{flag:'wx'});
 process.env.FACTORY_DATA_HOME=root;process.env.FACTORY_ENGINE_HOME=engine;process.env.ROAD_RESCUE_PYTHON=python;
 process.env.FACTORY_INSTALL_HOME=path.dirname(app.getPath('exe'));
 // Reaching a validated engine on a normal launch completes (or recovers) installation.
 const installing=path.join(root,'.runtime/updates/installing.json');
 if(fs.existsSync(installing)){
  const prior=JSON.parse(fs.readFileSync(installing,'utf8'));
  fs.writeFileSync(path.join(root,'.runtime/updates/install-result.json'),JSON.stringify({expected:prior.version,actual:app.getVersion(),recovered:prior.version!==app.getVersion(),at:Date.now()}));
  fs.unlinkSync(installing);
 }
 return root;
}
function registry(root){
 let base=process.env.FACTORY_ENGINE_HOME||root;
 if(process.env.FACTORY_DATA_HOME){
  const pointer=path.join(root,'.runtime/updates/active_rules.json');
  if(fs.existsSync(pointer)){const version=JSON.parse(fs.readFileSync(pointer,'utf8')).version;if(!/^[1-9][0-9]{0,19}$/.test(version))throw Error('规则指针无效');base=path.join(root,'.runtime/rules',version);}
 }
 const file=path.join(base,'projects/registry.json');
 const value=JSON.parse(fs.readFileSync(file,'utf8'));
 const hiddenPath=path.join(root,'.runtime/hidden_projects.json'),hidden=fs.existsSync(hiddenPath)?JSON.parse(fs.readFileSync(hiddenPath,'utf8')).projects:[];
 return {...value,projects:value.projects.filter(p=>!hidden.includes(p.id))};
}
module.exports={initialize,registry};
