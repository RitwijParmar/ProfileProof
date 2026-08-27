"use strict";

const SAMPLE_URL = "https://www.linkedin.com/in/profileproof-demo";
const REAL_EXAMPLE_URL = "https://www.linkedin.com/in/seanthorne";

const nodes = Object.fromEntries(
  [
    "form", "url", "submit", "submit-text", "mode-badge", "mode-text", "mode-help",
    "sample-button", "workspace", "loading-state", "error-state", "error-title",
    "error-detail", "retry-button", "error-sample-button", "empty-state",
    "empty-sample-button", "profile-result", "avatar", "profile-name", "profile-headline",
    "profile-location", "source-chip", "profile-link", "completeness", "field-count",
    "confidence", "confidence-label", "latency", "cache-label", "schema-version",
    "dataset-version", "overview-tab", "json-tab", "overview-panel", "json-panel",
    "about-section", "about-text", "experience-section", "experience-count",
    "experience-list", "education-section", "education-count", "education-list",
    "skills-section", "skills-list", "certifications-section", "certifications-list",
    "languages-section", "languages-list", "provenance-list", "limitations",
    "json-output", "copy-json", "request-meta",
  ].map((id) => [id, document.getElementById(id)])
);

let licensedConfigured = false;
let defaultProvider = "demo";
let lastRequest = null;
let lastPayload = null;

function create(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = String(text);
  return element;
}

function clear(element) {
  element.replaceChildren();
}

function setView(view) {
  nodes["loading-state"].hidden = view !== "loading";
  nodes["error-state"].hidden = view !== "error";
  nodes["empty-state"].hidden = view !== "empty";
  nodes["profile-result"].hidden = view !== "result";
  nodes.workspace.setAttribute("aria-busy", String(view === "loading"));
}

function setMode(kind, label, help) {
  nodes["mode-badge"].className = `mode-badge ${kind}`.trim();
  nodes["mode-text"].textContent = label;
  nodes["mode-help"].textContent = help;
}

function initials(name) {
  if (!name) return "PP";
  return name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function formatDate(value) {
  if (!value) return null;
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en", {month: "short", year: "numeric", timeZone: "UTC"})
    .format(parsed);
}

function formatRange(dates = {}) {
  const start = formatDate(dates.start);
  const end = dates.is_current ? "Present" : formatDate(dates.end);
  if (start && end) return `${start} — ${end}`;
  return start || end || "Dates not provided";
}

function setSection(section, visible) {
  section.hidden = !visible;
}

function renderTimeline(container, items, type) {
  clear(container);
  items.forEach((item) => {
    const row = create("article", "timeline-item");
    row.append(create("span", "timeline-dot"));
    const copy = create("div");
    const title = type === "experience" ? item.title : item.school;
    const subtitle = type === "experience"
      ? [item.company, item.location].filter(Boolean).join(" · ")
      : [item.degree, item.field_of_study].filter(Boolean).join(" · ");
    copy.append(create("h3", "timeline-title", title || "Untitled record"));
    if (subtitle) copy.append(create("p", "timeline-subtitle", subtitle));
    copy.append(create("p", "timeline-meta", formatRange(item.dates)));
    if (item.description) copy.append(create("p", "timeline-description", item.description));
    row.append(copy);
    container.append(row);
  });
}

function renderChips(container, items) {
  clear(container);
  items.forEach((item) => container.append(create("span", "chip", item)));
}

function renderDetails(container, items, renderItem) {
  clear(container);
  items.forEach((item) => {
    const detail = renderItem(item);
    const row = create("div", "detail-item");
    row.append(create("strong", "", detail.title));
    if (detail.meta) row.append(create("span", "", detail.meta));
    container.append(row);
  });
}

function addDefinition(term, description) {
  const row = create("div");
  row.append(create("dt", "", term), create("dd", "", description || "—"));
  nodes["provenance-list"].append(row);
}

function confidenceLabel(value) {
  if (value === null || value === undefined) return "Not provided";
  if (value >= .9) return "High-confidence match";
  if (value >= .75) return "Confident match";
  return "Review recommended";
}

function renderProfile(payload, elapsedMs) {
  const profile = payload.profile || {};
  const source = payload.source || {};
  const meta = payload.meta || {};
  const experiences = profile.experience || [];
  const education = profile.education || [];
  const skills = profile.skills || [];
  const certifications = profile.certifications || [];
  const languages = profile.languages || [];
  const isSample = source.provider === "demo";

  nodes.avatar.textContent = initials(profile.name);
  nodes["profile-name"].textContent = profile.name || "Unnamed profile";
  nodes["profile-headline"].textContent = profile.headline || "Headline not available";
  nodes["profile-location"].textContent = profile.location || "Location not available";
  nodes["source-chip"].textContent = isSample ? "Sample data" : "Licensed match";
  nodes["source-chip"].className = `source-chip${isSample ? " sample" : ""}`;
  nodes["profile-link"].href = payload.canonical_url;
  nodes["profile-link"].hidden = isSample;

  const completeness = Math.round((meta.completeness || 0) * 100);
  const confidence = source.match_confidence;
  nodes.completeness.textContent = `${completeness}%`;
  nodes["field-count"].textContent = `${(meta.fields_present || []).length} profile groups present`;
  nodes.confidence.textContent = confidence === null || confidence === undefined
    ? "N/A" : `${Math.round(confidence * 100)}%`;
  nodes["confidence-label"].textContent = isSample ? "Fixture—not identity scored" : confidenceLabel(confidence);
  nodes.latency.textContent = `${elapsedMs} ms`;
  nodes["cache-label"].textContent = meta.cached ? "Served from warm cache" : "Fresh resolution";
  nodes["schema-version"].textContent = `v${payload.schema_version || "—"}`;
  nodes["dataset-version"].textContent = source.dataset_version
    ? `Dataset ${source.dataset_version}` : "Versioned response contract";

  setSection(nodes["about-section"], Boolean(profile.about));
  nodes["about-text"].textContent = profile.about || "";
  setSection(nodes["experience-section"], experiences.length > 0);
  nodes["experience-count"].textContent = `${experiences.length} ${experiences.length === 1 ? "role" : "roles"}`;
  renderTimeline(nodes["experience-list"], experiences, "experience");
  setSection(nodes["education-section"], education.length > 0);
  nodes["education-count"].textContent = `${education.length} ${education.length === 1 ? "record" : "records"}`;
  renderTimeline(nodes["education-list"], education, "education");

  setSection(nodes["skills-section"], skills.length > 0);
  renderChips(nodes["skills-list"], skills);
  setSection(nodes["certifications-section"], certifications.length > 0);
  renderDetails(nodes["certifications-list"], certifications, (item) => ({
    title: item.name,
    meta: [item.issuer, item.issued ? `Issued ${formatDate(item.issued)}` : null]
      .filter(Boolean).join(" · "),
  }));
  setSection(nodes["languages-section"], languages.length > 0);
  renderDetails(nodes["languages-list"], languages, (item) => ({
    title: item.name,
    meta: item.proficiency,
  }));

  clear(nodes["provenance-list"]);
  addDefinition("Provider", source.provider);
  addDefinition("Mode", source.mode);
  addDefinition("Licensed", source.licensed ? "Yes" : "No");
  addDefinition("Identifier", payload.public_identifier);
  clear(nodes.limitations);
  (source.limitations || []).forEach((item) => nodes.limitations.append(create("p", "", item)));

  lastPayload = payload;
  nodes["json-output"].textContent = JSON.stringify(payload, null, 2);
  nodes["request-meta"].textContent = `Request ${meta.request_id || "—"} · ${elapsedMs} ms`;
  selectTab("overview");
  setView("result");
}

function friendlyError(status, payload) {
  const title = payload?.title || "Profile resolution failed";
  let detail = payload?.detail || "The API did not return a usable response. Please try again.";
  if (status === 404) detail = "No confident profile match was found. Check the URL and try again.";
  if (status === 429) detail = "The resolver is receiving too many requests. Wait briefly and retry.";
  if (status >= 500) detail = "The data source is temporarily unavailable. Your input was not stored.";
  return {title, detail};
}

function showError(title, detail) {
  nodes["error-title"].textContent = title;
  nodes["error-detail"].textContent = detail;
  setView("error");
}

async function resolveProfile({sample = false} = {}) {
  const requestedUrl = sample ? SAMPLE_URL : nodes.url.value.trim();
  const provider = sample ? "demo" : defaultProvider;
  if (!requestedUrl) {
    showError("Add a profile URL", "Enter a complete LinkedIn profile URL before continuing.");
    nodes.url.focus();
    return;
  }
  if (!licensedConfigured && provider === "demo" && requestedUrl !== SAMPLE_URL) {
    showError(
      "Live enrichment is not connected yet",
      "This deployment is healthy, but its licensed data key is not configured. Open the complete sample profile to explore the product flow."
    );
    return;
  }

  lastRequest = {sample, requestedUrl};
  nodes.url.value = requestedUrl;
  nodes.submit.disabled = true;
  nodes["submit-text"].textContent = "Resolving…";
  setView("loading");
  const started = performance.now();
  try {
    const response = await fetch("/v1/profiles/resolve", {
      method: "POST",
      headers: {"content-type": "application/json", accept: "application/json"},
      body: JSON.stringify({profile_url: requestedUrl, provider}),
    });
    let payload;
    try {
      payload = await response.json();
    } catch (_error) {
      throw new Error(`The API returned HTTP ${response.status} without a JSON response.`);
    }
    if (!response.ok) {
      const error = friendlyError(response.status, payload);
      showError(error.title, error.detail);
      return;
    }
    renderProfile(payload, Math.round(performance.now() - started));
  } catch (error) {
    showError("Could not reach the resolver", error instanceof Error ? error.message : String(error));
  } finally {
    nodes.submit.disabled = false;
    nodes["submit-text"].textContent = "Analyze profile";
  }
}

function selectTab(name) {
  const overview = name === "overview";
  nodes["overview-tab"].setAttribute("aria-selected", String(overview));
  nodes["json-tab"].setAttribute("aria-selected", String(!overview));
  nodes["overview-tab"].tabIndex = overview ? 0 : -1;
  nodes["json-tab"].tabIndex = overview ? -1 : 0;
  nodes["overview-panel"].hidden = !overview;
  nodes["json-panel"].hidden = overview;
}

async function loadCapabilities() {
  try {
    const response = await fetch("/v1/capabilities", {headers: {accept: "application/json"}});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    const licensed = payload.providers.find((item) => item.name === "people_data_labs");
    licensedConfigured = Boolean(licensed?.configured);
    defaultProvider = licensedConfigured ? "people_data_labs" : "demo";
    if (licensedConfigured) {
      nodes.url.value = REAL_EXAMPLE_URL;
      setMode("", "Licensed data connected", "Professional-only enrichment · confidence threshold 8/10 · no contact fields");
    } else {
      nodes.url.value = SAMPLE_URL;
      setMode("sample", "Sample preview", "Live API is healthy · previewing the complete product flow with clearly labeled sample data");
      await resolveProfile({sample: true});
    }
  } catch (_error) {
    setMode("error", "Source check unavailable", "The API is online, but its capability endpoint could not be read.");
    setView("empty");
  }
}

nodes.form.addEventListener("submit", (event) => {
  event.preventDefault();
  void resolveProfile();
});
nodes["sample-button"].addEventListener("click", () => void resolveProfile({sample: true}));
nodes["empty-sample-button"].addEventListener("click", () => void resolveProfile({sample: true}));
nodes["error-sample-button"].addEventListener("click", () => void resolveProfile({sample: true}));
nodes["retry-button"].addEventListener("click", () => void resolveProfile(lastRequest || {}));
nodes["overview-tab"].addEventListener("click", () => selectTab("overview"));
nodes["json-tab"].addEventListener("click", () => selectTab("json"));
nodes["copy-json"].addEventListener("click", async () => {
  if (!lastPayload) return;
  try {
    await navigator.clipboard.writeText(JSON.stringify(lastPayload, null, 2));
    nodes["copy-json"].textContent = "Copied";
    window.setTimeout(() => { nodes["copy-json"].textContent = "Copy JSON"; }, 1600);
  } catch (_error) {
    nodes["copy-json"].textContent = "Copy unavailable";
  }
});

[nodes["overview-tab"], nodes["json-tab"]].forEach((tab, index, tabs) => {
  tab.addEventListener("keydown", (event) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "ArrowRight" ? (index + 1) % tabs.length : (index - 1 + tabs.length) % tabs.length;
    tabs[next].click();
    tabs[next].focus();
  });
});

void loadCapabilities();
