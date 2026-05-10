"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import React from "react";
import { api } from "../../../../lib/api";
import { BlastRadiusGraph } from "../../../../components/BlastRadiusGraph";
import { ConfidenceTable } from "../../../../components/ConfidenceTable";
import { NotificationDrafts } from "../../../../components/NotificationDrafts";
import { RecallTasks } from "../../../../components/RecallTasks";
import { ComplianceTimeline } from "../../../../components/ComplianceTimeline";
import { ReassurancePanel } from "../../../../components/ReassurancePanel";
import { useRecallStream } from "../../../../components/useRecallStream";

type TabKey =
  | "overview"
  | "blast"
  | "transactions"
  | "tasks"
  | "notifications"
  | "compliance"
  | "reassurance";

const tabs: Array<{ k: TabKey; label: string }> = [
  { k: "overview", label: "Overview" },
  { k: "blast", label: "Blast Radius" },
  { k: "transactions", label: "Affected Transactions" },
  { k: "tasks", label: "Store Tasks" },
  { k: "notifications", label: "Notifications" },
  { k: "compliance", label: "Compliance" },
  { k: "reassurance", label: "Reassurance" }
];

export default function RecallDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const qc = useQueryClient();

  useRecallStream(id, () => {
    void qc.invalidateQueries({ queryKey: ["recallOverview", id] });
    void qc.invalidateQueries({ queryKey: ["blastRadius", id] });
    void qc.invalidateQueries({ queryKey: ["transactions", id] });
    void qc.invalidateQueries({ queryKey: ["tasks", id] });
    void qc.invalidateQueries({ queryKey: ["drafts", id] });
    void qc.invalidateQueries({ queryKey: ["compliance", id] });
    void qc.invalidateQueries({ queryKey: ["agentsTelemetry"] });
    void qc.invalidateQueries({ queryKey: ["gpuTelemetry"] });
  });

  const overview = useQuery({
    queryKey: ["recallOverview", id],
    queryFn: () => api.getRecallOverview(id),
    refetchInterval: 5_000
  });

  const [tab, setTab] = React.useState<TabKey>("overview");

  return (
    <div>
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="text-xs text-slate-400">
            <Link href="/recalls" className="hover:text-slate-200">
              Recalls
            </Link>{" "}
            / <span className="text-slate-200">{id.slice(0, 8)}</span>
          </div>
          <h1 className="mt-1 text-xl font-semibold tracking-tight">
            {recallTitle(overview.data?.recall_spec) ?? "Recall Case"}
          </h1>
          <div className="mt-1 text-sm text-slate-400">
            State: <span className="text-slate-200">{overview.data?.state ?? "…"}</span>
          </div>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        {tabs.map((t) => (
          <button
            key={t.k}
            type="button"
            onClick={() => setTab(t.k)}
            className={
              tab === t.k
                ? "rounded-full border border-slate-700 bg-slate-900 px-3 py-1 text-xs text-slate-100"
                : "rounded-full border border-slate-800 bg-slate-950 px-3 py-1 text-xs text-slate-300 hover:border-slate-700"
            }
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {tab === "overview" ? <OverviewPanel id={id} /> : null}
        {tab === "blast" ? <BlastRadiusGraph recallCaseId={id} /> : null}
        {tab === "transactions" ? <ConfidenceTable recallCaseId={id} /> : null}
        {tab === "tasks" ? <RecallTasks recallCaseId={id} /> : null}
        {tab === "notifications" ? <NotificationDrafts recallCaseId={id} /> : null}
        {tab === "compliance" ? <ComplianceTimeline recallCaseId={id} /> : null}
        {tab === "reassurance" ? <ReassurancePanel recallCaseId={id} /> : null}
      </div>
    </div>
  );
}

function OverviewPanel({ id }: { id: string }) {
  const overview = useQuery({ queryKey: ["recallOverview", id], queryFn: () => api.getRecallOverview(id) });
  const spec = overview.data?.recall_spec ?? null;

  return (
    <div className="grid gap-4">
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
        <div className="text-sm font-semibold">RecallSpec</div>
        <div className="mt-2 text-xs text-slate-400">
          Parsed fields (LLM + deterministic merge). Structured output is the contract.
        </div>
        <pre className="mt-3 max-h-[420px] overflow-auto rounded-lg border border-slate-800 bg-slate-950 p-3 text-xs text-slate-200">
          {spec ? JSON.stringify(spec, null, 2) : "No RecallSpec saved yet."}
        </pre>
      </div>
    </div>
  );
}

function recallTitle(spec: Record<string, unknown> | null | undefined): string | null {
  if (!spec) return null;
  const v = spec["recall_id"];
  return typeof v === "string" && v ? v : null;
}
