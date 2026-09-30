/* Every mutation uses the same public factory commands as Agent. */
(() => {
 const $=id=>document.getElementById(id),node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
 const api=(op,request={})=>window.roadRescue.tasks(op,request);
 const context=()=>window.dashboardTaskContext();
 function modal(title){const d=node('dialog');d.className='action-dialog';const head=node('header'),h=node('h2',title),x=node('button');x.append(window.dashboardIcon('x'));x.title='关闭';x.onclick=()=>d.close();head.append(h,x);d.append(head);const error=node('p');error.className='action-error';const body=node('div');d.append(body,error);d.addEventListener('close',()=>d.remove());document.body.append(d);d.showModal();return {d,body,error};}
 function report(text){$('task-message').textContent=text;}
 async function refreshAll(){window.refreshTaskLibrary?.();window.dispatchEvent(new Event('dashboard-admin-refresh'));}
 const menu=node('div');menu.className='context-menu';menu.hidden=true;document.body.append(menu);
 document.addEventListener('click',()=>menu.hidden=true);window.addEventListener('blur',()=>menu.hidden=true);document.addEventListener('keydown',e=>{if(e.key==='Escape')menu.hidden=true;});
 document.addEventListener('contextmenu',e=>{
  const project=e.target.closest('.project-tab'),batch=e.target.closest('.batch-row'),image=e.target.closest('.task-image,.thumb'),group=e.target.closest('.task-card,.group-row');
  if(!project&&!batch&&!group)return;e.preventDefault();menu.replaceChildren();
  const request={...context()};let label,scope;
  if(project){scope='project';request.category=project.dataset.project;label=project.textContent;}
  else if(batch){scope='batch';request.batch=batch.dataset.batch||'legacy';label='此批次';}
  else{request.group=Number(group.dataset.group);scope=image?'image':'group';if(image)request.position=Number(image.dataset.position);label=image?'这张图片及其占位':`第 ${request.group} 组`;}
  const remove=node('button','删除'+(scope==='project'?'项目':scope==='batch'?'批次':scope==='group'?'组':'图片'));remove.onclick=()=>deleteDialog({...request,scope},label);menu.append(remove);
  if(image){const regenerate=node('button','重新组装并生成此图');regenerate.onclick=()=>replacement({...request},image.querySelector('img')!==null);menu.append(regenerate);}
  const open=node('button','打开对应文件夹');open.onclick=async()=>{try{await window.roadRescue.openTaskFolder({...request,scope});}catch(e){report(e.message);}};menu.append(open);
  if(scope==='batch'||scope==='group'){const pack=node('button',scope==='batch'?'打包此批次':'打包此组');pack.onclick=()=>packageGroups({...request,groups:scope==='group'?[request.group]:undefined});menu.append(pack);}
  menu.hidden=false;menu.style.left=Math.min(e.clientX,window.innerWidth-225)+'px';menu.style.top=Math.min(e.clientY,window.innerHeight-menu.offsetHeight-8)+'px';
 });
 async function packageGroups(request){
  const button=$('task-package');button.disabled=true;
  try{report('请选择压缩包保存位置…');const result=await window.roadRescue.packageGroups(request);report(result?`已打包 ${result.groups.length} 组、${result.images} 张图片，${result.paths.length} 个压缩包：${result.paths.join("；")}。审核状态不变。`:'已取消打包');}
  catch(e){report('打包失败：'+e.message);}finally{button.disabled=!window.dashboardSelectedGroups?.().length;}
 }
 $('task-package').onclick=()=>packageGroups({...context(),groups:window.dashboardSelectedGroups()});
 $('open-folder').onclick=async()=>{
  try{const result=await window.roadRescue.chooseAssets();if(result){report(`资产路径已更新：${result.path}。Agent 与看板共用，新批次生效。`);$('open-folder').title='资产路径：'+result.path;await refreshAll();}}
  catch(e){report(e.message);}
 };
 api('assets-view').then(s=>$('open-folder').title='设置资产路径：'+s.path).catch(()=>{});
 function deleteDialog(request,label){
  const {d,body,error}=modal('删除'+(request.scope==='project'?'项目':label));
  body.append(node('p',`将永久删除${request.scope==='project'?label+'项目的配置、批次与图片':label}。删除后无法从看板或 Agent 找回。`));
  let input;if(request.scope==='project'){const phrase='删除'+label+'项目';body.append(node('p','请输入「'+phrase+'」确认：'));input=node('input');input.autocomplete='off';input.placeholder=phrase;body.append(input);}
  const button=node('button','确认删除');button.className='danger-action';button.disabled=Boolean(input);
  if(input)input.oninput=()=>button.disabled=input.value!=='删除'+label+'项目';
  button.onclick=async()=>{button.disabled=true;try{await api('delete',{...request,authorization:'delete_selected',confirmation:input?.value});d.close();await refreshAll();report('删除完成');}catch(e){error.textContent=e.message;button.disabled=false;}};body.append(button);
 }
 async function replacement(request,hasImage){
  const {d,body,error}=modal('单图重生成');body.append(node('p','正在组装本图的新提示词并检查执行范围…'));
  try{
   const saved=await api('replacement-prepare',{...request,request_id:crypto.randomUUID()});
   const plan=await api('plan',{category:request.category,batch:saved.id,groups:[1]});
   const preview=await api('view',{category:request.category,batch:saved.id,limit:1,include_prompts:true});body.replaceChildren();
   body.append(node('p',`${plan.pending_count} 个生成单元 · 请求上限 ${plan.max_requests} 次 · 模型 ${plan.config.model||'未配置'}。${hasImage?'生成成功后替换原图，失败保留原图。':'生成成功后填入此占位。'}`));
   for(const u of preview.groups[0].units){const detail=node('details');detail.append(node('summary','新提示词'),node('pre',u.prompt));body.append(detail);}
   if(plan.blocks.length)error.textContent=plan.blocks.join('；');
   const button=node('button','重新生成并替换');button.className='primary-action';button.disabled=Boolean(plan.blocks.length);button.onclick=async()=>{button.disabled=true;try{await api('start',{category:request.category,batch:saved.id,groups:[1],request_id:'replace-'+saved.id,plan_sha256:plan.plan_sha256,authorization:'execute_selected_groups'});d.close();await refreshAll();report('单图重生成已提交，成功后替换原位置。');}catch(e){error.textContent=e.message;button.disabled=false;}};body.append(button);
  }catch(e){error.textContent=e.message;}
 }
 $('update-settings').onclick=async()=>{
  const {d,body,error}=modal('版本与更新');
  const summary=node('p','正在读取版本…'),message=node('p'),check=node('button','检查软件与规则更新'),sync=node('button','刷新项目规则');
  body.append(summary,message,check,sync);let timer;
  async function render(){try{const s=await window.roadRescue.updates('status');summary.textContent=`软件 ${s.software_version} · 规则 ${s.rules_version==='workspace'?'本地编辑':s.rules_version} · ${s.mode==='maintainer'?'维护端':'使用端'}`;const states={idle:'等待检查',checking:'正在检查',downloading:'正在下载',ready:'等待安全退出后更新',error:'更新未完成'};message.textContent=[s.software?.message||states[s.software?.state]||s.software?.state,s.rules_status?.message||states[s.rules_status?.state]||s.rules_status?.state,s.rules_status?.checked_at?'上次检查 '+new Date(s.rules_status.checked_at*1000).toLocaleString():'尚未检查'].filter(Boolean).join(' · ');}catch(e){error.textContent=e.message;}}
  async function run(op){check.disabled=sync.disabled=true;error.textContent='';try{await window.roadRescue.updates(op);await refreshAll();}catch(e){error.textContent=e.message;}finally{check.disabled=sync.disabled=false;await render();}}
  check.onclick=()=>run('check');sync.onclick=()=>run('syncRules');await render();timer=setInterval(render,3000);d.addEventListener('close',()=>clearInterval(timer));
 };
 $('key-settings').onclick=async()=>{
  const {d,body,error}=modal('渠道与密钥');body.append(node('p','正在读取已配置渠道…'));
  try{
   const settings=await api('keys-view');body.replaceChildren();const select=node('select');select.setAttribute('aria-label','渠道');
   for(const c of settings.channels){const option=node('option',c.name);option.value=c.id;select.append(option);}select.value=settings.active;body.append(select);
   const description=node('p'),rows=node('div'),add=node('button','＋ 添加一行'),save=node('button','保存并使用此渠道');rows.className='key-list';save.className='primary-action';const footer=node('footer');footer.append(add,save);body.append(description,rows,footer);
   const drafts=new Map();let previous=select.value;
   function collect(){return [...rows.children].map(row=>({value:row.querySelector('input').value,keep_slot:Number(row.dataset.slot)||undefined}));}
   function addRow(entry={}){const row=node('div');row.className='key-row';row.dataset.slot=entry.keep_slot||'';const input=node('input');input.type='password';input.autocomplete='new-password';input.spellcheck=false;input.value=entry.value||'';input.placeholder=entry.keep_slot?'填写新密钥可替换，留空保留':'输入密钥';if(entry.keep_slot){const saved=node('span',`●●●●●● · 密钥 ${entry.keep_slot} 已保存`);saved.className='key-saved';row.append(saved);}const remove=node('button');remove.title='移除此密钥行';remove.setAttribute('aria-label','移除此密钥行');remove.append(window.dashboardIcon('x'));remove.onclick=()=>row.remove();row.append(input,remove);rows.append(row);}
   function render(){rows.replaceChildren();const channel=settings.channels.find(c=>c.id===select.value);description.textContent=`已保存 ${channel.slots.length} 个密钥 · ${channel.model||'使用项目模型'} · 每个有效密钥对应一路并发，数量不限，保存时查重。密钥仅保存在本机，不回显原文。`;for(const entry of drafts.get(channel.id)||channel.slots.map(s=>({keep_slot:s.slot})))addRow(entry);}
   select.onchange=()=>{drafts.set(previous,collect());previous=select.value;render();};add.onclick=()=>addRow();render();
   save.onclick=async()=>{save.disabled=true;error.textContent='';try{await api('keys-save',{channel:select.value,revision:settings.revision,rows:collect()});d.close();await refreshAll();report('密钥池已保存，Agent 与看板共用此配置。');}catch(e){error.textContent=e.message;save.disabled=false;}};
  }catch(e){error.textContent=e.message;}
 };
})();
