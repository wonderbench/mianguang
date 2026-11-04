(() => {
  "use strict";
  const overview = document.querySelector("[data-overview]");
  const history = document.querySelector("[data-history]");
  if (!overview && !history) return;

  const stamp = () => ({ wall: Date.now(), perf: performance.now() });
  const initial = document.querySelector("[data-server-ms]");
  let clock = { server: Number(initial.dataset.serverMs), wall: performance.timeOrigin, perf: 0 };
  const serverNow = () => clock.server + Math.max(0, Date.now() - clock.wall, performance.now() - clock.perf);
  const syncClock = (value, started) => { clock = { server: Number(value), ...started }; };
  const refreshError = document.querySelector("[data-refresh-error]");
  const showError = (element, text) => { element.textContent = text; element.hidden = !text; };
  const refreshMessage = "更新失败，旧观测会按时间自动过期。请检查连接；登录已过期时请重新登录。";
  const labels = { fresh: "最近有新上报", expired: "观测已过期", no_report: "超过60秒无新上报", waiting: "等待首包", disabled: "已停用" };

  function expireSnapshots() {
    const now = serverNow();
    const counts = { fresh: 0, expired: 0, no_report: 0, waiting: 0, disabled: 0 };
    document.querySelectorAll("[data-snapshot]").forEach(snapshot => {
      let state = snapshot.dataset.state;
      if (state !== "waiting" && state !== "disabled") {
        if (now - Number(snapshot.dataset.receivedMs) > 60000) state = "no_report";
        else if (state === "fresh" && (!snapshot.dataset.capturedMs || now - Number(snapshot.dataset.receivedMs) > 30000 || now - Number(snapshot.dataset.capturedMs) > 30000)) state = "expired";
        snapshot.dataset.state = state;
        const badge = snapshot.querySelector("[data-connectivity]");
        badge.textContent = labels[state];
        badge.className = `badge state-${state}`;
        if (state !== "fresh") {
          snapshot.querySelector("[data-occupancy]").textContent = "未知";
          ["rr", "hr", "lamp"].forEach(key => { snapshot.querySelector(`[data-${key}]`).textContent = "—"; });
          snapshot.querySelectorAll("[data-metric-note]").forEach(note => { note.textContent = "观测已过期"; });
        }
      }
      counts[state] += 1;
    });
    if (overview) {
      Object.entries(counts).forEach(([state, count]) => { overview.querySelector(`[data-count="${state}"]`).textContent = count; });
      overview.querySelector("[data-not-fresh-count]").textContent = Object.values(counts).reduce((sum, count) => sum + count, 0) - counts.fresh;
    }
  }

  async function get(url) {
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store", redirect: "error", signal: AbortSignal.timeout(12000) });
    if (!response.ok) throw new Error(response.status === 400 ? "时间范围无效：请使用最近 7 天内、最多 24 小时的 UTC 整分钟窗口。" : refreshMessage);
    return response;
  }

  let currentBusy = false;
  async function refreshCurrent() {
    if (currentBusy) return;
    if (history && document.querySelector("[data-current-region]").dataset.active === "false") return;
    currentBusy = true;
    const started = stamp();
    try {
      const response = await get(overview ? overview.dataset.refreshUrl : history.dataset.detailUrl);
      const documentCopy = new DOMParser().parseFromString(await response.text(), "text/html");
      const selector = overview ? "[data-overview-content]" : "[data-current-region]";
      const content = documentCopy.querySelector(selector);
      if (!content) throw new Error(refreshMessage);
      syncClock(content.dataset.serverMs, started);
      if (overview) overview.replaceChildren(content);
      else document.querySelector(selector).replaceWith(content);
      expireSnapshots();
      showError(refreshError, "");
    } catch (error) {
      showError(refreshError, refreshMessage);
    } finally {
      currentBusy = false;
    }
  }

  let refreshSeries = () => {};
  if (history) {
    const form = history.querySelector("[data-range-form]");
    const historyError = history.querySelector("[data-history-error]");
    const result = history.querySelector("[data-history-result]");
    const exportLink = history.querySelector("[data-export]");
    const iso = ms => new Date(ms).toISOString();
    const inputTime = value => value.slice(0, 16);
    const readable = value => value.slice(0, 19).replace("T", " ");
    form.elements.from.value = inputTime(history.dataset.initialFrom);
    form.elements.to.value = inputTime(history.dataset.initialTo);
    let rollingHours = 8;
    let requestNumber = 0;
    let pending = false;
    let lastGoodQuery = "";

    function selectQuick(hours) {
      rollingHours = hours;
      history.querySelectorAll("[data-hours]").forEach(button => button.setAttribute("aria-pressed", String(Number(button.dataset.hours) === hours)));
      if (hours) {
        const end = Math.floor(serverNow() / 60000) * 60000;
        form.elements.from.value = inputTime(iso(end - hours * 3600000));
        form.elements.to.value = inputTime(iso(end));
      }
    }

    function drawChart(svg, buckets, key) {
      const namespace = "http://www.w3.org/2000/svg";
      svg.replaceChildren();
      const add = (tag, attributes, text) => {
        const element = document.createElementNS(namespace, tag);
        Object.entries(attributes).forEach(([name, value]) => element.setAttribute(name, value));
        if (text !== undefined) element.textContent = text;
        svg.append(element);
      };
      const min = key === "rr_bpm" ? 10 : 60;
      const max = key === "rr_bpm" ? 25 : 100;
      const ticks = key === "rr_bpm" ? [10, 15, 20, 25] : [60, 80, 100];
      const x = index => 52 + index / Math.max(1, buckets.length - 1) * 888;
      const y = value => 158 - (value - min) / (max - min) * 136;
      ticks.forEach(value => {
        add("line", { x1: 52, x2: 940, y1: y(value), y2: y(value), class: "grid" });
        add("text", { x: 40, y: y(value) + 4, "text-anchor": "end" }, value);
      });
      const indexes = [...new Set([0, Math.floor((buckets.length - 1) / 2), buckets.length - 1])];
      indexes.forEach(index => {
        add("text", { x: x(index), y: 186, "text-anchor": index === 0 ? "start" : index === buckets.length - 1 ? "end" : "middle" }, readable(buckets[index].minute).slice(5, 16));
      });
      let points = [];
      let valid = 0;
      const finish = () => {
        if (points.length === 1) add("circle", { cx: points[0][0], cy: points[0][1], r: 2.5, class: "chart-dot" });
        else if (points.length) add("path", { d: points.map(([px, py], index) => `${index ? "L" : "M"}${px.toFixed(2)},${py.toFixed(2)}`).join(" "), class: "chart-line" });
        points = [];
      };
      buckets.forEach((bucket, index) => {
        if (bucket[key] === null) finish();
        else { points.push([x(index), y(bucket[key])]); valid += 1; }
      });
      finish();
      if (!valid) add("text", { x: 496, y: 90, "text-anchor": "middle", class: "empty-chart" }, "此窗口没有完整且有效的分钟点");
      add("title", {}, `共 ${buckets.length} 分钟，${valid} 个完整有效点；缺测或无效分钟断线。时间为 UTC。`);
    }

    async function loadSeries() {
      const number = ++requestNumber;
      pending = true;
      const started = stamp();
      const query = new URLSearchParams({ from: `${form.elements.from.value}:00Z`, to: `${form.elements.to.value}:00Z` }).toString();
      if (query !== lastGoodQuery) result.hidden = true;
      if (exportLink) exportLink.hidden = true;
      try {
        const response = await get(`${history.dataset.seriesUrl}?${query}`);
        const data = await response.json();
        if (number !== requestNumber) return;
        syncClock(Date.parse(data.server_time), started);
        Object.entries(data.summary).forEach(([key, value]) => {
          const target = history.querySelector(`[data-summary="${key}"]`);
          if (target) target.textContent = value === null ? "—" : `${(value * 100).toFixed(1)}%`;
        });
        const summary = data.summary;
        history.querySelector('[data-slot-count="report"]').textContent = `${summary.received_slots} / ${summary.expected_slots} 个完整时隙`;
        history.querySelector('[data-slot-count="rr"]').textContent = `${summary.rr_valid_slots} / ${summary.received_slots} 个已收到时隙`;
        history.querySelector('[data-slot-count="hr"]').textContent = `${summary.hr_valid_slots} / ${summary.received_slots} 个已收到时隙`;
        history.querySelector("[data-effective-range]").textContent = `有效范围：${readable(data.effective_range.from)} — ${readable(data.effective_range.to)} UTC。更新：${readable(data.server_time)} UTC。`;
        history.querySelectorAll("[data-chart]").forEach(svg => drawChart(svg, data.buckets, svg.dataset.chart));
        if (exportLink) { exportLink.href = `${history.dataset.exportUrl}?${query}`; exportLink.hidden = false; }
        lastGoodQuery = query;
        result.hidden = false;
        showError(historyError, "");
        expireSnapshots();
      } catch (error) {
        if (number === requestNumber) showError(historyError, error.message === refreshMessage || error.message.startsWith("时间范围") ? error.message : "趋势读取失败，请检查连接并重试。");
      } finally {
        if (number === requestNumber) pending = false;
      }
    }
    history.querySelectorAll("[data-hours]").forEach(button => button.addEventListener("click", () => { selectQuick(Number(button.dataset.hours)); loadSeries(); }));
    form.addEventListener("input", () => {
      selectQuick(null);
      requestNumber += 1;
      pending = false;
      result.hidden = true;
      if (exportLink) exportLink.hidden = true;
    });
    form.addEventListener("submit", event => { event.preventDefault(); selectQuick(null); loadSeries(); });
    refreshSeries = () => {
      if (rollingHours && !pending && document.querySelector("[data-current-region]").dataset.active === "true") {
        selectQuick(rollingHours);
        loadSeries();
      }
    };
    loadSeries();
  }

  expireSnapshots();
  setInterval(expireSnapshots, 1000);
  setInterval(() => { if (!document.hidden) { refreshCurrent(); refreshSeries(); } }, 15000);
  document.addEventListener("visibilitychange", () => {
    expireSnapshots();
    if (!document.hidden) { refreshCurrent(); refreshSeries(); }
  });
})();
