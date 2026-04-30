const state = { selectedBriefDate: null };

function q(id) { return document.getElementById(id); }

function currentParams() {
  const params = new URLSearchParams();
  for (const [key, value] of [
    ["country", q("countryFilter").value],
    ["event_type", q("eventFilter").value],
    ["population_type", q("populationFilter").value],
    ["signal", q("signalFilter").value],
    ["start", q("startFilter").value],
    ["end", q("endFilter").value],
  ]) {
    if (value) params.set(key, value);
  }
  return params;
}

async function fetchJson(path, params = new URLSearchParams()) {
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const res = await fetch(`${path}${suffix}`);
  if (!res.ok) throw new Error(`Failed to load ${path}`);
  return res.json();
}

function renderCards(summary) {
  const items = [
    ["Items in view", summary.items],
    ["Reports", summary.reports],
    ["Anomaly days", summary.anomaly_days],
    ["Avg confidence", summary.avg_confidence],
  ];
  q("summaryCards").innerHTML = items.map(([label, value]) => `
    <article class="card">
      <div class="muted">${label}</div>
      <span class="value">${value}</span>
    </article>
  `).join("");
}

function renderBarList(targetId, items, keyName) {
  const max = Math.max(1, ...items.map(item => item.value));
  q(targetId).innerHTML = `<div class="bar-list">${
    items.map(item => `
      <div class="bar-row">
        <header><span>${item[keyName]}</span><strong>${item.value.toLocaleString()}</strong></header>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.round((item.value / max) * 100)}%"></div></div>
      </div>
    `).join("")
  }</div>`;
}

function renderFreshness(items) {
  q("freshnessList").innerHTML = items.map(item => `
    <div class="status-item">
      <div class="panel-head">
        <strong>${item.source}</strong>
        <span class="badge ${item.status.replace("-", "_")}">${item.status.replace("_", " ")}</span>
      </div>
      <div class="muted">Records: ${item.records.toLocaleString()}</div>
      <div class="muted">Last seen: ${item.last_seen || "n/a"}${item.age_hours !== null ? ` (${item.age_hours}h ago)` : ""}</div>
    </div>
  `).join("");
}

function linePath(points, width, height, maxValue) {
  if (!points.length) return "";
  return points.map((point, index) => {
    const x = (index / Math.max(points.length - 1, 1)) * width;
    const y = height - ((point.value || 0) / Math.max(maxValue, 1)) * height;
    return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
  }).join(" ");
}

function renderTimeline(timeseries) {
  const media = timeseries.media || [];
  const metrics = timeseries.metrics || [];
  const width = 860;
  const height = 220;
  const mediaMax = Math.max(1, ...media.map(point => point.count || 0));
  const mediaPath = linePath(media.map(point => ({ value: point.count })), width, height, mediaMax);
  const extraMetric = metrics[0] || null;
  const extraMax = extraMetric ? Math.max(1, ...extraMetric.series.map(point => point.value || 0)) : 1;
  const extraPath = extraMetric ? linePath(extraMetric.series, width, height, extraMax) : "";

  q("timelineHint").textContent = extraMetric
    ? `Media coverage and ${extraMetric.metric_name}`
    : "Media coverage over time";

  q("timelineChart").innerHTML = `
    <svg class="svg-chart" viewBox="0 0 ${width} ${height + 40}" preserveAspectRatio="none">
      <line x1="0" y1="${height}" x2="${width}" y2="${height}" stroke="#c8bea9" stroke-width="1"></line>
      <path d="${mediaPath}" fill="none" stroke="#1f7a5c" stroke-width="3"></path>
      ${extraMetric ? `<path d="${extraPath}" fill="none" stroke="#d96c3f" stroke-width="2.5" stroke-dasharray="6 5"></path>` : ""}
      <text x="0" y="${height + 24}" fill="#5b655b" font-size="12">Start: ${media[0] ? media[0].date : "n/a"}</text>
      <text x="${width - 170}" y="${height + 24}" fill="#5b655b" font-size="12">End: ${media.length ? media[media.length - 1].date : "n/a"}</text>
    </svg>
    <div class="muted">Solid line: media coverage. ${extraMetric ? `Dashed line: ${extraMetric.metric_name}.` : ""}</div>
  `;
}

function renderTable(targetId, rows, columns) {
  q(targetId).innerHTML = `
    <table>
      <thead><tr>${columns.map(col => `<th>${col.label}</th>`).join("")}</tr></thead>
      <tbody>${rows.map(row => `<tr>${columns.map(col => `<td>${col.render(row)}</td>`).join("")}</tr>`).join("")}</tbody>
    </table>
  `;
}

function renderFlows(flows) {
  const cols = [
    { label: "Country", render: row => row.name },
    { label: "Value", render: row => Number(row.value).toLocaleString() },
    { label: "Badge", render: row => `<span class="badge ${row.badge}">${row.badge}</span>` },
  ];
  renderTable("originsTable", flows.origins || [], cols);
  renderTable("hostsTable", flows.hosts || [], cols);
}

function renderCountries(rows) {
  renderTable("countriesTable", rows, [
    { label: "Country", render: row => row.country_code },
    { label: "Items", render: row => row.items.toLocaleString() },
    { label: "Confidence", render: row => row.avg_confidence.toFixed(2) },
    { label: "Top signal", render: row => row.top_signal || "n/a" },
    { label: "Top event", render: row => row.top_event_type || "n/a" },
    { label: "Population", render: row => row.top_population || "n/a" },
    { label: "Latest", render: row => row.latest_date || "n/a" },
  ]);
}

function renderBriefList(data) {
  q("briefList").innerHTML = data.reports.map(report => `
    <div class="brief-item">
      <button type="button" data-date="${report.date}">
        <strong>${report.date}</strong>
        <div class="muted">Selected items: ${(report.meta.items_selected || 0).toLocaleString()}</div>
      </button>
    </div>
  `).join("");
  q("briefTitle").textContent = data.selected_date ? `Brief Viewer — ${data.selected_date}` : "Brief Viewer";
  q("briefContent").textContent = data.brief_markdown || "No report markdown found for this date.";
  q("briefList").querySelectorAll("button[data-date]").forEach(button => {
    button.addEventListener("click", async () => {
      state.selectedBriefDate = button.dataset.date;
      await loadBrief();
    });
  });
}

async function loadBrief() {
  const params = new URLSearchParams();
  if (state.selectedBriefDate) params.set("date", state.selectedBriefDate);
  renderBriefList(await fetchJson("/api/briefs", params));
}

async function loadFilters() {
  const data = await fetchJson("/api/filters");
  const fill = (id, values) => {
    q(id).insertAdjacentHTML("beforeend", values.map(value => `<option value="${value}">${value}</option>`).join(""));
  };
  fill("countryFilter", data.countries);
  fill("eventFilter", data.event_types);
  fill("populationFilter", data.population_types);
  fill("signalFilter", data.signals);
}

async function refresh() {
  const params = currentParams();
  const [overview, countries, timeseries, flows] = await Promise.all([
    fetchJson("/api/overview", params),
    fetchJson("/api/countries", params),
    fetchJson("/api/timeseries", params),
    fetchJson("/api/displacement"),
  ]);
  renderCards(overview.summary);
  renderFreshness(overview.freshness);
  renderBarList("signalBars", overview.top_signals.map(item => ({ signal: item.signal, value: item.items })), "signal");
  renderBarList("eventBars", overview.top_event_types.map(item => ({ event_type: item.event_type, value: item.items })), "event_type");
  renderTimeline(timeseries);
  renderFlows(flows);
  renderCountries(countries.countries || []);
}

document.addEventListener("DOMContentLoaded", async () => {
  await loadFilters();
  await Promise.all([refresh(), loadBrief()]);
  for (const id of ["countryFilter", "eventFilter", "populationFilter", "signalFilter", "startFilter", "endFilter"]) {
    q(id).addEventListener("change", refresh);
  }
  q("refreshBtn").addEventListener("click", refresh);
});
