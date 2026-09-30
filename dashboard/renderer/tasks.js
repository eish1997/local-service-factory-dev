/* Same public task commands as Agent; disk is the source of truth. */
(() => {
 const el=id=>document.getElementById(id), node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const titles={cover:'封面',triptych_panel:'三拼素材',triptych:'三拼图',detail:'详情'};
 const states={cancelled:'已取消',approved:'审核通过 · 待交付',needs_fix:'审核未通过 · 待处理',prompt_ready:'提示词已准备',queued:'排队中',running:'生成中',paused:'已暂停',interrupted:'任务中断',failed:'执行失败',failed_to_start:'启动失败',completed:'请求已完成',generated:'图片已生成 · 待审核'};
 let category='road_rescue',batch='',current=null,chosen=new Set(),planned=null,busy=false,reading=false,stamp='',epoch=0,initialized=false;
 const opened=new Set(),prompts=new Map();
 let autoChoose=true,refreshPending=false;
 const scroller=()=>document.querySelector('.content-scroll');
 function taskButtons(){const t=current?.tasks.find(t=>t.id===el('task-target').value);el('task-pause').disabled=busy||!t||!['running','queued'].includes(t.status);el('task-resume').disabled=busy||!t||['running','queued','completed','cancelled'].includes(t.status);el('task-retry').disabled=el('task-resume').disabled||!Object.values(t?.results||{}).some(r=>r.status==='failed');}
 const call=(op,p={})=>window.roadRescue.tasks(op,{category,...p});
 const message=(s,error=false)=>{el('task-message').textContent=s;el('task-message').classList.toggle('error',error);if(el('task-create-dialog').open&&error)el('task-create-error').textContent=s;};
 function invalidate(){el('task-package').disabled=!chosen.size;planned=null;el('task-start').disabled=true;el('task-plan-info').hidden=true;el('task-selection').textContent=`已选择 ${chosen.size} 组`;el('task-plan').disabled=!chosen.size;}
 async function action(fn){if(busy)return;busy=true;taskButtons();el('task-assemble').disabled=true;el('task-plan').disabled=true;el('task-start').disabled=true;try{await fn();}catch(e){message(e.message,true);}finally{busy=false;el('task-assemble').disabled=false;el('task-plan').disabled=!chosen.size;el('task-start').disabled=!planned||Boolean(planned.blocks.length);taskButtons();}}
 window.dashboardSelectedGroups=()=>[...chosen].sort((a,b)=>a-b);
 window.dashboardTaskContext=()=>({category,batch:batch||'legacy'});window.refreshTaskLibrary=()=>{chosen.clear();invalidate();prompts.clear();stamp='';refresh();};
 function setBatch(value){batch=value;message(value?'正在读取本地批次…':'选择业务后，可组装完整内容组；也可查看已有图片。');epoch++;chosen.clear();opened.clear();prompts.clear();stamp='';current=null;invalidate();el('gallery').hidden=Boolean(batch);el('task-actions').hidden=!batch;el('task-cards').replaceChildren();el('task-jobs').replaceChildren();}
 async function refresh(){if(reading){refreshPending=true;return;}reading=true;const ticket=epoch,cat=category;try{
   const rows=await call('batches');if(ticket!==epoch||cat!==category)return;if(batch&&!rows.some(b=>b.id===batch)){setBatch(rows[0]?.id||'');refreshPending=true;return;}
   if(autoChoose){autoChoose=false;if(rows.length){setBatch(rows[0].id);refreshPending=true;return;}}
   const select=el('task-batch');select.replaceChildren();const old=node('option','历史批次');old.value='';select.append(old);
   for(const b of rows){const o=node('option',`${b.name||`${b.phone||'历史批次'} · ${b.visible_count??b.count} 组`} · ${new Date(b.created_at).toLocaleString('zh-CN')} · ${b.source==='dashboard'?'看板':'Agent'}${b.status==='ready'?'':b.status==='failed'?' · 组装失败':` · 已组装 ${b.completed_groups} 组`}`);o.value=b.id;select.append(o);}select.value=batch;
   const list=el('task-batch-list'),scroll=list.parentElement.scrollTop;list.replaceChildren();
   const legacy=node('button','历史批次','batch-row'+(!batch?' selected':''));legacy.onclick=()=>{autoChoose=false;setBatch('');refresh();};legacy.dataset.batch='legacy';if(window.dashboardData?.groups.some(g=>g.projectId===category&&!g.libraryBatch))list.append(legacy);
   for(const b of rows){const button=node('button',undefined,'batch-row'+(b.id===batch?' selected':''));button.dataset.batch=b.id;button.append(node('strong',b.phone||'历史批次'),node('small',`${b.visible_count??b.count} 组 · ${b.status==='ready'?'提示词已就绪':b.status==='failed'?'组装失败':'组装中'}`),node('small',new Date(b.created_at).toLocaleString('zh-CN')));button.onclick=()=>{autoChoose=false;setBatch(b.id);refresh();};list.append(button);}list.parentElement.scrollTop=scroll;
   if(!batch)return;
   const data=await call('view',{batch,limit:100,include_prompts:false});if(ticket!==epoch||cat!==category)return;
   current=data;const next=JSON.stringify(data);if(next!==stamp){stamp=next;render(data);if(data.batch.status==='ready'&&!busy)message(`当前批次 ${data.batch.visible_count??data.batch.count} 组、${data.batch.prompt_count} 条提示词，均已保存到本地。`);}
   if(data.batch.status==='assembling')message(`正在本地组装：${data.batch.completed_groups}/${data.batch.visible_count??data.batch.count} 组`);
   else if(data.batch.status==='failed')message(`组装失败：${data.batch.error}`,true);
 }catch(e){message(e.message,true);}finally{reading=false;if(refreshPending||ticket!==epoch||cat!==category){refreshPending=false;queueMicrotask(refresh);}}}
 function imageDialog(images,index){const dialog=node('dialog',undefined,'task-image-dialog'),img=node('img');let i=index;const count=node('span');function show(){img.src=images[i].url;count.textContent=`${i+1}/${images.length}`;}const prev=node('button','上一张'),next=node('button','下一张'),close=node('button','关闭');prev.onclick=()=>{i=(i+images.length-1)%images.length;show();};next.onclick=()=>{i=(i+1)%images.length;show();};close.onclick=()=>dialog.close();dialog.append(img,prev,count,next,close);dialog.onclose=()=>dialog.remove();document.body.append(dialog);show();dialog.showModal();}
 async function fillPrompt(group,body){
   const key=`${category}/${batch}/${group}`;const ticket=epoch;
   try{let row=prompts.get(key);if(!row){const value=await call('view',{batch,offset:group-1,limit:1,include_prompts:true});row=value.groups[0];if(ticket!==epoch)return;prompts.set(key,row);}body.replaceChildren();
     for(const u of row.units){const section=node('section'),title=node('h4',`${u.position}. ${titles[u.kind]}${u.panel_index?' '+u.panel_index:''}${u.service_role?' · '+u.service_role:''}`),pre=node('pre',u.prompt),copy=node('button','复制提示词');copy.onclick=async()=>{try{await navigator.clipboard.writeText(u.prompt);copy.textContent='已复制';}catch{message('复制失败，可选中文字复制',true);}};section.append(title,copy,pre);body.append(section);}
   }catch(e){body.textContent=e.message;}
 }
 function render(data){
   const top=scroller().scrollTop;const root=el('task-cards');root.replaceChildren();
   const summary=node('p',`${data.batch.name||`${data.batch.phone||'历史批次'} · ${data.batch.visible_count??data.batch.count} 组`} · ${data.batch.prompt_count||'组装中'} 条提示词 · 规则版本 ${data.batch.revision} · ${new Date(data.batch.created_at).toLocaleString('zh-CN')}`,'task-meta');root.append(summary);
   const allImages=data.groups.flatMap(g=>g.images);
   for(const g of data.groups){
     const filters={pending:['prompt_ready'],active:['queued','running'],failed:['failed','failed_to_start','interrupted','paused','needs_fix'],review:['generated'],completed:['approved','completed']};if(el('task-filter').value&&!filters[el('task-filter').value].includes(g.status))continue;
     const card=node('section',undefined,'task-card');card.dataset.group=g.group;
     const header=node('div',undefined,'task-card-head'),label=node('label'),check=node('input');check.type='checkbox';check.checked=chosen.has(g.group);check.onchange=()=>{check.checked?chosen.add(g.group):chosen.delete(g.group);invalidate();};label.append(check,node('strong',`第 ${g.group} 组`));header.append(label,node('span',states[g.status]||g.status));card.append(header);
     const images=node('div',undefined,'task-images'),slots=new Map();for(const u of g.units)slots.set(u.delivery_position,u.kind==='triptych_panel'?'triptych':u.kind);
     for(const [position,kind]of slots){const item=node('button',undefined,'task-image'),existing=g.images.find(i=>i.position===position);item.dataset.position=position;if(existing){const img=node('img');img.src=existing.url;img.loading='lazy';item.append(img);item.onclick=()=>imageDialog(allImages,allImages.findIndex(i=>i.path===existing.path));}else{item.append(node('span','尚未生成'));item.setAttribute('aria-disabled','true');}item.append(node('small',`${position}. ${titles[kind]}${existing?' · '+(existing.review==='approved'?'已审核':['needs_fix','rejected'].includes(existing.review)?'待修复':'待审核'):''}`));images.append(item);}
     card.append(images);
     const details=node('details'),body=node('div',undefined,'task-prompts');details.append(node('summary',`查看本组 ${g.units.length} 条提示词`),body);details.open=opened.has(g.group);
     if(details.open)fillPrompt(g.group,body);
     details.ontoggle=()=>{if(details.open){opened.add(g.group);fillPrompt(g.group,body);}else opened.delete(g.group);};card.append(details);root.append(card);
   }
   const jobs=el('task-jobs');jobs.replaceChildren();
   for(const t of data.tasks){const row=node('div',undefined,'task-job');row.append(node('span',`${states[t.status]||t.status} · ${t.groups.length} 组 · 请求 ${t.requests_used}/${t.max_requests}${t.error?' · '+t.error:''}`));if(!['running','queued','completed','cancelled'].includes(t.status)){const b=node('button');b.append(window.dashboardIcon('step-forward'));b.title='继续原任务';b.setAttribute('aria-label','继续原任务');b.onclick=()=>action(async()=>{const saved=await call('resume',{batch,task:t.id,batch:t.batch||batch});message('已继续原任务，使用剩余预算');await refresh();});row.append(b);}jobs.append(row);}
   const select=el('task-target'),selectedTask=select.value;select.replaceChildren();select.disabled=!data.tasks.length;if(!data.tasks.length){const empty=node('option','暂无任务');empty.value='';select.append(empty);}for(const t of data.tasks){const option=node('option',`${states[t.status]||t.status} · ${t.groups.length} 组`);option.value=t.id;select.append(option);}if(data.tasks.some(t=>t.id===selectedTask))select.value=selectedTask;taskButtons();
   if(!root.querySelector('.task-card'))root.append(node('p','没有符合当前筛选条件的内容组。','task-meta'));
   scroller().scrollTop=top;
 }
 el('task-batch').onchange=()=>{setBatch(el('task-batch').value);refresh();};
 el('task-refresh').onclick=()=>refresh();
 el('task-select-all').onclick=()=>{chosen=new Set(current?.groups.map(g=>g.group)||[]);invalidate();if(current)render(current);};
 el('task-clear').onclick=()=>{chosen.clear();invalidate();if(current)render(current);};
 el('task-new').onclick=()=>{el('task-phone').value='';el('task-create-error').textContent='';el('task-create-dialog').showModal();el('task-phone').focus();};
 for(const id of ['task-create-close','task-create-cancel'])el(id).onclick=()=>{if(!busy)el('task-create-dialog').close();};
 el('task-create-dialog').addEventListener('cancel',e=>{if(busy)e.preventDefault();});
 el('task-create-form').onsubmit=e=>{e.preventDefault();action(async()=>{
   const count=Number(el('task-count').value);if(!Number.isInteger(count)||count<1||count>100)throw Error('请输入 1–100 组');
   const phone=el('task-phone').value.trim();if(!/^1[3-9][0-9]{9}$/.test(phone)){el('task-phone').focus();throw Error('请输入本批次的有效 11 位手机号');}
   const cat=category;message(`正在组装 ${count} 个完整组并保存到本地，不调用生图接口…`);
   const b=await call('assemble',{count,phone,request_id:crypto.randomUUID()});if(cat!==category)return;
   el('task-create-dialog').close();autoChoose=false;setBatch(b.id);await refresh();message(`已保存 ${b.visible_count??b.count} 组、${b.prompt_count} 条提示词。选择内容组后可查看执行信息。`);
 });};
 el('task-filter').onchange=()=>{if(current)render(current);};el('task-target').onchange=taskButtons;
 for(const op of ['pause','resume','retry'])el('task-'+op).onclick=()=>action(async()=>{const task=el('task-target').value;if(!task)throw Error('请选择任务');const selected=current.tasks.find(t=>t.id===task);await call(op,{batch:selected?.batch||batch,task});await refresh();message(op==='pause'?'已请求暂停调度，已发出的请求继续收尾。':op==='retry'?'已在原预算内重试允许恢复的失败项。':'已继续原任务，沿用剩余预算。');});
 el('task-plan').onclick=()=>action(async()=>{
   if(!chosen.size)throw Error('请先选择内容组');const ticket=epoch;
   const result=await call('plan',{batch,groups:[...chosen].sort((a,b)=>a-b)});if(ticket!==epoch)return;planned=result;
   el('task-plan-info').hidden=false;el('task-plan-info').textContent=`本次 ${result.group_count} 组 · 待请求 ${result.pending_count} 张 · 复用 ${result.reused_count} 张 · 请求上限 ${result.max_requests} 次 · 模型 ${result.config.model||'未就绪'} · 密钥并发上限 ${result.max_workers} 路。${result.blocks.length?'无法执行：'+result.blocks.join('；'):'点击执行将使用已配置 API，按所示范围产生费用。'}`;
 });
 el('task-start').onclick=()=>action(async()=>{
   if(!planned||planned.blocks.length)throw Error('请先取得有效执行信息');
   const key='task-request-'+planned.plan_sha256;let id=localStorage.getItem(key);if(!id){id=crypto.randomUUID();localStorage.setItem(key,id);}
   const saved=await call('start',{batch,groups:planned.groups,plan_sha256:planned.plan_sha256,request_id:id,authorization:'execute_selected_groups'});
   invalidate();message('所选内容组已提交生成；关闭看板不会中断任务。');await refresh();
 });
 window.showSavedGroupPrompts=async details=>{
  if(details.dataset.loaded)return;const body=details.querySelector('div');
  try{const cat=details.dataset.category,g=Number(details.dataset.group),b=details.dataset.batch;
   const value=await window.roadRescue.tasks(b?'view':'legacy-group',{category:cat,batch:b,group:g,offset:g-1,limit:1});
   const row=b?value.groups[0]:value;body.replaceChildren(node('p',row.note||'已冻结的本地提示词'));
   for(const u of row.units){body.append(node('h4',`${u.position}. ${titles[u.kind]||u.kind}`),node('pre',u.prompt));}
   details.dataset.loaded='1';
  }catch(e){body.textContent=e.message;}
 };
 window.addEventListener('dashboard-project',e=>{category=e.detail;autoChoose=true;el('task-filter').value='';setBatch('');refresh();});
 window.addEventListener('dashboard-refresh',e=>{if(!initialized||category!==e.detail){initialized=true;category=e.detail;autoChoose=true;setBatch('');refresh();}});
 setInterval(()=>{if(!el('gallery-panel').hidden&&!document.hidden)refresh();},5000);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!el('gallery-panel').hidden)refresh();});
})();
