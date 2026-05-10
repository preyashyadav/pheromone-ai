"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

export function ComplianceTimeline({ recallCaseId }: { recallCaseId: string }) {
  const log = useQuery({
    queryKey: ["compliance", recallCaseId],
    queryFn: () => api.getCompliance(recallCaseId),
    refetchInterval: 5_000
  });

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="text-sm font-semibold">Compliance Event Log</div>
      <div className="mt-1 text-xs text-slate-400">
        Append-only timeline: agent runs, approvals, and key state transitions.
      </div>

      <div className="mt-4 grid gap-2">
        {(log.data?.events ?? []).slice().reverse().map((e, idx) => (
          <div key={`${e.created_at_utc}:${idx}`} className="rounded-lg border border-slate-800 bg-slate-950 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-xs font-medium text-slate-100">{e.event_type}</div>
              <div className="text-[10px] text-slate-500">{new Date(e.created_at_utc).toLocaleString()}</div>
            </div>
            <div className="mt-1 text-xs text-slate-200">{e.message}</div>
          </div>
        ))}
      </div>

      {log.isLoading ? <div className="mt-3 text-xs text-slate-400">Loading compliance log…</div> : null}
      {log.isError ? <div className="mt-3 text-xs text-rose-300">Failed to load compliance log.</div> : null}
    </div>
  );
}
