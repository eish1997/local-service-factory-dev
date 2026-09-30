const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const { inspectJob, summarizeJob } = require('../monitor');

const NOW = Date.parse('2026-07-11T03:00:00Z');

test('reports a recently updated live process as live', () => {
  const result = inspectJob(
    { job_id: 'live', status: 'running', pid: 123, updated_at: '2026-07-11T02:59:30Z' },
    '',
    { nowMs: NOW, probe: () => true },
  );
  assert.equal(result.health, 'live');
  assert.equal(result.processAlive, true);
  assert.equal(result.stale, false);
});

test('reports a living process with an old update as stale', () => {
  const result = inspectJob(
    { job_id: 'stale', status: 'waiting_for_api', pid: 456, updated_at: '2026-07-11T02:50:00Z' },
    '',
    { nowMs: NOW, probe: () => true },
  );
  assert.equal(result.health, 'stale');
  assert.equal(result.processAlive, true);
  assert.equal(result.stale, true);
});

test('terminal jobs stay finished even though their old process no longer exists', () => {
  const result = inspectJob(
    { job_id: 'done', status: 'completed', pid: 789, updated_at: '2026-07-11T02:00:00Z' },
    '',
    { nowMs: NOW, probe: () => false },
  );
  assert.equal(result.health, 'finished');
});

test('dead group worker is red and keeps exact generation and license counts', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dashboard-monitor-'));
  try {
    const lockDir = path.join(root, '.runtime', 'group_locks', 'home_appliance_repair');
    const jobDir = path.join(root, '.runtime', 'jobs');
    const licenseDir = path.join(root, '.runtime', 'group_execution_licenses', 'home_appliance_repair');
    fs.mkdirSync(lockDir, { recursive: true });
    fs.mkdirSync(jobDir, { recursive: true });
    fs.mkdirSync(licenseDir, { recursive: true });
    fs.writeFileSync(
      path.join(lockDir, 'group_0016_0060.lock'),
      JSON.stringify({ job_id: 'group-test', pid: 9320 }),
    );
    fs.writeFileSync(
      path.join(jobDir, 'group-test.events.jsonl'),
      [1, 2, 3, 4].map((value) => JSON.stringify({ status: 'generated', target: `image-${value}.png` })).join('\n'),
    );
    fs.writeFileSync(
      path.join(licenseDir, 'group_0016_0060.json'),
      JSON.stringify({
        project_id: 'home_appliance_repair', group_start: 16, group_count: 60,
        approved_request_budget: 454, requests_used: 14,
        model: 'gpt-image-2', quality: 'medium', size: '1024x1536',
      }),
    );

    const result = summarizeJob({
      job_id: 'group-test', job_type: 'group-production', project_id: 'home_appliance_repair',
      status: 'waiting_for_api', group_start: 16, group_count: 60,
      requested_count: 540, completed: 90, failed: 0, requests_used: 14,
      updated_at: '2026-07-11T02:43:51Z', pid: 24652,
    }, root, { nowMs: NOW, probe: () => false });

    assert.equal(result.status, 'stopped_unexpectedly');
    assert.equal(result.health, 'dead');
    assert.equal(result.monitorPid, 9320);
    assert.equal(result.completed, 90);
    assert.equal(result.remaining, 450);
    assert.equal(result.reusable, 86);
    assert.equal(result.newGenerated, 4);
    assert.equal(result.failed, 0);
    assert.equal(result.requestsUsed, 14);
    assert.equal(result.requestBudget, 454);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('category job progress counts generated API units instead of preexisting delivery files', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dashboard-category-monitor-'));
  try {
    const batch = path.join(root, 'prompts', 'category_batches', 'road_rescue', 'batch_active');
    fs.mkdirSync(path.join(batch, 'production'), { recursive: true });
    fs.writeFileSync(
      path.join(batch, 'production', 'events_category-job.jsonl'),
      [1, 2, 3].map((value) => JSON.stringify({
        status: 'generated', generation_target_id: `unit-${value}`,
      })).join('\n'),
    );
    const result = summarizeJob({
      job_id: 'category-job', job_type: 'category-batch-production', project_id: 'road_rescue',
      batch_dir: batch, status: 'running', requested_count: 5, completed: 12,
      generated_api_units: 3, requests_used: 3, updated_at: '2026-07-11T02:59:30Z', pid: 123,
    }, root, { nowMs: NOW, probe: () => true });

    assert.equal(result.completed, 3);
    assert.equal(result.remaining, 2);
    assert.equal(result.newGenerated, 3);
    assert.equal(result.requestBudget, 5);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('category retry budget does not inflate generation target progress', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dashboard-category-retry-'));
  try {
    const batch = path.join(root, 'prompts', 'category_batches', 'road_rescue', 'batch_active');
    fs.mkdirSync(path.join(batch, 'production'), { recursive: true });
    fs.writeFileSync(
      path.join(batch, 'production', 'events_category-retry-job.jsonl'),
      [1, 2].map((value) => JSON.stringify({
        status: 'generated', generation_target_id: `unit-${value}`,
      })).join('\n'),
    );
    const result = summarizeJob({
      job_id: 'category-retry-job', job_type: 'category-batch-production', project_id: 'road_rescue',
      batch_dir: batch, status: 'awaiting_review', requested_count: 4, generation_target_count: 2,
      generated_api_units: 2, requests_used: 2, updated_at: '2026-07-11T02:59:30Z', pid: 123,
    }, root, { nowMs: NOW, probe: () => false });

    assert.equal(result.completed, 2);
    assert.equal(result.requested_count, 2);
    assert.equal(result.remaining, 0);
    assert.equal(result.requestBudget, 4);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
