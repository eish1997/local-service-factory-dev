const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  buildCompletionNotification,
  markNotificationSent,
  notificationWasSent,
  readNotificationState,
} = require('../notifications');

test('only terminal jobs create a completion notification', () => {
  assert.equal(buildCompletionNotification({ job_id: 'running', status: 'running' }), null);
  const notice = buildCompletionNotification({
    job_id: 'done', status: 'completed_with_errors', group_start: 329, group_count: 50,
    completed: 198, failed: 2, requestsUsed: 307,
  });
  assert.equal(notice.title, '图片生成结束，有失败项');
  assert.match(notice.body, /第329-378组/);
  assert.match(notice.body, /完成 198/);
  assert.match(notice.body, /失败 2/);
  assert.match(notice.body, /请求 307 次/);
});

test('notification state persists one record per job', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dashboard-notification-'));
  try {
    const notice = buildCompletionNotification({
      job_id: 'done', status: 'awaiting_review', group_start: 1, group_count: 3,
      completed: 3, failed: 0, requests_used: 3,
    });
    assert.equal(notificationWasSent(root, 'done'), false);
    markNotificationSent(root, notice, '2026-08-05T00:00:00Z');
    assert.equal(notificationWasSent(root, 'done'), true);
    const state = readNotificationState(root);
    assert.equal(state.jobs.done.status, 'awaiting_review');
    assert.equal(state.jobs.done.notified_at, '2026-08-05T00:00:00Z');
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
