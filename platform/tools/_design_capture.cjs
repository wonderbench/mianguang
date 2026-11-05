// One-off PR evidence; run beside serve.py with playwright@1.62.1 installed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const out = path.resolve('artifacts');
const before = 'http://127.0.0.1:8860';
const after = 'http://127.0.0.1:8861';
const detail = '/bindings/10000000-0000-0000-0000-000000000001/';
const report = { started: new Date().toISOString(), playwright: require('playwright/package.json').version, screenshots: [], checks: [] };
fs.mkdirSync(out, { recursive: true });
let browser, page;

function passed(name, evidence) {
  report.checks.push({ name, status: 'passed', evidence });
  console.log(`PASS ${name}`);
}

async function open(url, width = 1440, height = 1000) {
  await page.setViewportSize({ width, height });
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  if (new URL(url).pathname.startsWith('/bindings/')) {
    await page.locator('[data-chart] title').first().waitFor({ state: 'attached' });
  }
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function screenshot(name) {
  const file = `${name}.jpg`;
  await page.screenshot({ path: path.join(out, file), type: 'jpeg', quality: 80, fullPage: true, animations: 'disabled' });
  report.screenshots.push(file);
}

async function layout(name) {
  const size = await page.evaluate(() => ({ viewport: document.documentElement.clientWidth, content: document.documentElement.scrollWidth }));
  assert.ok(size.content <= size.viewport + 1, `${name}: horizontal overflow ${JSON.stringify(size)}`);
  passed(name, size);
}

async function charts(name, narrow) {
  const plots = await page.locator('[data-chart]').evaluateAll(nodes => nodes.map(svg => {
    const texts = [...svg.querySelectorAll('text')];
    const times = texts.filter(node => node.getAttribute('y') === '186');
    const tick = texts[0];
    const matrix = tick.getScreenCTM();
    return {
      series: svg.dataset.chart,
      width: svg.clientWidth,
      viewBoxWidth: svg.viewBox.baseVal.width,
      actualFontPx: parseFloat(getComputedStyle(tick).fontSize) * Math.hypot(matrix.a, matrix.b),
      ticks: texts.filter(node => node.getAttribute('x') === '40').map(node => node.textContent),
      times: times.map(node => { const r = node.getBoundingClientRect(); return { label: node.textContent, left: r.left, right: r.right }; }),
      paths: svg.querySelectorAll('path.chart-line').length,
      isolatedPoints: svg.querySelectorAll('circle.chart-dot').length,
      description: svg.querySelector('title').textContent
    };
  }));
  assert.equal(plots.length, 2);
  for (const plot of plots) {
    assert.equal(plot.viewBoxWidth, plot.width, `${name}: viewBox matches measured width`);
    assert.ok(Math.abs(plot.actualFontPx - 13) < 0.5, `${name}: actual tick size ${plot.actualFontPx}px`);
    assert.deepEqual(plot.ticks, plot.series === 'rr_bpm' ? ['10', '15', '20', '25'] : ['60', '80', '100']);
    assert.equal(plot.times.length, narrow ? 2 : 3);
    for (let i = 1; i < plot.times.length; i++) assert.ok(plot.times[i - 1].right < plot.times[i].left, `${name}: overlapping time labels`);
    assert.ok(plot.paths > 1 && plot.isolatedPoints > 0, `${name}: gaps and isolated points remain visible`);
    assert.match(plot.description, /缺测或无效分钟断线.*UTC/);
  }
  passed(name, plots);
}

async function main() {
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ locale: 'zh-CN', timezoneId: 'UTC', deviceScaleFactor: 1 });
  page = await context.newPage();
  page.setDefaultTimeout(10000);

  // Baseline is evidence only: do not apply the new design assertions to it.
  for (const [name, route, width, height] of [
    ['before-desktop-overview', '/', 1440, 1000],
    ['before-desktop-detail', detail, 1440, 1000],
    ['before-desktop-login', '/login/', 1440, 1000],
    ['before-mobile390-detail', detail, 390, 844]
  ]) {
    await open(before + route, width, height);
    await screenshot(name);
  }

  for (const [device, width, height] of [['desktop', 1440, 1000], ['mobile390', 390, 844]]) {
    for (const [view, route] of [['overview', '/'], ['detail', detail], ['login', '/login/']]) {
      const name = `after-${device}-${view}`;
      await open(after + route, width, height);
      await layout(name);
      if (view === 'detail') await charts(`${name}-charts`, width < 480);
      await screenshot(name);
    }
  }

  await open(after + detail + '?long=1', 320, 800);
  assert.match(await page.locator('h1').innerText(), /东侧观察区/);
  await layout('mobile320-long-title');
  await charts('mobile320-long-title-charts', true);
  await screenshot('after-mobile320-long-title');

  await open(after + '/?empty=1', 320, 800);
  assert.equal(await page.locator('.bed-card').count(), 0);
  assert.ok(await page.getByRole('heading', { name: '暂无绑定床位' }).isVisible());
  await layout('mobile320-empty');
  await screenshot('after-mobile320-empty');

  await open(after + '/login/?error=1', 320, 800);
  assert.match(await page.getByRole('alert').innerText(), /账号或密码不正确/);
  assert.ok(await page.getByLabel('账号', { exact: true }).isVisible());
  assert.ok(await page.getByLabel('密码', { exact: true }).isVisible());
  await layout('mobile320-login-error');
  await screenshot('after-mobile320-login-error');

  await open(after + detail + '?ended=1', 320, 800);
  assert.equal(await page.locator('[data-current-region]').getAttribute('data-active'), 'false');
  assert.equal(await page.locator('[data-current-region] [data-snapshot]').count(), 0);
  assert.ok(await page.locator('[data-history-result]').isVisible());
  await layout('mobile320-ended-binding');
  await screenshot('after-mobile320-ended-binding');

  await open(after + '/?viewer=1', 320, 800);
  assert.equal(await page.getByRole('link', { name: '平台管理' }).count(), 0);
  assert.equal(await page.locator('.diagnostics').count(), 0);
  await layout('mobile320-viewer-overview');
  await open(after + detail + '?viewer=1', 320, 800);
  assert.equal(await page.locator('[data-export]').count(), 0);
  assert.equal(await page.getByRole('link', { name: '平台管理' }).count(), 0);
  await layout('mobile320-viewer-detail');
  passed('viewer-permissions', 'No management, unbound-device diagnostics, or CSV controls');

  // Freeze timers only after a fresh load, to isolate resize from the 15s poll.
  await context.close();
  const controlled = await browser.newContext({ locale: 'zh-CN', timezoneId: 'UTC', deviceScaleFactor: 1 });
  page = await controlled.newPage();
  page.setDefaultTimeout(10000);
  await page.clock.install();
  await open(after + detail);
  await page.clock.pauseAt(await page.evaluate(() => Date.now() + 100));
  let resizeRequests = 0;
  const countFetch = request => { if (['fetch', 'xhr'].includes(request.resourceType())) resizeRequests++; };
  page.on('request', countFetch);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.clock.runFor(100);
  await charts('resize-redraws-cached-buckets', true);
  assert.equal(resizeRequests, 0, 'Resizing must not fetch');
  passed('resize-does-not-fetch', { requests: resizeRequests });
  page.off('request', countFetch);
  await page.clock.resume();

  // One failed changed-range request must not expose previous results or CSV.
  await page.route('**/api/**', route => route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"unavailable"}' }));
  const from = page.locator('[data-range-form] input[name="from"]');
  const changed = new Date(new Date((await from.inputValue()) + 'Z').getTime() + 60000).toISOString().slice(0, 16);
  await from.fill(changed);
  assert.equal(await page.locator('[data-history-result]').isVisible(), false);
  assert.equal(await page.locator('[data-export]').isVisible(), false);
  await page.locator('[data-range-form]').getByRole('button', { name: '查询', exact: true }).click();
  await page.locator('[data-history-error]').waitFor({ state: 'visible' });
  assert.equal(await page.locator('[data-history-result]').isVisible(), false);
  assert.equal(await page.locator('[data-export]').isVisible(), false);
  passed('failed-changed-query-hides-old-result-and-csv', await page.locator('[data-history-error]').innerText());
  await controlled.close();

  // Offline freshness must still progress using the browser's own timer.
  const offline = await browser.newContext({ locale: 'zh-CN', timezoneId: 'UTC' });
  page = await offline.newPage();
  await page.clock.install();
  await open(after + '/', 390, 844);
  const snapshot = page.locator('[data-snapshot]').first();
  assert.equal(await snapshot.getAttribute('data-state'), 'fresh');
  await offline.setOffline(true);
  for (const [seconds, expected] of [[31, 'expired'], [62, 'no_report']]) {
    await page.clock.fastForward(31000);
    const observed = await snapshot.evaluate(node => ({
      state: node.dataset.state,
      label: node.querySelector('[data-connectivity]').textContent,
      occupancy: node.querySelector('[data-occupancy]').textContent,
      values: ['rr', 'hr', 'lamp'].map(key => node.querySelector(`[data-${key}]`).textContent),
      reasons: [...node.querySelectorAll('[data-metric-note]')].map(note => note.textContent)
    }));
    assert.equal(observed.state, expected);
    assert.equal(observed.occupancy, '未知');
    assert.deepEqual(observed.values, ['—', '—', '—']);
    assert.ok(observed.reasons.every(reason => reason === '观测已过期'));
    assert.equal(await page.locator('[data-count="fresh"]').innerText(), '0');
    passed(`offline-${seconds}s-${expected}`, observed);
  }
  await page.locator('[data-refresh-error]').waitFor({ state: 'visible' });
  passed('offline-refresh-error-visible', await page.locator('[data-refresh-error]').innerText());
  await offline.close();
}

main().catch(async error => {
  report.error = error.stack;
  process.exitCode = 1;
  console.error(error);
  if (page && !page.isClosed()) await screenshot('failure').catch(() => {});
}).finally(async () => {
  report.finished = new Date().toISOString();
  report.status = report.error ? 'failed' : 'passed';
  fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
  if (browser) await browser.close();
});
