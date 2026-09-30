const {spawn}=require('child_process');
const path=require('path');
const {pathToFileURL}=require('url');
const allowed=new Set(['projects','assemble','batches','view','plan','start','resume','pause','retry','delete','replacement-prepare','keys-view','keys-save','legacy-group','assets-view','assets-save','open-folder','package']);
function runTasks(root,operation,request={}){
  return new Promise((resolve,reject)=>{
    if(!allowed.has(operation)||!request||typeof request!=='object'||Array.isArray(request))return reject(Error('不支持的任务请求'));
    const payload=JSON.stringify({...request,source:'dashboard'});
    if(operation!=='keys-save'&&Buffer.byteLength(payload)>65536)return reject(Error('任务请求过大'));
    const child=spawn(require('./backend').python(),['-X','utf8',require('./backend').entry(root),'tasks',operation],{cwd:root,windowsHide:true,shell:false,detached:operation==='assemble',env:{...process.env,PYTHONIOENCODING:'utf-8'}});
    let output='',errors='',settled=false;
    const done=(error,value)=>{if(settled)return;settled=true;clearTimeout(timer);error?reject(error):resolve(value);};
    // Assembly owns disk state and must survive window closure; only reads time out.
    const timer=setTimeout(()=>{if(operation!=='assemble')child.kill();done(Error('本地任务仍在处理，请刷新查看磁盘状态'));},['assemble','package'].includes(operation)?600000:60000);
    child.stdout.setEncoding('utf8');child.stderr.setEncoding('utf8');
    child.stdout.on('data',s=>{output+=s;if(output.length>16*1024*1024)done(Error('结果过大，请分页读取'));});
    child.stderr.on('data',s=>{errors=(errors+s).slice(-1000);});
    child.on('error',e=>done(Error('无法运行本地任务工具：'+e.message)));
    child.on('close',(code)=>{try{const r=JSON.parse(output.trim());if(!r.ok)throw Error(r.error);if(operation==='view')for(const g of r.data.groups)for(const i of g.images){if(!require('./assets').inside(require('./assets').batchOutput(root,request.category,request.batch),i.path))throw Error('图片路径越界');i.url=pathToFileURL(i.path).href;}done(null,r.data);}catch(e){const missing=errors.match(/ModuleNotFoundError: No module named '([a-zA-Z0-9_.]+)'/);done(Error(output.trim().startsWith('{')?e.message:missing?`本地 Python 缺少依赖 ${missing[1]}，请修复开发环境后重启看板`:`本地任务没有返回有效结果（退出码：${code}）`));}});
    child.stdin.on('error',()=>{});child.stdin.end(payload);
  });
}
function readLibraryJobs(root){
 const fs=require('fs'),result=[];const home=path.join(root,'prompts','library');
 if(!fs.existsSync(home))return result;
 for(const category of fs.readdirSync(home,{withFileTypes:true}).filter(d=>d.isDirectory())){
  const c=path.join(home,category.name);
  for(const batch of fs.readdirSync(c,{withFileTypes:true}).filter(d=>d.isDirectory()&&d.name.startsWith('batch_'))){
   const tasks=path.join(c,batch.name,'tasks');if(!fs.existsSync(tasks))continue;
   for(const task of fs.readdirSync(tasks,{withFileTypes:true}).filter(d=>d.isDirectory())){
    try{const data=JSON.parse(fs.readFileSync(path.join(tasks,task.name,'task.json'),'utf8'));
     result.push({...data,job_id:data.id,job_type:'shared-task',project_id:category.name,category_id:category.name,batch_id:batch.name,
      group_start:Math.min(...data.groups),group_count:data.groups.length,api_key_slots:data.slots,
      requested_count:data.total_units,completed:data.completed_units||data.reused_units||0,
      request_budget:data.max_requests,reused:data.reused_units||0,generated:Object.values(data.results||{}).filter(r=>r.status==='generated').length,model:data.config.model,quality:data.config.quality,size:data.config.api_size,
      failed:Object.values(data.results||{}).filter(r=>r.status==='failed').length});
    }catch{}
   }
  }
 }
 return result;
}
module.exports={runTasks,readLibraryJobs};
