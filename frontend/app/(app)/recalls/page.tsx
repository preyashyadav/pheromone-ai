"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import React from "react";
import { api } from "../../../lib/api";

function severityColor(sev: string | null) {
  const s = (sev ?? "").toLowerCase();
  if (s === "high") return "bg-slate-950 text-rose-200 border-rose-700";
  if (s === "medium") return "bg-slate-950 text-amber-200 border-amber-700";
  if (s === "low") return "bg-slate-950 text-emerald-200 border-emerald-700";
  return "bg-slate-950 text-slate-200 border-slate-700";
}

export default function RecallsPage() {
  const router = useRouter();
  const feed = useQuery({ queryKey: ["recallsFeed"], queryFn: api.listRecalls, refetchInterval: 5_000 });

  React.useEffect(() => {
    const rows = feed.data?.recalls ?? [];
    if (rows.length === 1) {
      router.replace(`/recall/${rows[0].recall_case_id}`);
    }
  }, [feed.data?.recalls, router]);

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Recall Feed</h1>
          <p className="mt-1 text-sm text-slate-400">
            Recency-first view. Open a case to see trace evidence, impacted transactions, and customer-safe workflows.
          </p>
        </div>
      </div>

      <div className="mt-6 grid gap-3">
        {(feed.data?.recalls ?? []).map((r) => (
          <Link
            key={r.recall_case_id}
            href={`/recall/${r.recall_case_id}`}
            className="group rounded-xl border border-slate-800 bg-slate-900 p-4 hover:border-slate-700"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="text-sm font-semibold text-slate-100 group-hover:text-white">
                  {r.recall_id ?? r.recall_case_id.slice(0, 8)}
                </div>
                <span className={`rounded-full border px-2 py-0.5 text-xs ${severityColor(r.severity)}`}>
                  {r.severity ?? "unknown"}
                </span>
                <span className="rounded-full border border-slate-700 bg-slate-950 px-2 py-0.5 text-xs text-slate-200">
                  {r.state}
                </span>
              </div>
              <div className="text-xs text-slate-400">{new Date(r.updated_at_utc).toLocaleString()}</div>
            </div>
            <div className="mt-2 text-sm text-slate-300">
              Hazard: <span className="text-slate-100">{r.hazard_type ?? "unknown"}</span> · Source:{" "}
              <span className="text-slate-100">{r.source_type ?? "unknown"}</span>
            </div>
          </Link>
        ))}

        {feed.isLoading ? <div className="text-sm text-slate-400">Loading recalls…</div> : null}

        {feed.data && feed.data.recalls.length === 0 ? (
          <div className="rounded-xl border border-slate-800 bg-slate-900 p-4 text-sm text-slate-300">
            <div className="font-medium text-slate-100">No recall cases yet</div>
            <div className="mt-1 text-slate-400">
              Seed the demo recall, then refresh:{" "}
              <code className="rounded bg-slate-950 px-1.5 py-0.5 text-xs text-slate-200">
                ./.venv/bin/python scripts/seed_demo_recall.py --reset
              </code>
            </div>
          </div>
        ) : null}

        {feed.isError ? (
          <div className="text-sm text-rose-300">
            Failed to load the recall feed. Check `NEXT_PUBLIC_API_BASE_URL` and backend `/api/recalls`.
          </div>
        ) : null}
      </div>
    </div>
  );
}
