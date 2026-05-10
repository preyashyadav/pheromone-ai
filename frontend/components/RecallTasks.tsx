"use client";

import { useQuery } from "@tanstack/react-query";
import React from "react";
import { api, TaskRow } from "../lib/api";

export function RecallTasks({ recallCaseId }: { recallCaseId: string }) {
  const tasks = useQuery({
    queryKey: ["tasks", recallCaseId],
    queryFn: () => api.getTasks(recallCaseId),
    refetchInterval: 5_000
  });

  const grouped = React.useMemo(() => {
    const out = new Map<string, TaskRow[]>();
    for (const t of tasks.data?.tasks ?? []) {
      const storeId = typeof t.payload["store_id"] === "string" ? (t.payload["store_id"] as string) : "unknown";
      out.set(storeId, [...(out.get(storeId) ?? []), t]);
    }
    return Array.from(out.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [tasks.data?.tasks]);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="text-sm font-semibold">Store Tasks</div>
      <div className="mt-1 text-xs text-slate-400">
        Per-store task lists (floor pulls, quarantine, POS blocks). Demo mode: no real sending.
      </div>

      <div className="mt-4 grid gap-3">
        {grouped.map(([storeId, rows]) => (
          <div key={storeId} className="rounded-xl border border-slate-800 bg-slate-950 p-3">
            <div className="flex items-center justify-between">
              <div className="text-xs font-medium text-slate-100">Store {storeId.slice(0, 8)}</div>
              <div className="text-xs text-slate-400">{rows.length} tasks</div>
            </div>
            <div className="mt-3 grid gap-2">
              {rows.slice(0, 12).map((t) => (
                <TaskCard key={t.id} row={t} />
              ))}
              {rows.length > 12 ? <div className="text-xs text-slate-500">+ {rows.length - 12} more…</div> : null}
            </div>
          </div>
        ))}
      </div>

      {tasks.isLoading ? <div className="mt-3 text-xs text-slate-400">Loading tasks…</div> : null}
      {tasks.isError ? <div className="mt-3 text-xs text-rose-300">Failed to load tasks.</div> : null}
    </div>
  );
}

function TaskCard({ row }: { row: TaskRow }) {
  const title = typeof row.payload["title"] === "string" ? (row.payload["title"] as string) : row.task_type;
  const desc = typeof row.payload["description"] === "string" ? (row.payload["description"] as string) : "";
  const priority = typeof row.payload["priority"] === "string" ? (row.payload["priority"] as string) : "normal";
  const status = row.status;
  const badge =
    status === "done"
      ? "border-emerald-800 bg-emerald-950 text-emerald-100"
      : "border-slate-700 bg-slate-950 text-slate-200";
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-medium text-slate-100">{title}</div>
        <div className="flex items-center gap-2">
          <span className={`rounded-full border px-2 py-0.5 text-[10px] ${badge}`}>{status}</span>
          <span className="text-[10px] text-slate-500">{priority}</span>
        </div>
      </div>
      {desc ? <div className="mt-2 text-xs text-slate-200">{desc}</div> : null}
    </div>
  );
}
