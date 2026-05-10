"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import React from "react";
import { api, DraftRow } from "../lib/api";

const tierStyles: Record<string, { badge: string; group: string; title: string }> = {
  confirmed_affected: {
    badge: "border-rose-700 bg-rose-950 text-rose-200",
    group: "border-rose-900",
    title: "Confirmed Affected"
  },
  likely_affected: {
    badge: "border-orange-700 bg-orange-950 text-orange-200",
    group: "border-orange-900",
    title: "Likely Affected"
  },
  possible_affected: {
    badge: "border-amber-700 bg-amber-950 text-amber-200",
    group: "border-amber-900",
    title: "Possible Affected"
  },
  likely_unaffected: {
    badge: "border-emerald-700 bg-emerald-950 text-emerald-200",
    group: "border-emerald-900",
    title: "Likely Unaffected"
  },
  confirmed_unaffected: {
    badge: "border-emerald-700 bg-emerald-950 text-emerald-200",
    group: "border-emerald-900",
    title: "Confirmed Unaffected"
  }
};

export function NotificationDrafts({ recallCaseId }: { recallCaseId: string }) {
  const qc = useQueryClient();
  const drafts = useQuery({
    queryKey: ["drafts", recallCaseId],
    queryFn: () => api.getDrafts(recallCaseId),
    refetchInterval: 5_000
  });

  const [lastApproval, setLastApproval] = React.useState<{ action: string; count: number } | null>(null);
  const approve = useMutation({
    mutationFn: (action: string) => api.createApproval(recallCaseId, { approved_by: "manager@example.com", action }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["drafts", recallCaseId] });
      await qc.invalidateQueries({ queryKey: ["compliance", recallCaseId] });
    }
  });

  const grouped = React.useMemo(() => groupByTier(drafts.data?.drafts ?? []), [drafts.data?.drafts]);

  return (
    <div className="grid gap-4">
      <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-sm font-semibold">Notification Drafts</div>
            <div className="mt-1 text-xs text-slate-400">
              Drafts only in demo mode. Approvals create audit entries without sending.
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() =>
                approve.mutate("approve_confirmed_affected_batch", {
                  onSuccess: (res) =>
                    setLastApproval({ action: "approve_confirmed_affected_batch", count: res.approvals_count })
                })
              }
              className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1 text-xs text-slate-100 hover:border-slate-500 disabled:opacity-50"
              disabled={approve.isPending}
            >
              Approve all Confirmed Affected
            </button>
            <button
              type="button"
              onClick={() =>
                approve.mutate("approve_likely_affected_batch", {
                  onSuccess: (res) =>
                    setLastApproval({ action: "approve_likely_affected_batch", count: res.approvals_count })
                })
              }
              className="rounded-md border border-slate-700 bg-slate-950 px-3 py-1 text-xs text-slate-100 hover:border-slate-500 disabled:opacity-50"
              disabled={approve.isPending}
            >
              Approve all Likely Affected
            </button>
          </div>
        </div>

        <div className="mt-4 grid gap-3">
          {lastApproval ? (
            <div className="rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-200">
              Approval recorded: <span className="font-medium">{lastApproval.action}</span> (count:{" "}
              <span className="font-medium">{lastApproval.count}</span>)
            </div>
          ) : null}
          {Object.entries(grouped).map(([tier, rows]) => (
            <TierGroup key={tier} tier={tier} rows={rows} />
          ))}
        </div>

        {drafts.isLoading ? <div className="mt-3 text-xs text-slate-400">Loading drafts…</div> : null}
        {drafts.isError ? <div className="mt-3 text-xs text-rose-300">Failed to load drafts.</div> : null}
      </div>

      <div className="rounded-xl border border-emerald-900 bg-slate-900 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold text-emerald-100">Reassurance Tier (Differentiator)</div>
            <div className="mt-1 text-xs text-slate-300">
              Approvals create audit entries for safe-path reassurance messaging without sending.
            </div>
          </div>
          <button
            type="button"
            onClick={() =>
              approve.mutate("approve_reassurance_batch", {
                onSuccess: (res) => setLastApproval({ action: "approve_reassurance_batch", count: res.approvals_count })
              })
            }
            className="rounded-md border border-emerald-800 bg-slate-950 px-3 py-1 text-xs font-medium text-emerald-100 hover:border-emerald-700 disabled:opacity-50"
            disabled={approve.isPending}
          >
            Approve reassurance batch
          </button>
        </div>
      </div>
    </div>
  );
}

function groupByTier(rows: DraftRow[]) {
  const out: Record<string, DraftRow[]> = {};
  for (const r of rows) {
    const t = r.confidence_tier || "unknown";
    out[t] = out[t] ? [...out[t], r] : [r];
  }
  const ordered = Object.entries(out).sort((a, b) => a[0].localeCompare(b[0]));
  return Object.fromEntries(ordered);
}

function TierGroup({ tier, rows }: { tier: string; rows: DraftRow[] }) {
  const s = tierStyles[tier] ?? {
    badge: "border-slate-700 bg-slate-950 text-slate-200",
    group: "border-slate-800",
    title: tier
  };
  return (
    <div className={`rounded-xl border ${s.group} bg-slate-950 p-3`}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className={`rounded-full border px-2 py-0.5 text-xs ${s.badge}`}>{s.title}</span>
          <span className="text-xs text-slate-400">{rows.length} drafts</span>
        </div>
      </div>
      <div className="mt-3 grid gap-2">
        {rows.slice(0, 6).map((r) => (
          <DraftCard key={r.id} row={r} />
        ))}
        {rows.length > 6 ? <div className="text-xs text-slate-500">+ {rows.length - 6} more…</div> : null}
      </div>
    </div>
  );
}

function DraftCard({ row }: { row: DraftRow }) {
  const d = row.draft as Record<string, unknown>;
  const subject = typeof d["subject"] === "string" ? (d["subject"] as string) : "";
  const body = typeof d["body"] === "string" ? (d["body"] as string) : JSON.stringify(row.draft);
  const language = typeof d["language"] === "string" ? (d["language"] as string) : "en";
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs text-slate-400">
          {row.channel} · {language}
        </div>
        <div className="text-[10px] text-slate-500">{new Date(row.created_at_utc).toLocaleString()}</div>
      </div>
      {subject ? <div className="mt-1 text-sm font-medium text-slate-100">{subject}</div> : null}
      <div className="mt-2 whitespace-pre-wrap text-xs text-slate-200">{body}</div>
    </div>
  );
}
