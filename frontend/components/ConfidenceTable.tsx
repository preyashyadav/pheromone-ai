"use client";

import { useQuery } from "@tanstack/react-query";
import React from "react";
import { api, TransactionRow } from "../lib/api";

const tierOrder: Record<string, number> = {
  confirmed_affected: 0,
  likely_affected: 1,
  possible_affected: 2,
  likely_unaffected: 3,
  confirmed_unaffected: 4,
  no_action: 5
};

function tierBadge(tier: string) {
  switch (tier) {
    case "confirmed_affected":
      return "border-rose-700 bg-rose-950 text-rose-200";
    case "likely_affected":
      return "border-orange-700 bg-orange-950 text-orange-200";
    case "possible_affected":
      return "border-amber-700 bg-amber-950 text-amber-200";
    case "likely_unaffected":
      return "border-emerald-700 bg-emerald-950 text-emerald-200";
    case "confirmed_unaffected":
      return "border-emerald-700 bg-emerald-950 text-emerald-200";
    case "no_action":
    default:
      return "border-slate-700 bg-slate-950 text-slate-200";
  }
}

export function ConfidenceTable({ recallCaseId }: { recallCaseId: string }) {
  const tx = useQuery({
    queryKey: ["transactions", recallCaseId],
    queryFn: () => api.getTransactions(recallCaseId),
    refetchInterval: 5_000
  });

  const [filter, setFilter] = React.useState<string>("all");
  const [sort, setSort] = React.useState<"tier" | "prob">("tier");

  const rows = React.useMemo(() => {
    const all = tx.data?.transactions ?? [];
    const filtered = filter === "all" ? all : all.filter((r) => r.confidence_tier === filter);
    const sorted = [...filtered].sort((a, b) => {
      if (sort === "prob") return (b.affected_probability ?? 0) - (a.affected_probability ?? 0);
      return (tierOrder[a.confidence_tier] ?? 999) - (tierOrder[b.confidence_tier] ?? 999);
    });
    return sorted;
  }, [tx.data?.transactions, filter, sort]);

  const tiers = React.useMemo(() => {
    const set = new Set<string>();
    for (const r of tx.data?.transactions ?? []) set.add(r.confidence_tier);
    return Array.from(set).sort((a, b) => (tierOrder[a] ?? 999) - (tierOrder[b] ?? 999));
  }, [tx.data?.transactions]);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">Affected Transactions</div>
          <div className="mt-1 text-xs text-slate-400">
            PII-redacted view: customer initials + masked email domain only.
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="rounded-md border border-slate-800 bg-slate-950 px-2 py-1 text-slate-100"
          >
            <option value="all">All tiers</option>
            {tiers.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as any)}
            className="rounded-md border border-slate-800 bg-slate-950 px-2 py-1 text-slate-100"
          >
            <option value="tier">Sort: tier</option>
            <option value="prob">Sort: probability</option>
          </select>
        </div>
      </div>

      <div className="mt-4 overflow-auto rounded-lg border border-slate-800">
        <table className="w-full min-w-[820px] text-left text-xs">
          <thead className="bg-slate-950 text-slate-300">
            <tr>
              <th className="px-3 py-2 font-medium">Tier</th>
              <th className="px-3 py-2 font-medium">Affected prob</th>
              <th className="px-3 py-2 font-medium">Customer</th>
              <th className="px-3 py-2 font-medium">Email</th>
              <th className="px-3 py-2 font-medium">Timestamp</th>
              <th className="px-3 py-2 font-medium">Transaction</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {rows.map((r) => (
              <Row key={r.transaction_id} row={r} />
            ))}
          </tbody>
        </table>
      </div>

      {tx.isLoading ? <div className="mt-3 text-xs text-slate-400">Loading transactions…</div> : null}
      {tx.isError ? <div className="mt-3 text-xs text-rose-300">Failed to load transactions.</div> : null}
    </div>
  );
}

function Row({ row }: { row: TransactionRow }) {
  return (
    <tr className="hover:bg-slate-950">
      <td className="px-3 py-2">
        <span className={`rounded-full border px-2 py-0.5 ${tierBadge(row.confidence_tier)}`}>
          {row.confidence_tier}
        </span>
      </td>
      <td className="px-3 py-2 text-slate-200">{(row.affected_probability * 100).toFixed(1)}%</td>
      <td className="px-3 py-2 text-slate-200">{row.customer_initials ?? "—"}</td>
      <td className="px-3 py-2 text-slate-200">{row.email_masked ?? "—"}</td>
      <td className="px-3 py-2 text-slate-300">{new Date(row.timestamp_utc).toLocaleString()}</td>
      <td className="px-3 py-2 font-mono text-slate-300">{row.transaction_id.slice(0, 8)}</td>
    </tr>
  );
}
