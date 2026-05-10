"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import React from "react";
import { api } from "../lib/api";

export function ReassurancePanel({ recallCaseId }: { recallCaseId: string }) {
  const qc = useQueryClient();
  const tx = useQuery({
    queryKey: ["transactions", recallCaseId],
    queryFn: () => api.getTransactions(recallCaseId),
    refetchInterval: 5_000
  });

  const reassurance = React.useMemo(() => {
    const rows = tx.data?.transactions ?? [];
    return rows.filter((r) => r.confidence_tier === "likely_unaffected" || r.confidence_tier === "confirmed_unaffected");
  }, [tx.data?.transactions]);

  const [enabled, setEnabled] = React.useState(false);
  const approve = useMutation({
    mutationFn: () => api.createApproval(recallCaseId, { approved_by: "manager@example.com", action: "approve_reassurance_batch" }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["compliance", recallCaseId] });
    }
  });

  return (
    <div className="rounded-xl border border-emerald-900 bg-slate-900 p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="text-sm font-semibold text-emerald-100">Reassurance Batch</div>
          <div className="mt-1 text-xs text-slate-300">
            Safe-path messaging: prove non-exposure using supply-chain provenance evidence.
          </div>
        </div>
        <label className="flex items-center gap-2 text-xs text-emerald-100">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="h-4 w-4 accent-emerald-500"
          />
          Send reassurance batch?
        </label>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs text-slate-300">
          Eligible transactions: <span className="text-emerald-100">{reassurance.length.toLocaleString()}</span>
        </div>
        <button
          type="button"
          onClick={() => approve.mutate()}
          disabled={!enabled || approve.isPending}
          className="rounded-md border border-emerald-800 bg-slate-950 px-3 py-1 text-xs font-medium text-emerald-100 hover:border-emerald-700 disabled:opacity-50"
        >
          Approve reassurance batch
        </button>
      </div>

      <div className="mt-4 overflow-auto rounded-lg border border-emerald-900 bg-slate-950">
        <table className="w-full min-w-[680px] text-left text-xs">
          <thead className="bg-slate-950 text-emerald-100/90">
            <tr>
              <th className="px-3 py-2 font-medium">Tier</th>
              <th className="px-3 py-2 font-medium">Customer</th>
              <th className="px-3 py-2 font-medium">Email</th>
              <th className="px-3 py-2 font-medium">Timestamp</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-emerald-950">
            {reassurance.slice(0, 50).map((r) => (
              <tr key={r.transaction_id} className="hover:bg-slate-900">
                <td className="px-3 py-2 text-emerald-100">{r.confidence_tier}</td>
                <td className="px-3 py-2 text-emerald-100">{r.customer_initials ?? "—"}</td>
                <td className="px-3 py-2 text-emerald-100">{r.email_masked ?? "—"}</td>
                <td className="px-3 py-2 text-slate-300">{new Date(r.timestamp_utc).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {tx.isLoading ? <div className="mt-3 text-xs text-slate-300">Loading…</div> : null}
      {tx.isError ? <div className="mt-3 text-xs text-rose-300">Failed to load transactions.</div> : null}
    </div>
  );
}
