const fs = require('fs');
const path = require('path');

const ACTIVE_STATUSES = new Set(['queued', 'starting', 'running', 'waiting_for_api']);
const FINISHED_STATUSES = new Set(['completed', 'completed_with_errors', 'awaiting_review']);
const STALE_AFTER_SECONDS = 180;

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
  } catch {
    return null;
  }
}

function positiveInteger(value) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : null;
}

function processIsAlive(pid) {
  const value = positiveInteger(pid);
  if (!value) return null;
  try {
    process.kill(value, 0);
    return true;
  } catch (error) {
    return error?.code === 'EPERM';
  }
}

function secondsSince(iso, nowMs = Date.now()) {
  const updatedMs = Date.parse(String(iso || ''));
  if (!Number.isFinite(updatedMs)) return null;
  return Math.max(0, Math.floor((nowMs - updatedMs) / 1000));
}

function groupLockPath(projectRoot, job) {
  if (job?.job_type !== 'group-production' || !job.project_id) return null;
  const start = positiveInteger(job.group_start);
  const count = positiveInteger(job.group_count);
  if (!start || !count) return null;
  return path.join(
    projectRoot,
    '.runtime',
    'group_locks',
    String(job.project_id),
    `group_${String(start).padStart(4, '0')}_${String(count).padStart(4, '0')}.lock`,
  );
}

function inspectJob(job, projectRoot, options = {}) {
  const nowMs = options.nowMs ?? Date.now();
  const probe = options.probe || processIsAlive;
  const claimedActive = ACTIVE_STATUSES.has(job?.status);
  const ageSeconds = secondsSince(job?.updated_at || job?.created_at, nowMs);
  const lockFile = projectRoot ? groupLockPath(projectRoot, job) : null;
  const lock = options.lockData === undefined ? (lockFile ? readJson(lockFile) : null) : options.lockData;
  const matchingLock = lock && String(lock.job_id || '') === String(job?.job_id || '') ? lock : null;
  const lockPid = positiveInteger(matchingLock?.pid);
  const launcherPid = positiveInteger(job?.pid);
  const monitorPid = lockPid || launcherPid;
  const pidSource = lockPid ? 'worker-lock' : (launcherPid ? 'job' : null);
  const processAlive = monitorPid ? Boolean(probe(monitorPid)) : null;
  const stale = claimedActive && ageSeconds !== null && ageSeconds > STALE_AFTER_SECONDS;

  let health = 'idle';
  if (claimedActive && processAlive === false) health = 'dead';
  else if (claimedActive && (stale || processAlive === null)) health = 'stale';
  else if (claimedActive) health = 'live';
  else if (job?.status === 'failed') health = 'failed';
  else if (FINISHED_STATUSES.has(job?.status)) health = 'finished';

  return {
    claimedActive,
    processAlive,
    monitorPid,
    pidSource,
    lockFile,
    ageSeconds,
    stale,
    health,
  };
}

function eventPath(projectRoot, job) {
  if (job?.event_file) return path.resolve(String(job.event_file));
  if (job?.job_type === 'category-batch-production' && job?.batch_dir) {
    return path.join(String(job.batch_dir), 'production', `events_${job.job_id}.jsonl`);
  }
  if (job?.batchDir) return path.join(job.batchDir, 'production', 'jobs', `${job.job_id}.events.jsonl`);
  return path.join(projectRoot, '.runtime', 'jobs', `${job.job_id}.events.jsonl`);
}

function readEventCounts(projectRoot, job) {
  const file = eventPath(projectRoot, job);
  if (!fs.existsSync(file)) {
    return { eventsFound: false, newGenerated: null, explicitReusable: null, requestFailures: 0 };
  }
  const generated = new Set();
  const reused = new Set();
  let requestFailures = 0;
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    if (!line.trim()) continue;
    let event = null;
    try { event = JSON.parse(line); } catch { continue; }
    const target = String(
      event.generation_target_id
      || event.target
      || event.delivery_target
      || `${event.group_index || ''}:${event.generation_position || event.position || ''}`,
    );
    if (event.status === 'generated') generated.add(target);
    if (event.status === 'reused') reused.add(target);
    if (event.status === 'request_failed') requestFailures += 1;
  }
  return {
    eventsFound: true,
    newGenerated: generated.size,
    explicitReusable: reused.size,
    requestFailures,
  };
}

function readGroupLicense(projectRoot, job) {
  if (job?.job_type !== 'group-production' || !job.project_id) return null;
  const start = positiveInteger(job.group_start);
  const count = positiveInteger(job.group_count);
  if (!start || !count) return null;
  const file = path.join(
    projectRoot,
    '.runtime',
    'group_execution_licenses',
    String(job.project_id),
    `group_${String(start).padStart(4, '0')}_${String(count).padStart(4, '0')}.json`,
  );
  const license = readJson(file);
  if (!license) return null;
  if (String(license.project_id || '') !== String(job.project_id)) return null;
  if (Number(license.group_start) !== start || Number(license.group_count) !== count) return null;
  return {
    requestBudget: Number.isFinite(Number(license.approved_request_budget))
      ? Number(license.approved_request_budget) : null,
    requestsUsed: Number.isFinite(Number(license.requests_used)) ? Number(license.requests_used) : 0,
    model: license.model || null,
    quality: license.quality || null,
    size: license.size || null,
  };
}

function summarizeJob(job, projectRoot, options = {}) {
  const processState = inspectJob(job, projectRoot, options);
  const events = readEventCounts(projectRoot, job);
  const license = readGroupLicense(projectRoot, job);
  const requestBudgetFromJob = Math.max(0, Number(job.requested_count || 0));
  const requested = job?.job_type === 'category-batch-production'
    ? Math.max(0, Number(job.generation_target_count ?? job.requested_count ?? 0))
    : requestBudgetFromJob;
  const newGenerated = events.eventsFound
    ? events.newGenerated
    : (Number.isFinite(Number(job.generated)) ? Number(job.generated) : null);
  const completed = job?.job_type === 'category-batch-production'
    ? Math.max(0, Math.min(requested, Number(job.generated_api_units ?? newGenerated ?? 0)))
    : Math.max(0, Number(job.completed || 0));
  const jobReusable = Number.isFinite(Number(job.reused)) ? Number(job.reused) : null;
  const reusable = events.eventsFound
    ? Math.max(events.explicitReusable || 0, completed - Number(newGenerated || 0))
    : jobReusable;
  const jobRequestsUsed = Number.isFinite(Number(job.requests_used)) ? Number(job.requests_used) : 0;
  const licenseRequestsUsed = license?.requestsUsed || 0;
  const status = processState.health === 'dead' ? 'stopped_unexpectedly' : job.status;

  return {
    ...job,
    rawStatus: job.status,
    status,
    ...processState,
    completed,
    requested_count: requested,
    remaining: Math.max(0, requested - completed),
    failed: Math.max(0, Number(job.failed || 0)),
    reusable,
    newGenerated,
    requestFailures: events.requestFailures,
    requestsUsed: Math.max(jobRequestsUsed, licenseRequestsUsed),
    requestBudget: license?.requestBudget
      ?? (Number.isFinite(Number(job.request_budget)) ? Number(job.request_budget) : null)
      ?? (job?.job_type === 'category-batch-production' ? requestBudgetFromJob : null),
    model: license?.model || job.model || null,
    quality: license?.quality || job.quality || null,
    size: license?.size || job.size || null,
  };
}

module.exports = {
  ACTIVE_STATUSES,
  STALE_AFTER_SECONDS,
  inspectJob,
  processIsAlive,
  readEventCounts,
  readGroupLicense,
  secondsSince,
  summarizeJob,
};
