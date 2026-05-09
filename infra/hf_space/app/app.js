const steps = [
  {
    title: "Intake → parse the recall notice",
    tier: "signal_detected",
    asOf: "2026-05-09T00:00:00Z",
    body:
      "A supplier notice reports a Salmonella risk tied to an ingredient used in Salsa Verde. Intake extracts hazards, severity, and any lot references — and admits uncertainty when fields are missing.",
    facts: [
      "Hazard: Salmonella",
      "Severity: high",
      "Signal source: supplier notice",
      "Lot reference: ING-052126 (ingredient lot)",
    ],
    signals:
      "Pheromone lays a trail from the notice back into the supply chain graph — without assuming perfect lot capture at checkout.",
  },
  {
    title: "Trace → compute the ingredient-level blast radius",
    tier: "blast_radius_computed",
    asOf: "2026-05-09T00:00:00Z",
    body:
      "Trace walks recipes and transformations to find every finished product that could contain the recalled ingredient, then identifies which stores received affected pallets.",
    facts: [
      "Recalled ingredient propagates into: Salsa Verde 16oz + related SKUs",
      "Affected stores: 6",
      "Facilities implicated: Plant P2 (affected set)",
    ],
    signals:
      "Instead of a broadcast panic alert, the colony gets precise signals: which products, which stores, which windows.",
  },
  {
    title: "Match → score each transaction probabilistically",
    tier: "transactions_scored",
    asOf: "2026-05-09T00:00:00Z",
    body:
      "Match replays stocking + sales events to estimate which pallet a unit came from. Each transaction gets an affected probability and a confidence tier.",
    facts: [
      "Confirmed affected: 451",
      "Likely affected: 1,389",
      "Possible affected: 680",
      "Confirmed unaffected (reassurance): 780",
      "Likely unaffected (soft reassurance): 300",
    ],
    signals:
      "This is the differentiator: notifying the safe with proof prevents panic refunds and protects trust.",
  },
  {
    title: "Comms → draft selective notifications (affected tiers)",
    tier: "drafts_created",
    asOf: "2026-05-09T00:00:00Z",
    body:
      "Affected customers receive urgent, action-oriented instructions: don’t consume, discard/return, and guidance for vulnerable households — without leaking PII.",
    facts: [
      "Confirmed/Likely affected: urgent, max 4 sentences",
      "Possible affected: gentle, 'may include' phrasing + lot-check instructions",
      "Never send in demo mode — drafts only",
    ],
    signals:
      "Signals are tiered: the more certain the risk, the more direct the call to action — while keeping language calibrated.",
  },
  {
    title: "Comms → reassurance notifications (the killer feature)",
    tier: "reassurance_drafted",
    asOf: "2026-05-09T00:00:00Z",
    body:
      "Unaffected customers get a reassurance note that’s time-bound and evidence-based. It names the provenance proof (e.g., plant-of-origin inference) and promises follow-up if scope changes.",
    facts: [
      "Time-bound: 'as of <timestamp>'",
      "Concrete proof: plant-of-origin inference not in affected set",
      "Never claim 'guaranteed safe' — calibrated language only",
    ],
    signals:
      "Selective signaling: reassure the safe with proof, while staying honest about uncertainty and scope changes.",
  },
  {
    title: "Human-in-loop → manager approval before action",
    tier: "manager_approval",
    asOf: "2026-05-09T00:00:00Z",
    body:
      "Before any operational steps or outbound comms, the workflow pauses for a manager to approve the batch. If the recall scope expands, the system re-runs only what’s needed.",
    facts: [
      "Durable state + crash recovery",
      "Scope-change reruns are incremental",
      "Compliance-ready audit trail",
    ],
    signals:
      "The colony stays safe by pausing at the right decision points — humans confirm the highest-stakes actions.",
  },
];

function byId(id) {
  const el = document.getElementById(id);
  if (!el) throw new Error(`Missing element: ${id}`);
  return el;
}

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

