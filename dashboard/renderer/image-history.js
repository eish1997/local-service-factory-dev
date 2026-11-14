/* Shared history sidebar for inline and standalone image viewers. */
(() => {
 window.mountImageHistory=async(container,request,onSelected)=>{
  const token={};container._imageHistoryToken=token;container.replaceChildren();const make=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  const heading=make('h3','历史版本'),list=make('div'),status=make('p');container.append(heading,list,status);
  let disposed=false;const active=()=>!disposed&&container._imageHistoryToken===token;
  async function refresh(){
   try{const data=await window.roadRescue.tasks('image-history',request);if(!active())return;list.replaceChildren();
    status.textContent=data.versions.length?'':'暂无历史版本';
    for(const version of data.versions){const button=make('button');button.className='image-history-item'+(version.id===data.current?' selected':'');const img=make('img');img.src=version.url;img.loading='lazy';const title=make('span',({original:'原始版本',generation:'重新生成',postprocess:'后处理'}[version.operation]||'历史版本')+(version.id===data.current?' · 当前':''));const time=make('small',version.created_at?new Date(version.created_at).toLocaleString('zh-CN'):'');button.append(img,title,time);
     button.onclick=async()=>{if(!active()||version.id===data.current)return;list.querySelectorAll('button').forEach(b=>b.disabled=true);status.textContent='切换当前版本…';try{await window.roadRescue.tasks('image-version-select',{...request,version:version.id});if(!active())return;await onSelected(version);status.textContent='已设为当前版本';await refresh();window.dispatchEvent(new Event('dashboard-admin-refresh'));}catch(e){if(!active())return;status.textContent=e.message;list.querySelectorAll('button').forEach(b=>b.disabled=false);}};list.append(button);
    }
   }catch(e){if(active())status.textContent='无法读取历史版本';}
  }
  await refresh();return ()=>{disposed=true;};
 };
})();
