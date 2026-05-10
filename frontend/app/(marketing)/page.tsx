import Link from "next/link";

const GITHUB_URL = "https://github.com/<org>/pheromone";
const HF_SPACE_URL = "https://huggingface.co/spaces/<org>/pheromone";

export default function MarketingLandingPage() {
  return (
    <div className="min-h-screen bg-slate-950">
      <header className="border-b border-slate-800">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4 sm:px-6 lg:px-10">
          <div className="flex items-center gap-4">
            <div className="text-sm font-semibold tracking-tight">Pheromone</div>
            <div className="hidden text-xs text-slate-400 md:block">
              Recall operations for food retail and supply-chain teams.
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/recalls"
              className="rounded-md bg-slate-50 px-3 py-2 text-sm font-medium text-slate-950 hover:bg-white"
            >
              View Demo
            </Link>
            <a
              href={HF_SPACE_URL}
              target="_blank"
              rel="noreferrer"
              className="rounded-md border border-slate-700 px-3 py-2 text-sm font-medium text-slate-100 hover:border-slate-500"
            >
              Hugging Face
            </a>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="hidden rounded-md border border-slate-700 px-3 py-2 text-sm font-medium text-slate-100 hover:border-slate-500 sm:inline-flex"
            >
              GitHub
            </a>
          </div>
        </div>
      </header>

      <main>
        <Section>
          <div className="grid gap-8 lg:grid-cols-12 lg:items-start">
            <div className="lg:col-span-7">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-400">
                AI Recall Operating System
              </div>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-50 sm:text-4xl">
                Trace recalls. Notify the affected. Reassure the safe.
              </h1>
              <p className="mt-4 max-w-2xl text-base leading-relaxed text-slate-300">
                Pheromone ingests recall notices, traces affected products through the supply chain, matches likely
                impacted transactions, and generates audit-ready workflows for customer communication and store
                operations.
              </p>

              <div className="mt-6 flex flex-wrap gap-3">
                <Link
                  href="/recalls"
                  className="rounded-md bg-slate-50 px-4 py-2.5 text-sm font-medium text-slate-950 hover:bg-white"
                >
                  View Demo
                </Link>
                <a
                  href={GITHUB_URL}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-md border border-slate-700 px-4 py-2.5 text-sm font-medium text-slate-100 hover:border-slate-500"
                >
                  GitHub
                </a>
              </div>

              <div className="mt-8 grid gap-3 sm:grid-cols-3">
                <Kpi label="Workflow" value="Intake → Trace → Match → Comms" />
                <Kpi label="Agents" value="5 coordinated agents" />
                <Kpi label="Output" value="Audit-ready reporting" />
              </div>
            </div>

            <div className="lg:col-span-5">
              <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
                <div className="text-sm font-semibold text-slate-100">Example Snapshot (demo)</div>
                <div className="mt-1 text-xs text-slate-400">
                  What a recall team needs to answer in minutes, not days.
                </div>

                <div className="mt-4 grid gap-3 text-sm">
                  <PanelRow
                    k="Affected SKUs"
                    v={<span className="rounded-full border border-amber-700 bg-slate-950 px-2 py-0.5 text-xs">2</span>}
                  />
                  <PanelRow
                    k="Likely impacted transactions"
                    v={<span className="rounded-full border border-rose-700 bg-slate-950 px-2 py-0.5 text-xs">41</span>}
                  />
                  <PanelRow
                    k="Safe transactions"
                    v={
                      <span className="rounded-full border border-emerald-700 bg-slate-950 px-2 py-0.5 text-xs">
                        318
                      </span>
                    }
                  />
                  <PanelRow k="Next action" v="Generate customer messaging + store tasks" />
                </div>
              </div>
            </div>
          </div>
        </Section>

        <Section>
          <div className="grid gap-4 lg:grid-cols-12 lg:items-start">
            <div className="lg:col-span-4">
              <h2 className="text-lg font-semibold tracking-tight">The operational problem</h2>
              <p className="mt-2 text-sm leading-relaxed text-slate-300">
                Recalls happen. Purchase-level notification is often inconsistent, and customers are left guessing.
              </p>
            </div>
            <div className="grid gap-3 lg:col-span-8 sm:grid-cols-2">
              <Card title="Unclear exposure">
                Customers often don’t know if they bought the recalled item—brand and SKU data don’t match receipts.
              </Card>
              <Card title="Unnecessary panic">
                Unaffected customers discard safe food, creating waste and avoidable support volume.
              </Card>
              <Card title="Refund and call-center load">
                Stores face broad refunds and high-touch escalations when exposure can’t be confirmed.
              </Card>
              <Card title="Audit pressure">
                Teams need a defensible record of what was traced, who was notified, and why.
              </Card>
            </div>
          </div>
        </Section>

        <Section>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold tracking-tight">Workflow</h2>
              <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-300">
                A coordinated recall runbook from intake to customer communication, driven by a supply-chain graph and
                transaction matching.
              </p>
            </div>
            <Link href="/recalls" className="text-sm font-medium text-slate-200 hover:text-white">
              Open demo →
            </Link>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-6">
            <Step n="1" title="Intake notice" body="Parse recall notice into a structured RecallSpec contract." />
            <Step n="2" title="Trace graph" body="Walk suppliers, lots, and shipments to determine exposure paths." />
            <Step n="3" title="Match transactions" body="Identify likely impacted purchases and confidence." />
            <Step n="4" title="Risk tier" body="Classify customers as affected, safe, or unknown with evidence." />
            <Step n="5" title="Notify" body="Generate customer-safe templates and outreach tasks." />
            <Step n="6" title="Compliance report" body="Produce audit-ready timelines and trace artifacts." />
          </div>
        </Section>

        <Section>
          <h2 className="text-lg font-semibold tracking-tight">Agents</h2>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-300">
            Five agents with clear contracts. No “AI magic”—each agent takes a typed input, performs a bounded job, and
            emits an output used by downstream workflow.
          </p>

          <div className="mt-5 grid gap-3">
            <AgentRow
              name="Intake Agent"
              input="Recall notice text"
              responsibility="Extract fields and normalize into RecallSpec (hazard, scope, dates, products)."
              output="RecallSpec JSON + parsing trace"
            />
            <AgentRow
              name="Trace Agent"
              input="RecallSpec + supply-chain entities"
              responsibility="Traverse lots/shipments and build exposure paths in the graph."
              output="Supply-chain subgraph + affected lots"
            />
            <AgentRow
              name="Match Agent"
              input="Affected lots + transactions"
              responsibility="Join graph evidence to purchases and compute confidence."
              output="Ranked impacted transactions"
            />
            <AgentRow
              name="Ops Agent"
              input="Impact set + store context"
              responsibility="Generate operational tasks: pulls, signage, escalation queue, refunds policy prompts."
              output="Task list + priority"
            />
            <AgentRow
              name="Comms Agent"
              input="Risk tier + evidence"
              responsibility="Draft customer-safe notifications with provenance evidence and escalation paths."
              output="Message drafts + channel plan"
            />
          </div>
        </Section>

        <Section>
          <div className="grid gap-4 lg:grid-cols-12 lg:items-start">
            <div className="lg:col-span-4">
              <h2 className="text-lg font-semibold tracking-tight">Reassurance is the differentiator</h2>
              <p className="mt-2 text-sm leading-relaxed text-slate-300">
                Most recall systems only notify affected customers. Pheromone also reassures customers who are not
                affected, using provenance evidence from the supply-chain graph.
              </p>
            </div>
            <div className="grid gap-3 lg:col-span-8 sm:grid-cols-2">
              <OutcomeCard
                tone="affected"
                title="Affected"
                subtitle="Your purchase may be impacted."
                body="We traced your purchase to an exposure path (lot + shipment evidence). Next steps and support are included."
                points={[
                  "Clear risk tier",
                  "Evidence-backed reasoning",
                  "Actionable next steps"
                ]}
              />
              <OutcomeCard
                tone="safe"
                title="Safe"
                subtitle="Your purchase was traced to a clean batch."
                body="We can prove your purchase did not intersect the recall scope, reducing panic and unnecessary refunds."
                points={[
                  "Provenance proof",
                  "Lower call-center volume",
                  "Trust-preserving messaging"
                ]}
              />
            </div>
          </div>
        </Section>

        <Section>
          <div className="grid gap-4 lg:grid-cols-12 lg:items-start">
            <div className="lg:col-span-4">
              <h2 className="text-lg font-semibold tracking-tight">AMD + GPU-backed inference</h2>
              <p className="mt-2 text-sm leading-relaxed text-slate-300">
                The demo architecture runs a full multi-agent stack with large-model inference so the workflow is
                realistic and end-to-end.
              </p>
            </div>
            <div className="lg:col-span-8">
              <div className="grid gap-3 sm:grid-cols-2">
                <SpecCard k="Model" v="Qwen3-32B" />
                <SpecCard k="Serving" v="vLLM" />
                <SpecCard k="Driver stack" v="ROCm 7" />
                <SpecCard k="GPU" v="AMD Instinct MI300X" />
                <SpecCard k="Memory" v="192GB HBM3" />
                <SpecCard k="Why it matters" v="Multi-agent context retention + high-throughput inference" />
              </div>
            </div>
          </div>
        </Section>

        <Section>
          <h2 className="text-lg font-semibold tracking-tight">Validation</h2>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-300">
            Demo-ready system checks focused on correctness, traceability, and operational outputs.
          </p>
          <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Fact title="Five-agent workflow live" body="End-to-end intake → trace → match → ops → comms." />
            <Fact title="Reassurance supported" body="Safe-path messaging uses graph provenance evidence." />
            <Fact title="GPU inference in loop" body="Telemetry + real model serving in the demo architecture." />
            <Fact title="Open-source" body="Repo + HF Space linkable for judges and reviewers." />
          </div>
        </Section>

        <footer className="border-t border-slate-800">
          <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-8 text-sm text-slate-400 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-10">
            <div>© {new Date().getFullYear()} Pheromone</div>
            <div className="flex flex-wrap items-center gap-3">
              <Link href="/recalls" className="text-slate-300 hover:text-white">
                Demo
              </Link>
              <a href={HF_SPACE_URL} target="_blank" rel="noreferrer" className="text-slate-300 hover:text-white">
                Hugging Face
              </a>
              <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="text-slate-300 hover:text-white">
                GitHub
              </a>
            </div>
          </div>
        </footer>
      </main>
    </div>
  );
}

function Section({ children }: { children: React.ReactNode }) {
  return (
    <section className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-10 lg:py-16">
      {children}
    </section>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="text-[11px] text-slate-400">{label}</div>
      <div className="mt-1 text-sm font-medium text-slate-100">{value}</div>
    </div>
  );
}

function PanelRow({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-slate-800 bg-slate-950 px-3 py-2">
      <div className="text-xs text-slate-400">{k}</div>
      <div className="text-xs font-medium text-slate-100">{v}</div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="text-sm font-semibold text-slate-100">{title}</div>
      <div className="mt-2 text-sm leading-relaxed text-slate-300">{children}</div>
    </div>
  );
}

function Step({ n, title, body }: { n: string; title: string; body: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="flex items-start gap-3">
        <div className="flex h-6 w-6 items-center justify-center rounded-md border border-slate-700 bg-slate-950 text-xs font-semibold text-slate-100">
          {n}
        </div>
        <div>
          <div className="text-sm font-semibold text-slate-100">{title}</div>
          <div className="mt-1 text-sm leading-relaxed text-slate-300">{body}</div>
        </div>
      </div>
    </div>
  );
}

function AgentRow({
  name,
  input,
  responsibility,
  output
}: {
  name: string;
  input: string;
  responsibility: string;
  output: string;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="text-sm font-semibold text-slate-100">{name}</div>
        <div className="text-xs text-slate-400">Contracted agent</div>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <Field label="Input" value={input} />
        <Field label="Responsibility" value={responsibility} />
        <Field label="Output" value={output} />
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950 p-3">
      <div className="text-[11px] text-slate-400">{label}</div>
      <div className="mt-1 text-sm leading-relaxed text-slate-200">{value}</div>
    </div>
  );
}

function OutcomeCard({
  tone,
  title,
  subtitle,
  body,
  points
}: {
  tone: "affected" | "safe";
  title: string;
  subtitle: string;
  body: string;
  points: string[];
}) {
  const badge =
    tone === "affected"
      ? "border-rose-700 text-rose-200"
      : "border-emerald-700 text-emerald-200";

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-semibold text-slate-100">{title}</div>
        <div className={`rounded-full border bg-slate-950 px-2 py-0.5 text-xs ${badge}`}>{subtitle}</div>
      </div>
      <div className="mt-3 text-sm leading-relaxed text-slate-300">{body}</div>
      <ul className="mt-4 grid gap-2 text-sm text-slate-200">
        {points.map((p) => (
          <li key={p} className="flex items-start gap-2">
            <span className="mt-1 inline-block h-1.5 w-1.5 rounded-full bg-slate-500" />
            <span>{p}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SpecCard({ k, v }: { k: string; v: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="text-[11px] text-slate-400">{k}</div>
      <div className="mt-1 text-sm font-medium text-slate-100">{v}</div>
    </div>
  );
}

function Fact({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="text-sm font-semibold text-slate-100">{title}</div>
      <div className="mt-2 text-sm leading-relaxed text-slate-300">{body}</div>
    </div>
  );
}
