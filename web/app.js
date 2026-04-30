const state = { selectedBriefDate: null, selectedCountry: null };
const PRESET_KEY = "displacement-monitor-presets";

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

function syncPathForCountry() {
  if (state.selectedCountry) {
    history.replaceState({}, "", `/country/${state.selectedCountry}`);
  } else {
    history.replaceState({}, "", "/dashboard");
  }
}

function loadPathState() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  if (parts[0] === "country" && parts[1]) {
    state.selectedCountry = parts[1].toUpperCase();
  }
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

function renderMap(data) {
  const points = data.points || [];
  q("mapView").innerHTML = `
    <div class="map-canvas">
      ${points.map(point => {
        const riskClass = point.risk_score >= 40 ? "high-risk" : (point.risk_score >= 25 ? "medium-risk" : "");
        return `<button class="map-dot ${riskClass}" data-country="${point.country_code}" title="${point.country_code}: ${point.items} items / risk ${point.risk_score}">
          <strong>${point.country_code}</strong>
          <span>Risk ${point.risk_score}</span>
          <span>${point.items} items</span>
          <span>${point.top_signal || "monitor"}</span>
        </button>`;
      }).join("")}
      <div class="map-legend">Each tile represents a country in the current dataset. Warmer fills indicate higher combined risk.</div>
    </div>
  `;
  q("mapView").querySelectorAll(".map-dot").forEach(button => {
    button.addEventListener("click", async () => {
      state.selectedCountry = button.dataset.country;
      q("countryFilter").value = state.selectedCountry;
      syncPathForCountry();
      await Promise.all([refresh(), loadCountryDetail()]);
    });
  });
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
    { label: "Country", render: row => `<button type="button" class="country-link" data-country="${row.country_code}">${row.country_code}</button>` },
    { label: "Items", render: row => row.items.toLocaleString() },
    { label: "Risk", render: row => row.risk_score.toFixed(1) },
    { label: "Confidence", render: row => row.avg_confidence.toFixed(2) },
    { label: "Top signal", render: row => row.top_signal || "n/a" },
    { label: "Top event", render: row => row.top_event_type || "n/a" },
    { label: "Population", render: row => row.top_population || "n/a" },
    { label: "Latest", render: row => row.latest_date || "n/a" },
  ]);
  q("countriesTable").querySelectorAll(".country-link").forEach(button => {
    button.addEventListener("click", async () => {
      state.selectedCountry = button.dataset.country;
      syncPathForCountry();
      await loadCountryDetail();
    });
  });
}

function renderCountryDetail(data) {
  q("countryDetailTitle").textContent = data.country_code ? `Country Items — ${data.country_code}` : "Country Items";
  const signalRows = (data.summary.signal_breakdown || []).slice(0, 5);
  const eventRows = (data.summary.event_breakdown || []).slice(0, 5);
  q("countryDetailSummary").innerHTML = `
    <div class="status-item"><strong>Items</strong><div class="muted">${data.summary.items}</div></div>
    <div class="status-item"><strong>Average confidence</strong><div class="muted">${data.summary.avg_confidence}</div></div>
    <div class="status-item"><strong>Top signal</strong><div class="muted">${data.summary.top_signal || "n/a"}</div></div>
    <div class="status-item"><strong>Top event</strong><div class="muted">${data.summary.top_event_type || "n/a"}</div></div>
    <div class="status-item"><strong>Top population</strong><div class="muted">${data.summary.top_population || "n/a"}</div></div>
    <div class="status-item"><strong>External metrics</strong><div class="muted">${(data.summary.external_metrics || []).map(([name, count]) => `${name} (${count})`).join(", ") || "n/a"}</div></div>
  `;
  q("countryDetailCharts").innerHTML = `
    <section class="mini-chart">
      <h3>Operational signal mix</h3>
      ${signalRows.map(([name, count]) => `<div class="muted">${name}: ${count}</div>`).join("") || `<div class="muted">n/a</div>`}
    </section>
    <section class="mini-chart">
      <h3>Event type mix</h3>
      ${eventRows.map(([name, count]) => `<div class="muted">${name}: ${count}</div>`).join("") || `<div class="muted">n/a</div>`}
    </section>
  `;
  q("countryDetailItems").innerHTML = `<div class="item-list">${
    data.latest_items.map(item => `
      <article class="item-card">
        <strong><a href="${item.url}" target="_blank" rel="noreferrer">${item.title}</a></strong>
        <div class="muted">${item.publisher || "Unknown"} • ${item.published_at || "n/a"}</div>
        <div class="muted">${item.event_type || "n/a"} • ${item.signal || "n/a"} • ${item.population_type || "n/a"} • confidence ${item.confidence ?? "n/a"}</div>
      </article>
    `).join("")
  }</div>`;
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

async function loadCountryDetail() {
  if (!state.selectedCountry) {
    return;
  }
  const params = new URLSearchParams();
  params.set("country", state.selectedCountry);
  syncPathForCountry();
  renderCountryDetail(await fetchJson("/api/country-detail", params));
}

function getPresets() {
  try {
    return JSON.parse(localStorage.getItem(PRESET_KEY) || "[]");
  } catch (_err) {
    return [];
  }
}

function savePresets(presets) {
  localStorage.setItem(PRESET_KEY, JSON.stringify(presets));
}

function refreshPresetSelect() {
  const presets = getPresets();
  q("presetSelect").innerHTML = `<option value="">Choose a saved view</option>${presets.map((preset, idx) => `<option value="${idx}">${preset.name}</option>`).join("")}`;
}

function applyPreset(preset) {
  q("countryFilter").value = preset.country || "";
  q("eventFilter").value = preset.event_type || "";
  q("populationFilter").value = preset.population_type || "";
  q("signalFilter").value = preset.signal || "";
  q("startFilter").value = preset.start || "";
  q("endFilter").value = preset.end || "";
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
  const [overview, countries, timeseries, flows, mapData] = await Promise.all([
    fetchJson("/api/overview", params),
    fetchJson("/api/countries", params),
    fetchJson("/api/timeseries", params),
    fetchJson("/api/displacement"),
    fetchJson("/api/map", params),
  ]);
  renderCards(overview.summary);
  renderFreshness(overview.freshness);
  renderBarList("signalBars", overview.top_signals.map(item => ({ signal: item.signal, value: item.items })), "signal");
  renderBarList("eventBars", overview.top_event_types.map(item => ({ event_type: item.event_type, value: item.items })), "event_type");
  renderMap(mapData);
  renderTimeline(timeseries);
  renderFlows(flows);
  renderCountries(countries.countries || []);
  q("exportItemsLink").href = `/export/items.csv?${params.toString()}`;
  if (q("countryFilter").value) {
    state.selectedCountry = q("countryFilter").value;
    await loadCountryDetail();
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  loadPathState();
  await loadFilters();
  if (state.selectedCountry) {
    q("countryFilter").value = state.selectedCountry;
  }
  refreshPresetSelect();
  await Promise.all([refresh(), loadBrief()]);
  for (const id of ["countryFilter", "eventFilter", "populationFilter", "signalFilter", "startFilter", "endFilter"]) {
    q(id).addEventListener("change", refresh);
  }
  q("refreshBtn").addEventListener("click", refresh);
  q("savePresetBtn").addEventListener("click", () => {
    const name = window.prompt("Preset name");
    if (!name) return;
    const params = Object.fromEntries(currentParams().entries());
    const presets = getPresets();
    presets.push({ name, ...params });
    savePresets(presets);
    refreshPresetSelect();
  });
  q("applyPresetBtn").addEventListener("click", async () => {
    const idx = q("presetSelect").value;
    if (idx === "") return;
    const preset = getPresets()[Number(idx)];
    if (!preset) return;
    applyPreset(preset);
    state.selectedCountry = preset.country || null;
    await refresh();
  });
  q("deletePresetBtn").addEventListener("click", () => {
    const idx = q("presetSelect").value;
    if (idx === "") return;
    const presets = getPresets();
    presets.splice(Number(idx), 1);
    savePresets(presets);
    refreshPresetSelect();
  });
});
