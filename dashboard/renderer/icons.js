/* Lucide static assets, kept locally for offline use. No hand-drawn paths. */
(() => {
  window.dashboardIcon = name => {
    const span = document.createElement('span');
    span.className = `ui-icon icon-${name}`;
    span.setAttribute('aria-hidden', 'true');
    return span;
  };
  const icons = {
    'task-select-all':'square-check', 'task-clear':'square', 'task-plan':'info',
    'task-package':'archive','task-start':'play', 'task-pause':'pause', 'task-resume':'step-forward',
    'task-retry':'rotate-ccw', 'task-refresh':'refresh-cw', 'task-new':'plus',
    'variable-reload':'refresh-cw', 'task-create-close':'x',
    'update-settings':'refresh-cw','key-settings':'key-round','open-folder':'folder-open', 'compact-toggle':'minimize-2',
    'window-minimize':'minus', 'window-maximize':'maximize-2', 'window-close':'x'
  };
  for (const [id, name] of Object.entries(icons)) {
    const button = document.getElementById(id);
    button.replaceChildren(window.dashboardIcon(name));
    button.setAttribute('aria-label', button.getAttribute('aria-label') || button.title);
  }
  for (const id of ['task-target','task-filter','variable-role','variable-filter']) {
    const select=document.getElementById(id), wrap=document.createElement('span');
    wrap.className='select-wrap';select.before(wrap);wrap.append(select,window.dashboardIcon('chevron-down'));
  }
})();
