const fs = require('fs');
const path = require('path');

const NOTIFICATION_STATE_VERSION = 1;
const TERMINAL_STATUSES = new Set([
  'completed',
  'completed_with_errors',
  'awaiting_review',
  'failed',
  'stopped_unexpectedly',
]);

function nonNegative(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, number) : 0;
}

function groupRange(job) {
  const start = Number(job?.group_start);
  const count = Number(job?.group_count);
  if (!Number.isInteger(start) || !Number.isInteger(count) || start < 1 || count < 1) return null;
  return count === 1 ? `第${start}组` : `第${start}-${start + count - 1}组`;
}

function buildCompletionNotification(job) {
  const status = String(job?.status || '');
  const jobId = String(job?.job_id || '');
  if (!jobId || !TERMINAL_STATUSES.has(status)) return null;

  const title = {
    awaiting_review: '图片生成完成，等待验收',
    completed: '图片生成完成',
    completed_with_errors: '图片生成结束，有失败项',
    failed: '图片生成失败',
    stopped_unexpectedly: '图片任务异常停止',
  }[status];
  const range = groupRange(job);
  const completed = nonNegative(job.completed);
  const failed = nonNegative(job.failed);
  const requestsUsed = nonNegative(job.requestsUsed ?? job.requests_used);
  const parts = [];
  if (range) parts.push(range);
  parts.push(`完成 ${completed}`);
  parts.push(`失败 ${failed}`);
  if (requestsUsed > 0) parts.push(`请求 ${requestsUsed} 次`);
  return { jobId, status, title, body: parts.join('；') };
}

function statePath(projectRoot) {
  return path.join(projectRoot, '.runtime', 'dashboard_notification_state.json');
}

function readNotificationState(projectRoot) {
  try {
    const payload = JSON.parse(fs.readFileSync(statePath(projectRoot), 'utf8').replace(/^\uFEFF/, ''));
    if (payload?.schema_version === NOTIFICATION_STATE_VERSION && payload.jobs && typeof payload.jobs === 'object') {
      return payload;
    }
  } catch {}
  return { schema_version: NOTIFICATION_STATE_VERSION, jobs: {} };
}

function notificationWasSent(projectRoot, jobId) {
  return Boolean(readNotificationState(projectRoot).jobs[String(jobId)]);
}

function markNotificationSent(projectRoot, notice, notifiedAt = new Date().toISOString()) {
  const payload = readNotificationState(projectRoot);
  payload.jobs[notice.jobId] = {
    status: notice.status,
    notified_at: notifiedAt,
  };
  const entries = Object.entries(payload.jobs)
    .sort((left, right) => String(right[1]?.notified_at || '').localeCompare(String(left[1]?.notified_at || '')))
    .slice(0, 200);
  payload.jobs = Object.fromEntries(entries);
  payload.updated_at = notifiedAt;
  const target = statePath(projectRoot);
  const temporary = `${target}.${process.pid}.tmp`;
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(temporary, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  fs.renameSync(temporary, target);
}

module.exports = {
  TERMINAL_STATUSES,
  buildCompletionNotification,
  markNotificationSent,
  notificationWasSent,
  readNotificationState,
};
