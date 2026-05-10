const LINKS = {
  github: "https://github.com/<org>/pheromone",
  demo: "https://<your-demo-url>",
  hf: "https://huggingface.co/spaces/<org>/pheromone",
  x: "https://x.com/<handle>",
  contact: "mailto:hello@example.com",
};

const steps = [
  {
    title: "Intake → parse notice into RecallSpec",
    tier: "notice_ingested",
    asOf: "2026-05-09T00:00:00Z",
    body:
      "Intake transforms a raw recall notice into a strict RecallSpec schema: hazard, severity, scope, and product clues. This structured output is the contract for downstream agents.",
    facts: [
      "Hazard: Salmonella",
      "Severity: high",
      "Source type: supplier",
      "Lot reference: ING-052126 (ingredient lot)",
    ],
    signals: "Output: RecallSpec JSON + extraction trace suitable for audit review.",
  },
  {
    title: "Trace → build exposure paths in the graph",
    tier: "trace_computed",
    asOf: "2026-05-09T00:00:00Z",
    body:
      "Trace traverses suppliers, lots, and transformations to find where the recalled input could have propagated, then narrows exposure windows by facility and shipment evidence.",
    facts: [
      "Propagation: ingredient → finished products (SKU set)",
      "Affected stores: derived from shipments",
      "Evidence: lots + facility + shipment chain",
    ],
    signals: "Output: supply-chain subgraph + affected lots + store/time windows.",
  },
  {
    title: "Match → score impacted transactions",
    tier: "transactions_scored",
    asOf: "2026-05-09T00:00:00Z",
    body:
      "Match joins trace evidence to sales events. Each transaction gets an affected probability and a confidence tier so comms and operations can be calibrated.",
    facts: [
      "Tiered outputs: confirmed / likely / possible",
      "Safe tiers: likely_unaffected / confirmed_unaffected",
      "Walkthrough uses anonymized examples",
    ],
    signals: "Output: ranked impacted transaction set + confidence tiers.",
  },
  {
    title: "Ops → generate store tasks",
    tier: "ops_tasks_created",
    asOf: "2026-05-09T00:00:00Z",
    body:
      "Ops generates operational tasks: pulls, quarantine, POS blocks, signage, and escalation routing. Tasks are grouped by store and prioritized.",
    facts: ["Per-store task list", "Priority + status tracking", "Demo mode: no external systems updated"],
    signals: "Output: store task queue + compliance log entries.",
  },
  {
    title: "Comms → draft notifications and reassurance",
    tier: "drafts_created",
    asOf: "2026-05-09T00:00:00Z",
    body:
      "Comms drafts customer-safe messaging. Affected customers get clear next steps; safe customers get reassurance backed by provenance evidence and an as-of timestamp.",
    facts: ["Affected: concise call-to-action language", "Safe: provenance evidence + time-bound messaging", "Drafts only in demo mode"],
    signals: "Output: message drafts by tier + channel plan placeholders.",
  },
  {
    title: "Human-in-loop → manager approval + audit trail",
    tier: "awaiting_manager_approval",
    asOf: "2026-05-09T00:00:00Z",
    body:
      "High-stakes actions pause for manager approval. The system records approvals and agent transitions in an append-only compliance event log.",
    facts: ["Durable state + crash recovery", "Incremental reruns on scope change", "Audit-ready event timeline"],
    signals: "Output: approvals + compliance events; downstream actions gated on human review.",
  },
];

function byId(id) {
  const el = document.getElementById(id);
  if (!el) throw new Error(`Missing element: ${id}`);
  return el;
}

function setLink(id, href, label) {
  const el = document.getElementById(id);
  if (!el) return;
  el.setAttribute("href", href);
  if (label) el.textContent = label;
}

setLink("githubLink", LINKS.github, LINKS.github.replace(/^https?:\/\//, ""));
setLink("githubLinkTop", LINKS.github, "GitHub");
setLink("demoLink", LINKS.demo, "View Demo");
setLink("demoLink2", LINKS.demo, "View Demo");
setLink("demoLink3", LINKS.demo, LINKS.demo.replace(/^https?:\/\//, ""));
setLink("hfLink", LINKS.hf, "Hugging Face");
setLink("xLink", LINKS.x, LINKS.x.replace(/^https?:\/\//, ""));
setLink("contactLink", LINKS.contact, LINKS.contact.replace(/^mailto:/, ""));

const progressBar = byId("progressBar");
const stepPill = byId("stepPill");
const tierPill = byId("tierPill");
const asOfPill = byId("asOfPill");
const stepTitle = byId("stepTitle");
const stepBody = byId("stepBody");
const factsList = byId("factsList");
const signalsBox = byId("signalsBox");
const prevBtn = byId("prevBtn");
const nextBtn = byId("nextBtn");

let idx = 0;

function render() {
  const step = steps[idx];
  stepPill.textContent = `Step ${idx + 1} / ${steps.length}`;
  tierPill.textContent = `State: ${step.tier}`;
  asOfPill.textContent = `As of: ${step.asOf}`;
  stepTitle.textContent = step.title;
  stepBody.textContent = step.body;

  factsList.innerHTML = "";
  for (const f of step.facts) {
    const li = document.createElement("li");
    li.textContent = f;
    factsList.appendChild(li);
  }

  signalsBox.textContent = step.signals;

  const pct = Math.round(((idx + 1) / steps.length) * 100);
  progressBar.style.width = `${pct}%`;

  prevBtn.disabled = idx === 0;
  nextBtn.textContent = idx === steps.length - 1 ? "Restart" : "Next";
}

prevBtn.addEventListener("click", () => {
  idx = Math.max(0, idx - 1);
  render();
});
nextBtn.addEventListener("click", () => {
  if (idx === steps.length - 1) idx = 0;
  else idx += 1;
  render();
});

render();
