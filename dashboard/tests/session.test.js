const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  buildDeliveryGallery,
  buildSessionGallery,
  loadSessionJob,
  readDashboardSession,
  readTouchedTargets,
} = require('../session');

function temporaryRoot() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dashboard-session-'));
  fs.mkdirSync(path.join(root, '.runtime'), { recursive: true });
  fs.mkdirSync(path.join(root, 'output', 'road_rescue', 'group_0001'), { recursive: true });
  return root;
}

test('waiting session never scans or displays historical output images', () => {
  const root = temporaryRoot();
  try {
    fs.writeFileSync(path.join(root, 'output', 'road_rescue', 'group_0001', '01_cover.png'), 'old');
    const session = readDashboardSession(root);
    const gallery = buildSessionGallery(root, session, null);
    assert.equal(session.mode, 'waiting');
    assert.deepEqual(gallery.images, []);
    assert.deepEqual(gallery.groups, []);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('delivery queue displays the full pending group instead of only job-touched files', () => {
  const root = temporaryRoot();
  try {
    const batch = path.join(root, 'prompts', 'category_batches', 'road_rescue', 'batch_active');
    const jobs = path.join(batch, 'production', 'jobs');
    fs.mkdirSync(jobs, { recursive: true });
    const current = path.join(root, 'output', 'road_rescue', 'group_0001', '02_triptych.png');
    const historical = path.join(root, 'output', 'road_rescue', 'group_0001', '01_cover.png');
    fs.writeFileSync(current, 'current');
    fs.writeFileSync(historical, 'historical');
    const job = {
      job_id: 'road-job-1', job_type: 'category-batch-production', project_id: 'road_rescue',
      batch_dir: batch, batch_id: 'batch_active', group_start: 1, group_count: 1,
    };
    const jobFile = path.join(jobs, 'road-job-1.json');
    fs.writeFileSync(jobFile, JSON.stringify(job));
    fs.writeFileSync(
      path.join(batch, 'production', 'events_road-job-1.jsonl'),
      `${JSON.stringify({ status: 'generated', delivery_target: current })}\n`,
    );
    const session = {
      schema_version: 1, mode: 'job', job_id: 'road-job-1',
      job_file: path.relative(root, jobFile), project_id: 'road_rescue',
      expected_targets: [
        { path: path.relative(root, current), group_index: 1, position: 2, role: 'triptych' },
        { path: 'output/road_rescue/group_0001/03_detail.png', group_index: 1, position: 3, role: 'detail' },
      ],
    };
    fs.writeFileSync(path.join(root, '.runtime', 'dashboard_session.json'), JSON.stringify(session));
    const deliveryState = {
      schema_version: 1,
      projects: {
        road_rescue: {
          pending_groups: {
            1: { group_index: 1, expected_image_count: 2 },
          },
        },
      },
    };
    fs.writeFileSync(
      path.join(root, '.runtime', 'dashboard_delivery_state.json'),
      JSON.stringify(deliveryState),
    );

    const loadedSession = readDashboardSession(root);
    const loadedJob = loadSessionJob(root, loadedSession);
    const touched = readTouchedTargets(root, loadedJob);
    const gallery = buildDeliveryGallery(root, deliveryState, loadedJob);
    assert.equal(touched.size, 1);
    assert.equal(gallery.images.length, 2);
    assert.equal(gallery.images.some((item) => item.path === current), true);
    assert.equal(gallery.images.some((item) => item.path === historical), true);
    assert.equal(gallery.groups[0].expectedImageCount, 2);
    assert.equal(gallery.groups[0].imageComplete, true);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('packaged group is absent even when output files remain on disk', () => {
  const root = temporaryRoot();
  try {
    fs.writeFileSync(path.join(root, 'output', 'road_rescue', 'group_0001', '01_cover.png'), 'old');
    const gallery = buildDeliveryGallery(
      root,
      { schema_version: 1, projects: { road_rescue: { pending_groups: {} } } },
      null,
    );
    assert.deepEqual(gallery.images, []);
    assert.deepEqual(gallery.groups, []);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('session job path cannot escape the project root', () => {
  const root = temporaryRoot();
  try {
    const session = { mode: 'job', job_id: 'outside', job_file: '../outside.json' };
    assert.equal(loadSessionJob(root, session), null);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
test('library groups keep batch identity and cannot expose paths outside their group', () => {
  const root=temporaryRoot();
  try {
    const relative='output/road_rescue/library/batch_test/group_0001/01_cover.png';
    fs.mkdirSync(path.dirname(path.join(root,relative)),{recursive:true});fs.writeFileSync(path.join(root,relative),'test');
    fs.writeFileSync(path.join(root,'output/road_rescue/group_0001/01_cover.png'),'legacy');
    const state={projects:{road_rescue:{pending_groups:{'1':{group_index:1,expected_image_count:1}},pending_library_groups:{'batch_test:1':{batch_id:'batch_test',group_index:1,expected_image_count:1,paths:[relative,'output/road_rescue/group_0001/01_cover.png']}}}}};
    const gallery=buildDeliveryGallery(root,state);
    assert.equal(gallery.images.length,2);assert.equal(gallery.groups.length,2);
    assert.equal(gallery.groups.filter(g=>g.libraryBatch==='batch_test').length,1);
    assert.equal(gallery.images.filter(i=>i.libraryBatch==='batch_test').length,1);
  } finally {fs.rmSync(root,{recursive:true,force:true});}
});
