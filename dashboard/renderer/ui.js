/* Shared presentation helpers; task budgets and execution remain in public APIs. */
(()=>{
 const node=(tag,text)=>{const value=document.createElement(tag);if(text!==undefined)value.textContent=text;return value;};
 window.dashboardMessage=(element,text,error=false)=>{
  element._errorDetails?.remove();element._errorDetails=null;
  const full=String(text||'').replace(/Error invoking remote method '[^']+':\s*(?:Error:\s*)?/g,''),reasons=[
   ['没有可在原预算内继续','当前没有可继续的图片，请打开任务详情查看原因。'],
   ['API配置已变化','生成设置已变化。请恢复任务原来的设置后继续。'],
   ['结果不确定','请求结果尚未确认，请先核对记录，避免重复扣费。']
  ],short=error?(reasons.find(([match])=>full.includes(match))?.[1]||full):full;
  element.textContent=short;element.hidden=!short;element.classList.toggle('error',error);
  if(error&&short!==full){const details=node('details');details.className='content-details error-details';details.append(node('summary','错误详情'),node('p',full));element.after(details);element._errorDetails=details;}
 };
 window.dashboardPlan=(element,plan,full,context='')=>{
  element.replaceChildren();
  if(context)element.append(node('p',context));
  element.append(node('p',`新生成 ${plan.pending_count} 张 · 复用 ${plan.library_reused_count||0} 张 · 保留 ${plan.retained_count||0} 张 · 整批最高请求 ${plan.total_max_requests??plan.max_requests} 次`));
  element.append(node('small',plan.pending_count?'按实际请求计费，额度内持续补齐。':'使用已有图片，无生图费用。'));
  if(plan.blocks.length){const error=node('p');element.append(error);window.dashboardMessage(error,'无法开始：'+plan.blocks.join('；'),true);}
  const details=node('details');details.className='content-details';details.append(node('summary','生成详情'),node('p',full));element.append(details);
 };
})();
