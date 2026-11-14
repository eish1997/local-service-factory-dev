/* Same public task commands as Agent; disk is the source of truth. */
(() => {
 const el=id=>document.getElementById(id), node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const titles={cover:'封面',triptych_panel:'三拼素材',triptych:'三拼图',detail:'详情'};
 const states={cancelled:'已取消',approved:'已审核',needs_fix:'待修复',prompt_ready:'待开始',queued:'排队中',running:'生成中',recovering:'自动补齐中',paused:'已暂停',interrupted:'待继续',failed:'待处理',failed_to_start:'无法启动',completed:'已完成',completed_with_errors:'待处理',generated:'待审核'};
 let category='road_rescue',batch='',current=null,chosen=new Set(),planned=null,busy=false,reading=false,stamp='',epoch=0,planVersion=0,initialized=false;
 let autoChoose=true,refreshPending=false;
 const scroller=()=>document.querySelector('.content-scroll');
 const nothingSafe=t=>t?.resume_summary?.ready_count===0&&t.resume_summary.blocked_count>0&&!t.local_render_errors?.length&&!(t.auto_complete?.enabled&&!t.auto_recovery?.finished);
 // Keep the submitted task locked until the backend reports a terminal state,
 // including the interval before the first refreshed view contains it.
 const submitted=new Map(),pausing=new Set();
 const batchKey=()=>JSON.stringify([category,batch]);
 function activeBatch(){
   return submitted.has(batchKey())||Boolean(current?.tasks.some(workingTask));
 }
 function eligibleTasks(op){
   const tasks=current?.tasks||[];
   if(op==='resume'&&activeBatch())return [];
   return tasks.filter(t=>op==='pause'?workingTask(t)&&!pausing.has(t.id):!workingTask(t)&&!['completed','cancelled'].includes(t.status)&&!nothingSafe(t));
 }
 function taskButtons(){
   for(const op of ['pause','resume'])el('task-'+op).disabled=busy||!eligibleTasks(op).length;
 }
 function continued(t,op){return op==='retry'?'已提交重试':'已继续任务';}
 const call=(op,p={})=>window.roadRescue.tasks(op,{category,...p});
 const message=(s,error=false)=>{window.dashboardMessage(el('task-message'),s,error);if(el('task-create-dialog').open&&error)window.dashboardMessage(el('task-create-error'),s,true);};
 function syncSelection(){
   const box=el('task-select-all'),groups=current?.groups||[];
   const selectedRows=groups.filter(g=>chosen.has(g.group)),selected=selectedRows.length;
   const complete=g=>new Set(g.units.map(u=>u.delivery_position)).size===g.images.length;
   const completeSelection=selected>0&&selectedRows.every(complete);
   const needsResume=current?.tasks.some(t=>['paused','interrupted'].includes(t.status)&&t.groups.some(g=>chosen.has(g)));
   const running=activeBatch();
   box.disabled=busy||!groups.length;
   box.checked=groups.length>0&&selected===groups.length;
   box.indeterminate=selected>0&&!box.checked;
   el('task-selection').textContent=`${current?.batch?.visible_count??current?.batch?.count??0} ( ${selected} ) 组`;
   const start=el('task-start');
   start.disabled=busy||running||!selected||completeSelection||needsResume;
   if(!busy)start.lastChild.textContent=running?'生成中…':'开始生成';
   start.title=running?'当前批次有生成任务':needsResume?'请继续原任务':completeSelection?'所选组已全部生成':'按待生成张数自动设置请求上限';
   el('task-package').disabled=busy||running||!completeSelection;
   for(const check of el('task-cards').querySelectorAll('input[type=checkbox]'))check.disabled=busy;
 }
 function invalidate(){planVersion++;el('task-package').disabled=!chosen.size;planned=null;el('task-start').disabled=true;el('task-plan-info').hidden=true;syncSelection();}
 window.runDashboardAction=fn=>action(fn);
 window.batchActionsLocked=()=>busy||activeBatch();
 async function action(fn){if(busy)return;busy=true;syncSelection();taskButtons();el('task-assemble').disabled=true;el('task-start').disabled=true;try{await fn();}catch(e){message(e.message,true);}finally{busy=false;el('task-assemble').disabled=false;syncSelection();taskButtons();}}
 window.dashboardSelectedGroups=()=>[...chosen].sort((a,b)=>a-b);
 window.dashboardTaskContext=()=>({category,batch:batch||'legacy'});window.refreshTaskLibrary=()=>{chosen.clear();invalidate();stamp='';refresh();};
 let startedTask=null;
 function setBatch(value){startedTask=null;batch=value;message(value?'加载中…':'选择批次，或点 ＋ 新建。');epoch++;chosen.clear();stamp='';current=null;invalidate();el('gallery').hidden=Boolean(batch);el('task-actions').hidden=!batch;el('task-cards').replaceChildren();el('task-jobs').replaceChildren();if(el('task-jobs-section').open)el('task-jobs-section').close('cancel');window.dispatchEvent(new CustomEvent('dashboard-batch',{detail:{category,batch:batch||'legacy'}}));}
 async function refresh(){if(reading){refreshPending=true;return;}reading=true;const ticket=epoch,cat=category;try{
   const rows=await call('batches');if(ticket!==epoch||cat!==category)return;if(batch&&!rows.some(b=>b.id===batch)){setBatch(rows[0]?.id||'');refreshPending=true;return;}
   if(autoChoose){autoChoose=false;if(rows.length){setBatch(rows[0].id);refreshPending=true;return;}}
   const select=el('task-batch');select.replaceChildren();const old=node('option','历史批次');old.value='';select.append(old);
   for(const b of rows){const o=node('option',`${b.name||`${b.phone||'历史批次'} · ${b.visible_count??b.count} 组`} · ${new Date(b.created_at).toLocaleString('zh-CN')} · ${b.source==='dashboard'?'看板':'Agent'}${b.status==='ready'?'':b.status==='failed'?' · 组装失败':` · 已组装 ${b.completed_groups} 组`}`);o.value=b.id;select.append(o);}select.value=batch;
   const list=el('task-batch-list'),scroll=list.parentElement.scrollTop;list.replaceChildren();
   const legacy=node('button','历史批次','batch-row'+(!batch?' selected':''));legacy.onclick=()=>{autoChoose=false;setBatch('');refresh();};legacy.dataset.batch='legacy';if(window.dashboardData?.groups.some(g=>g.projectId===category&&!g.libraryBatch))list.append(legacy);
   for(const b of rows){const button=node('button',undefined,'batch-row'+(b.id===batch?' selected':''));button.dataset.batch=b.id;button.append(node('strong',b.phone||'历史批次'),node('small',`${b.visible_count??b.count} 组${b.status==='ready'?'':b.status==='failed'?' · 创建失败':' · 创建中'}`),node('small',new Date(b.created_at).toLocaleString('zh-CN')));button.onclick=()=>{autoChoose=false;setBatch(b.id);refresh();};list.append(button);}list.parentElement.scrollTop=scroll;
   if(!batch)return;
   const data=await call('view',{batch,limit:100,include_prompts:false});if(ticket!==epoch||cat!==category)return;
   current=data;
   const submittedState=data.tasks.find(t=>t.id===submitted.get(batchKey()));
   if(submittedState&&!workingTask(submittedState))submitted.delete(batchKey());
   for(const t of data.tasks)if(!workingTask(t))pausing.delete(t.id);
   window.dispatchEvent(new CustomEvent('dashboard-task-data',{detail:{category,batch,groups:data.groups}}));const next=JSON.stringify(data);if(next!==stamp){stamp=next;render(data);const task=startedTask&&data.tasks.find(t=>t.id===startedTask);
     if(task){message(`${states[task.status]||task.status} · 已完成 ${task.completed_units||0}/${task.total_units||0} 张 · 请求 ${task.total_requests_used??task.requests_used??0}/${task.total_max_requests??task.max_requests}`);if(!workingTask(task))startedTask=null;}
     else if(data.batch.status==='ready'&&!busy&&!/打包/.test(el('task-message').textContent||''))message('');}
   if(data.batch.status==='assembling')message(`正在本地组装：${data.batch.completed_groups}/${data.batch.visible_count??data.batch.count} 组`);
   else if(data.batch.status==='failed')message(`组装失败：${data.batch.error}`,true);
 }catch(e){message(e.message,true);}finally{reading=false;if(refreshPending||ticket!==epoch||cat!==category){refreshPending=false;queueMicrotask(refresh);}}}
 function imageDialog(images,index){
   const dialog=node('dialog',undefined,'task-image-dialog version-viewer');
   dialog.setAttribute('aria-label','大图预览');
   const top=node('header',undefined,'preview-bar'),count=node('span',undefined,'preview-count');
   const main=node('div',undefined,'preview-main'),stage=node('div',undefined,'preview-stage');
   const img=node('img',undefined,'preview-photo'),side=node('aside',undefined,'image-history-sidebar');
   let i=index,ticket=0,dispose=null;
   const previewCategory=category,previewBatch=batch||'legacy';
   function button(label,icon,action){
     const b=node('button',undefined,'preview-icon');
     b.title=label;b.setAttribute('aria-label',label);b.append(window.dashboardIcon(icon));b.onclick=action;return b;
   }
   async function show(){
     const seq=++ticket,item=images[i];dispose?.();dispose=null;
     img.src=item.url;img.alt=`第 ${item.group} 组 · 第 ${item.position} 张`;
     count.textContent=`${i+1} / ${images.length}`;
     if(side.hidden)return;
     const cleanup=await window.mountImageHistory(side,{category:previewCategory,batch:previewBatch,group:item.group,position:item.position},async version=>{
       if(seq!==ticket)return;
       img.src=version.url;stamp='';refresh();
     });
     if(seq===ticket)dispose=cleanup;else cleanup();
   }
   function step(delta){i=(i+delta+images.length)%images.length;show();}
   const prev=button('上一张','chevron-right',()=>step(-1)),next=button('下一张','chevron-right',()=>step(1));
   prev.classList.add('preview-prev');next.classList.add('preview-next');
   prev.hidden=next.hidden=images.length<2;
   const history=button('历史版本','rotate-ccw',()=>{side.hidden=!side.hidden;history.setAttribute('aria-expanded',String(!side.hidden));show();});
   history.setAttribute('aria-expanded','false');side.hidden=true;
   top.append(count,history,button('关闭预览','x',()=>dialog.close()));
   stage.append(img,prev,next);main.append(stage,side);dialog.append(top,main);
   dialog.onkeydown=e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();step(e.key==='ArrowLeft'?-1:1);}};
   dialog.onclose=()=>{ticket++;dispose?.();dialog.remove();};
   document.body.append(dialog);dialog.showModal();show();
 }
 function deliveredKeys(groups){const ready=new Set();for(const g of groups||[])for(const image of g.images||[])if(image?.position!=null)ready.add(`${g.group}:${image.position}`);return ready;}
 function pendingLocal(t,groups){const ready=deliveredKeys(groups);return (t.local_render_errors||[]).filter(item=>!ready.has(`${item.group}:${item.position}`));}
 function workingTask(t){return ['running','queued','recovering'].includes(t.status);}
 function renderAutoDiagnostics(t,body,groups){
   const local=pendingLocal(t,groups);
   if(t.status==='completed'||workingTask(t))return;
   const blocked=t.auto_recovery?.blocked||[];
   if(!blocked.length&&!local.length)return;
   const details=node('details',undefined,'task-recovery task-auto-diagnostics');
   details.append(node('summary',`自动恢复记录 · ${blocked.length} 项补缺限制 · ${local.length} 张本地合成待处理`));
   for(const item of blocked)details.append(node('p',`第 ${item.group} 组 · 图片 ${item.position}${repairLabel(t,item.round)?' · '+repairLabel(t,item.round):''}：${item.reason}`));
   for(const item of local)details.append(node('p',`第 ${item.group} 组 · 图片 ${item.position}：本地合成失败，原图已保留${item.error?'（'+item.error+'）':''}`));
   body.append(details);
 }
 function repairLabel(t,number){return number?(t.auto_complete?.mode==='continuous'?`补齐尝试 ${number}`:`第 ${number} 轮补缺`):'';}
 function enableRowDrag(row){
   let drag=null,suppressClick=false;
   row.addEventListener('dragstart',e=>e.preventDefault());
   row.addEventListener('pointerdown',e=>{
     suppressClick=false;
     if(e.button!==0||e.pointerType==='touch'||row.scrollWidth<=row.clientWidth)return;
     drag={id:e.pointerId,x:e.clientX,left:row.scrollLeft};
   });
   row.addEventListener('pointermove',e=>{
     if(!drag||e.pointerId!==drag.id)return;
     if(!(e.buttons&1)){drag=null;return;}
     const delta=e.clientX-drag.x;
     if(!suppressClick&&Math.abs(delta)<5)return;
     suppressClick=true;
     if(!row.hasPointerCapture(e.pointerId))row.setPointerCapture(e.pointerId);
     row.classList.add('dragging');
     row.scrollLeft=drag.left-delta;
   });
   const finish=()=>{drag=null;row.classList.remove('dragging');};
   row.addEventListener('pointerup',finish);
   row.addEventListener('lostpointercapture',finish);
   row.addEventListener('pointercancel',finish);
   for(const type of ['click','dblclick'])row.addEventListener(type,e=>{
     if(suppressClick&&e.detail){e.preventDefault();e.stopImmediatePropagation();}
   },true);
 }
 function render(data){
   syncSelection();
   const top=scroller().scrollTop;const recoveryOpen=new Set([...document.querySelectorAll('.task-recovery[open]')].map(node=>node.dataset.task).filter(Boolean));const root=el('task-cards');const offsets=new Map([...root.querySelectorAll('.task-card')].map(card=>[card.dataset.group,card.querySelector('.task-images').scrollLeft]));root.replaceChildren();
   const summary=node('p',`${data.batch.name||`${data.batch.phone||'历史批次'} · ${data.batch.visible_count??data.batch.count} 组`} · ${data.batch.prompt_count||'组装中'} 条提示词 · 规则版本 ${data.batch.revision} · ${new Date(data.batch.created_at).toLocaleString('zh-CN')}`,'task-meta');
   const allImages=data.groups.flatMap(g=>g.images.map(i=>({...i,group:g.group})));
   for(const g of data.groups){
     const card=node('section',undefined,'task-card');card.dataset.group=g.group;
     card.tabIndex=0;
     card.setAttribute('aria-label',`第 ${g.group} 组`);
     card.title='单击选择或取消本组，双击图片预览';
     card.classList.toggle('group-selected',chosen.has(g.group));
     function toggleGroup(){
       if(busy)return;
       if(chosen.has(g.group))chosen.delete(g.group);else chosen.add(g.group);
       card.classList.toggle('group-selected',chosen.has(g.group));
       invalidate();
     }
     card.onclick=toggleGroup;
     card.onkeydown=e=>{if(e.target===card&&e.key===' '){e.preventDefault();toggleGroup();}};
     const images=node('div',undefined,'task-images'),slots=new Map();for(const u of g.units)slots.set(u.delivery_position,u.kind==='triptych_panel'?'triptych':u.kind);
     for(const [position,kind]of slots){const item=node('button',undefined,'task-image'),existing=g.images.find(i=>i.position===position);item.dataset.position=position;if(existing){const img=node('img');img.src=existing.url;img.loading='lazy';item.append(img);const preview=()=>imageDialog(allImages,allImages.findIndex(i=>i.path===existing.path));item.ondblclick=preview;item.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();preview();}};}else{item.append(node('span','尚未生成'));item.setAttribute('aria-disabled','true');}item.setAttribute('aria-label',`第 ${g.group} 组，第 ${position} 张${titles[kind]}`);images.append(item);}
     enableRowDrag(images);card.append(images);
     root.append(card);images.scrollLeft=offsets.get(String(g.group))||0;
   }
   const jobs=el('task-jobs');jobs.replaceChildren(summary);
   for(const t of data.tasks){const row=node('div',undefined,'task-job'),body=node('div',undefined,'task-job-body');row.dataset.status=t.status;const working=workingTask(t);body.append(node('span',`${states[t.status]||t.status} · ${t.groups.length} 组 · 请求 ${t.total_requests_used??t.requests_used}/${t.total_max_requests??t.max_requests}${t.auto_recovery?.phase?' · '+t.auto_recovery.phase:''}${t.error&&!working?' · '+t.error:''}`));
    if(!working&&t.status!=='completed'&&t.status!=='cancelled'){const s=t.resume_summary,blockedItems=(s?.blocked||[]).map(item=>({...item,...(t.auto_failures||[]).find(f=>f.unit===item.unit)}));
    if(blockedItems.length){const details=node('details',undefined,'task-recovery');details.dataset.task=t.id;details.open=recoveryOpen.has(t.id);details.append(node('summary',`可继续 ${s?.ready_count||0} 张 · 待处理 ${s?.blocked_count??blockedItems.length} 张（展开原因）`));const offered=new Set();for(const item of blockedItems){details.append(node('p',`第 ${t.replacement_target?.group||item.group} 组 · 图片 ${item.position} · ${item.unit}：${repairLabel(t,item.round)?repairLabel(t,item.round)+'：':''}${item.message||item.reason||'正在处理'}${item.http_status?'（HTTP '+item.http_status+'）':''}`));const key=item.group+':'+item.position;if(!offered.has(key)){offered.add(key);const b=node('button','补生成此图 · 复用已有素材');b.dataset.repair=key;b.disabled=blockedItems.some(i=>i.group===item.group&&i.position===item.position&&['uncertain','download','saved_result'].includes(i.reason));b.title=b.disabled?'需先核对或找回已返回结果，不能重复付费生成':'沿用冻结提示词，只补缺失素材，点击后查看独立请求范围';b.onclick=()=>window.repairTaskImage?.(t.replacement_target?{category,...t.replacement_target,source_revision:t.batch}:{category,batch:t.batch||batch,group:item.group,position:item.position});details.append(b);}}body.append(details);}renderAutoDiagnostics(t,body,data.groups);}row.append(body);
    if(!['running','queued','recovering','completed','cancelled'].includes(t.status)){const b=node('button');b.append(window.dashboardIcon('step-forward'));b.title=nothingSafe(t)?'已无可继续项，请展开待处理原因':'继续原任务，跳过需处理项';b.disabled=nothingSafe(t);b.setAttribute('aria-label','继续原任务');b.onclick=()=>action(async()=>{const saved=await call('resume',{task:t.id,batch:t.batch||batch});await refresh();message(continued(saved,'resume'));});row.append(b);}jobs.append(row);}
   taskButtons();
   if(!root.querySelector('.task-card'))root.append(node('p','没有符合当前筛选条件的内容组。','task-meta'));
   scroller().scrollTop=top;
 }
 el('task-batch').onchange=()=>{setBatch(el('task-batch').value);refresh();};
 el('task-refresh').onclick=()=>refresh();
 el('task-select-all').onchange=e=>{chosen=new Set(e.target.checked?(current?.groups.map(g=>g.group)||[]):[]);invalidate();if(current)render(current);};
 let watermarkTicket=0,watermarkLoad=Promise.resolve();
 function watermarkPhone(){el('task-watermark-phone').textContent='电话：'+el('task-phone').value.trim();}
 function watermarkRow(value){const row=node('div',undefined,'postprocess-line'),input=node('input'),remove=node('button','×');input.value=value;input.maxLength=20;input.setAttribute('aria-label','水印文字');remove.type='button';remove.title='删除这条文字';remove.setAttribute('aria-label','删除这条文字');remove.onclick=()=>row.remove();row.append(input,remove);return row;}
 function loadWatermark(){const ticket=++watermarkTicket,lines=el('task-watermark-lines');lines.replaceChildren(node('p','正在读取…'));el('task-watermark-add').disabled=true;watermarkLoad=call('overlay-text').then(data=>{if(ticket!==watermarkTicket)return;el('task-type-field').hidden=category!=='diving_salvage';el('task-type').replaceChildren();for(const item of data.task_types||[]){const option=node('option',item.name);option.value=item.id;el('task-type').append(option);}if(category==='diving_salvage')el('task-type').value='objects';lines.replaceChildren();for(const text of data.services||[])lines.append(watermarkRow(text));el('task-watermark-add').disabled=false;}).catch(error=>{if(ticket!==watermarkTicket)return;lines.replaceChildren();el('task-watermark-add').disabled=false;throw error;});}
 el('task-phone').addEventListener('input',watermarkPhone);
 el('task-watermark-add').onclick=()=>{const lines=el('task-watermark-lines');lines.append(watermarkRow(''));lines.lastElementChild.querySelector('input').focus();};
 el('task-new').onclick=()=>{el('task-type-field').hidden=category!=='diving_salvage';el('task-type').replaceChildren();el('task-phone').value='';watermarkPhone();window.dashboardMessage(el('task-create-error'),'');el('task-create-dialog').showModal();el('task-phone').focus();loadWatermark();};
 for(const id of ['task-create-close','task-create-cancel'])el(id).onclick=()=>{if(!busy)el('task-create-dialog').close();};
 el('task-create-dialog').addEventListener('cancel',e=>{if(busy)e.preventDefault();});
 el('task-create-form').onsubmit=e=>{e.preventDefault();action(async()=>{
   const count=Number(el('task-count').value);if(!Number.isInteger(count)||count<1||count>100)throw Error('请输入 1–100 组');
   const phone=el('task-phone').value.trim();if(!/^1[3-9][0-9]{9}$/.test(phone)){el('task-phone').focus();throw Error('请输入本批次的有效 11 位手机号');}
   await watermarkLoad;
   const services=[...el('task-watermark-lines').querySelectorAll('input')].map(input=>input.value);
   const cat=category;if(window.dashboardFlushPostprocessText)await window.dashboardFlushPostprocessText();message('正在创建批次…');
   const b=await call('assemble',{count,phone,services,...(category==='diving_salvage'?{task_type:el('task-type').value}:{}),request_id:crypto.randomUUID()});if(cat!==category)return;
   el('task-create-dialog').close();autoChoose=false;setBatch(b.id);await refresh();message('批次已创建，选择组后准备生成。');
 });};
 el('task-target').onchange=taskButtons;
 for(const op of ['pause','resume'])el('task-'+op).onclick=()=>action(async()=>{const options=eligibleTasks(op),select=el('task-target');if(!options.length)return;select.replaceChildren(...options.map(t=>new Option(`${states[t.status]||t.status} · ${t.groups.length} 组`,t.id)));if(options.length>1){const dialog=el('task-jobs-section');const closed=new Promise(resolve=>dialog.onclose=()=>resolve(dialog.returnValue));dialog.returnValue='cancel';dialog.showModal();if(await closed!=='confirm')return;}const task=el('task-target').value;if(!task)throw Error('请选择任务');const selected=current.tasks.find(t=>t.id===task);const key=batchKey();const saved=await call(op,{batch:selected?.batch||batch,task});if(op==='pause')pausing.add(task);else submitted.set(key,task);epoch++;await refresh();message(op==='pause'?'正在暂停，等待当前图片完成':continued(saved,op));});
 el('task-start').onclick=()=>{if(el('task-start').disabled)return;return action(async()=>{
   if(!chosen.size)throw Error('请先选择内容组');
   const keyBatch=batchKey(),ticket=epoch,version=planVersion,groups=[...chosen].sort((a,b)=>a-b);
   const started=Date.now();
   const button=el('task-start');
   const label=button.lastChild;
   let stage=`正在核对 ${groups.length} 组的待生成图片和可用通道`;
   function progress(){
     if(ticket===epoch)message(`${stage} · ${Math.floor((Date.now()-started)/1000)} 秒`);
   }
   progress();label.textContent='准备中…';
   const timer=setInterval(progress,1000);
   try{
     const result=await call('plan',{batch,groups,auto_complete:'automatic_cap'});
     if(ticket!==epoch)return;
     if(version!==planVersion){message('选择已变化，请重新开始生成。');return;}
     if(result.blocks.length)throw Error(result.blocks.join('；'));
     const cap=result.total_max_requests;
     stage=`待生成 ${result.pending_count} 张，整批最多请求 ${cap} 次，正在提交任务`;
     progress();label.textContent='提交中…';
     const key='task-request-'+result.plan_sha256;
     let id=localStorage.getItem(key);
     if(!id){id=crypto.randomUUID();localStorage.setItem(key,id);}
     const saved=await call('start',{batch,groups:result.groups,auto_complete:{mode:'continuous',total_max_requests:cap},plan_sha256:result.plan_sha256,request_id:id,authorization:'execute_selected_groups'});
     submitted.set(keyBatch,saved.id);
     if(ticket!==epoch)return;
     epoch++;startedTask=saved.id;
     stage=`任务已提交，等待后台生成 · 整批最多请求 ${cap} 次`;
     progress();invalidate();await refresh();
   }finally{clearInterval(timer);label.textContent='开始生成';}
 });};
 window.showSavedGroupPrompts=async details=>{
  if(details.dataset.loaded)return;const body=details.querySelector('div');
  try{const cat=details.dataset.category,g=Number(details.dataset.group),b=details.dataset.batch;
   const value=await window.roadRescue.tasks(b?'view':'legacy-group',{category:cat,batch:b,group:g,offset:g-1,limit:1});
   const row=b?value.groups[0]:value;body.replaceChildren(node('p',row.note||'已冻结的本地提示词'));
   for(const u of row.units){body.append(node('h4',`${u.position}. ${titles[u.kind]||u.kind}`),node('pre',u.prompt));}
   details.dataset.loaded='1';
  }catch(e){body.textContent=e.message;}
 };
 window.addEventListener('dashboard-project',e=>{category=e.detail;autoChoose=true;setBatch('');refresh();});
 window.addEventListener('dashboard-refresh',e=>{if(!initialized||category!==e.detail){initialized=true;category=e.detail;autoChoose=true;setBatch('');refresh();}});
 let refreshedAt=0;const refreshSoon=refresh;refresh=async function(){refreshedAt=Date.now();return refreshSoon.apply(this,arguments);};setInterval(()=>{if(el('gallery-panel').hidden||document.hidden)return;const active=current?.tasks?.some(workingTask);if(Date.now()-refreshedAt<(active?2000:5000))return;refresh();},1000);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!el('gallery-panel').hidden)refresh();});
})();
