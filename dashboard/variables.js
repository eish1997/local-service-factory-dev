const { spawn } = require('child_process');
const path = require('path');
// Renderer access is deliberately read-only; Agent CLI retains editing commands.
const OPERATIONS = new Set(['projects', 'list', 'history']);

function runVariables(root, request) {
  return new Promise((resolve, reject) => {
    if (!root || !request || !OPERATIONS.has(request.operation) || !/^[a-z0-9_]+$/.test(request.category || 'road_rescue')) {
      reject(new Error('无效的变量管理请求')); return;
    }
    if (request.payload && Object.keys(request.payload).length) { reject(new Error('变量一览仅允许读取，不接受修改或抽样内容')); return; }
    const child = spawn(require('./backend').python(), ['-X', 'utf8', require('./backend').entry(root), 'variables', request.operation,
      '--category', request.category || 'road_rescue'], { cwd: root, windowsHide: true, shell: false, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
    let output = '', errors = '', settled = false;
    const done = (error, value) => { if (settled) return; settled = true; clearTimeout(timer); error ? reject(error) : resolve(value); };
    const timer = setTimeout(() => { child.kill(); done(new Error('读取变量超时，请稍后刷新')); }, 60000);
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    child.stdout.on('data', chunk => { output += chunk; if (output.length > 12 * 1024 * 1024) { child.kill(); done(new Error('返回内容过大')); } });
    child.stderr.on('data', chunk => { errors = (errors + chunk).slice(-2000); });
    child.on('error', error => done(new Error(`无法运行本地配置工具：${error.message}`)));
    child.on('close', () => {
      try { const result = JSON.parse(output.trim()); if (!result.ok) throw new Error(result.error); done(null, result.data); }
      catch (e) { done(new Error(output.trim().startsWith('{') ? e.message : `本地工具未返回有效结果：${errors}`)); }
    });
    child.stdin.on('error', () => {}); child.stdin.end();
  });
}
module.exports = { runVariables };
