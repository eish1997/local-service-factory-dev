/* Lucide static assets, kept locally for offline use. No hand-drawn paths. */
(() => {
  window.dashboardIcon = name => {
    const span = document.createElement('span');
    span.className = `ui-icon icon-${name}`;
    span.setAttribute('aria-hidden', 'true');
    return span;
  };
  const icons = {

    'task-package':'archive','task-start':'play', 'task-pause':'pause', 'task-resume':'step-forward',
    'task-refresh':'refresh-cw', 'task-new':'plus',
    'variable-reload':'refresh-cw', 'task-create-close':'x',
    'update-settings':'refresh-cw','key-settings':'key-round','open-folder':'folder-open', 'compact-toggle':'minimize-2',
    'window-minimize':'minus', 'window-maximize':'square', 'window-close':'x'
  };
  for (const [id, name] of Object.entries(icons)) {
    const button = document.getElementById(id);
    const label=({'task-start':'开始生成','task-pause':'暂停','task-resume':'继续','task-package':'打包'})[id]||'';
    button.replaceChildren(window.dashboardIcon(name));
    if(label)button.append(document.createTextNode(label));
    button.setAttribute('aria-label', button.getAttribute('aria-label') || button.title);
  }
  window.roadRescue.onMaximizedChanged(maximized=>{
    const button=document.getElementById('window-maximize');
    button.replaceChildren(window.dashboardIcon(maximized?'restore':'square'));
    button.title=maximized?'还原':'最大化';
    button.setAttribute('aria-label',button.title);
  });
  for (const id of ['task-target','variable-role','variable-filter']) {
    const select=document.getElementById(id), wrap=document.createElement('span');
    wrap.className='select-wrap';select.before(wrap);wrap.append(select,window.dashboardIcon('chevron-down'));
  }
})();
