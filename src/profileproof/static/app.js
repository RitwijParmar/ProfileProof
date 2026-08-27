"use strict";

const form = document.getElementById("form");
const output = document.getElementById("output");
const meta = document.getElementById("meta");
const button = document.getElementById("submit");
const provider = document.getElementById("provider");
const url = document.getElementById("url");
const capabilityStatus = document.getElementById("capability-status");

async function loadCapabilities() {
  try {
    const response = await fetch("/v1/capabilities", {headers: {accept: "application/json"}});
    const payload = await response.json();
    const licensed = payload.providers.find((item) => item.name === "people_data_labs");
    const option = provider.querySelector('option[value="people_data_labs"]');
    if (licensed?.configured) {
      capabilityStatus.textContent = "Licensed provider configured · real profile lookups enabled";
      capabilityStatus.className = "status ok";
      provider.value = "people_data_labs";
    } else {
      option.disabled = true;
      provider.value = "demo";
      url.value = "https://www.linkedin.com/in/profileproof-demo";
      capabilityStatus.textContent = "Licensed provider not configured · synthetic fallback active";
      capabilityStatus.className = "status warn";
    }
  } catch (error) {
    capabilityStatus.textContent = `Capability check failed: ${String(error)}`;
    capabilityStatus.className = "status warn";
  }
}

provider.addEventListener("change", () => {
  url.value = provider.value === "demo"
    ? "https://www.linkedin.com/in/profileproof-demo"
    : "https://www.linkedin.com/in/seanthorne";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  button.disabled = true;
  output.textContent = "requesting…";
  const started = performance.now();
  try {
    const response = await fetch("/v1/profiles/resolve", {
      method: "POST",
      headers: {"content-type": "application/json"},
      body: JSON.stringify({profile_url: url.value, provider: provider.value}),
    });
    const payload = await response.json();
    const elapsed = (performance.now() - started).toFixed(0);
    meta.textContent = `HTTP ${response.status} · ${elapsed} ms · request ${response.headers.get("x-request-id")}`;
    output.textContent = JSON.stringify(payload, null, 2);
  } catch (error) {
    output.textContent = String(error);
  } finally {
    button.disabled = false;
  }
});

void loadCapabilities();
