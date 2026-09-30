const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '')); } catch { return null; }
}

function isInside(parent, candidate) {
  const relative = path.relative(path.resolve(parent), path.resolve(candidate));
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

function resolveProjectFile(projectRoot, value) {
  if (!value) return null;
  const candidate = path.resolve(projectRoot, String(value));
  return isInside(projectRoot, candidate) ? candidate : null;
}

function readDashboardSession(projectRoot) {
  const file = path.join(projectRoot, '.runtime', 'dashboard_session.json');
  const session = readJson(file);
  if (!session || session.schema_version !== 1) {
    return {
      schema_version: 1,
      mode: 'waiting',
      job_id: null,
      project_id: 'road_rescue',
      expected_targets: [],
    };
  }
  return session;
}

function readDashboardDeliveryState(projectRoot) {
  const file = path.join(projectRoot, '.runtime', 'dashboard_delivery_state.json');
  const state = readJson(file);
  if (!state || state.schema_version !== 1 || typeof state.projects !== 'object') {
    return { schema_version: 1, projects: {}, package_history: [] };
  }
  return state;
}

function loadSessionJob(projectRoot, session) {
  if (session?.mode !== 'job' || !session.job_file || !session.job_id) return null;
  const file = resolveProjectFile(projectRoot, session.job_file);
  if (!file || !fs.existsSync(file)) return null;
  const job = readJson(file);
  return job && String(job.job_id) === String(session.job_id) ? job : null;
}

function eventPathCandidates(projectRoot, job) {
  const candidates = [];
  if (job?.event_file) candidates.push(path.resolve(String(job.event_file)));
  if (job?.job_type === 'category-batch-production' && job.batch_dir && job.job_id) {
    candidates.push(path.join(String(job.batch_dir), 'production', `events_${job.job_id}.jsonl`));
  }
  if (job?.job_id) {
    candidates.push(path.join(projectRoot, '.runtime', 'jobs', `${job.job_id}.events.jsonl`));
  }
  return Array.from(new Set(candidates.map((value) => path.resolve(value))))
    .filter((value) => isInside(projectRoot, value));
}

function outputTarget(projectRoot, value) {
  if (!value) return null;
  const candidate = path.isAbsolute(String(value))
    ? path.resolve(String(value))
    : path.resolve(projectRoot, String(value));
  const outputRoot = path.join(projectRoot, 'output');
  if (!require('./assets').allowed(projectRoot, candidate) || path.extname(candidate).toLowerCase() !== '.png') return null;
  return candidate;
}

function readTouchedTargets(projectRoot, job) {
  const targets = new Set();
  for (const eventFile of eventPathCandidates(projectRoot, job)) {
    if (!fs.existsSync(eventFile)) continue;
    for (const line of fs.readFileSync(eventFile, 'utf8').split(/\r?\n/)) {
      if (!line.trim()) continue;
      let event = null;
      try { event = JSON.parse(line); } catch { continue; }
      if (!['generated', 'reused'].includes(event.status)) continue;
      const target = outputTarget(projectRoot, event.delivery_target || event.target);
      if (target) targets.add(target);
    }
  }
  return targets;
}

function imageEntry(projectRoot, fullPath, job) {
  if (!fs.existsSync(fullPath)) return null;
  const outputRoot = path.join(projectRoot, 'output');
  const name = path.relative(outputRoot, fullPath).replaceAll('\\', '/');
  const parts = name.split('/');
  const fileName = parts[parts.length - 1] || name;
  const groupMatch = name.match(/group_(\d+)/i);
  const positionMatch = fileName.match(/^(\d+)_/);
  if (!groupMatch || !positionMatch) return null;
  const stat = fs.statSync(fullPath);
  let role = 'detail';
  if (fileName.includes('cover')) role = 'cover';
  else if (fileName.includes('triptych')) role = 'triptych';
  return {
    name,
    path: fullPath,
    url: pathToFileURL(fullPath).href,
    size: stat.size,
    modified: stat.mtime.toISOString(),
    projectId: String(job?.project_id || job?.category_id || parts[0] || 'unassigned'),
    batchId: job?.batch_id || null,
    groupIndex: Number(groupMatch[1]),
    position: Number(positionMatch[1]),
    role,
  };
}

function expectedTargets(projectRoot, session) {
  return (session?.expected_targets || []).map((item) => {
    const target = outputTarget(projectRoot, item.path);
    if (!target) return null;
    return {
      ...item,
      target,
      group_index: Number(item.group_index || 0),
      position: Number(item.position || 0),
    };
  }).filter(Boolean);
}

function validationApproved(target) {
  const validation = readJson(target.replace(/\.png$/i, '.validation.json'));
  return validation?.approved === true || validation?.status === 'approved';
}

function buildSessionGallery(projectRoot, session, job) {
  return buildDeliveryGallery(projectRoot, readDashboardDeliveryState(projectRoot), job);
}

function buildDeliveryGallery(projectRoot, deliveryState, currentJob = null) {
  const images = [];
  const groups = [];
  const projects = deliveryState?.projects || {};
  const outputRoot = path.join(projectRoot, 'output');
  for (const [projectId, project] of Object.entries(projects)) {
    if (!/^[A-Za-z0-9_-]+$/.test(projectId)) continue;
    const pending = project?.pending_groups || {};
    for (const entry of Object.values(pending)) {
      const groupIndex = Number(entry?.group_index || 0);
      const expectedImageCount = Number(entry?.expected_image_count || 0);
      if (!Number.isInteger(groupIndex) || groupIndex < 1 || expectedImageCount < 1) continue;
      const groupDir = path.resolve(outputRoot, projectId, `group_${String(groupIndex).padStart(4, '0')}`);
      if (!isInside(outputRoot, groupDir)) continue;
      const pseudoJob = {
        project_id: projectId,
        category_id: projectId,
        batch_id: String(currentJob?.project_id || currentJob?.category_id || '') === projectId
          ? currentJob?.batch_id || null : null,
      };
      const items = fs.existsSync(groupDir)
        ? fs.readdirSync(groupDir)
          .filter((name) => name.toLowerCase().endsWith('.png'))
          .map((name) => imageEntry(projectRoot, path.join(groupDir, name), pseudoJob))
          .filter(Boolean)
          .sort((a, b) => a.position - b.position)
        : [];
      images.push(...items);
      const complete = items.length === expectedImageCount;
      const approved = complete && items.every((item) => validationApproved(item.path));
      groups.push({
        projectId,
        groupIndex,
        imageCount: items.length,
        expectedImageCount,
        imageComplete: complete,
        textApproved: approved,
        deliveryReady: complete && approved,
        validationStatus: approved ? 'approved' : 'needs_user_review',
      });
    }
  }
  for (const [projectId, project] of Object.entries(projects)) {
    for(const entry of Object.values(project.pending_library_groups||{})){
      if(!/^batch_[A-Za-z0-9_-]+$/.test(entry.batch_id)||!Number.isInteger(entry.group_index))continue;
      let allowed;try{allowed=path.resolve(require('./assets').batchOutput(projectRoot,projectId,entry.batch_id),`group_${String(entry.group_index).padStart(4,'0')}`);}catch{continue;}
      const items=(entry.paths||[]).map(value=>path.resolve(projectRoot,value)).filter(file=>file&&isInside(allowed,file)&&fs.existsSync(file))
        .map(file=>imageEntry(projectRoot,file,{project_id:projectId,batch_id:entry.batch_id})).filter(Boolean)
        .map(item=>({...item,libraryBatch:entry.batch_id}));
      images.push(...items);const complete=items.length===entry.expected_image_count,approved=complete&&items.every(i=>validationApproved(i.path));
      groups.push({projectId,groupIndex:entry.group_index,libraryBatch:entry.batch_id,imageCount:items.length,expectedImageCount:entry.expected_image_count,imageComplete:complete,textApproved:approved,deliveryReady:approved,validationStatus:approved?'approved':'needs_user_review'});
    }
  }
  images.sort((a, b) => a.projectId.localeCompare(b.projectId) || a.groupIndex - b.groupIndex || a.position - b.position);
  groups.sort((a, b) => a.projectId.localeCompare(b.projectId) || a.groupIndex - b.groupIndex);
  return { images, groups };
}

module.exports = {
  buildDeliveryGallery,
  buildSessionGallery,
  eventPathCandidates,
  loadSessionJob,
  readDashboardSession,
  readDashboardDeliveryState,
  readTouchedTargets,
  resolveProjectFile,
};
