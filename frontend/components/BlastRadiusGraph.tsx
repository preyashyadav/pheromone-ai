"use client";

import { useQuery } from "@tanstack/react-query";
import React from "react";
import ReactFlow, { Background, Controls, Edge, Node } from "reactflow";
import "reactflow/dist/style.css";
import { api } from "../lib/api";

export function BlastRadiusGraph({ recallCaseId }: { recallCaseId: string }) {
  const blast = useQuery({
    queryKey: ["blastRadius", recallCaseId],
    queryFn: () => api.getBlastRadius(recallCaseId),
    refetchInterval: 5_000
  });

  const data = blast.data?.blast_radius as any | null;
  const nodesAndEdges = React.useMemo(() => buildGraph(data), [data]);

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold">Blast Radius</div>
          <div className="mt-1 text-xs text-slate-400">
            Visual centerpiece: stores + transaction windows derived from deterministic trace.
          </div>
        </div>
        <div className="text-xs text-slate-400">
          {blast.isFetching ? "Updating…" : data ? "Latest snapshot" : "No snapshot yet"}
        </div>
      </div>

      <div className="mt-4 h-[520px] overflow-hidden rounded-lg border border-slate-800 bg-slate-950">
        <ReactFlow nodes={nodesAndEdges.nodes} edges={nodesAndEdges.edges} fitView>
          <Background color="#334155" gap={18} />
          <Controls />
        </ReactFlow>
      </div>

      {blast.isError ? (
        <div className="mt-3 text-xs text-rose-300">Failed to load blast radius snapshot.</div>
      ) : null}
    </div>
  );
}

function buildGraph(blast: any | null): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  nodes.push({
    id: "recall",
    position: { x: 0, y: 0 },
    data: { label: "Recall" },
    style: baseNodeStyle("#0f172a", "#38bdf8")
  });

  const stores: Array<{ store_id: string; peak: number }> = (blast?.affected_stores ?? []).map((s: any) => ({
    store_id: String(s.store_id),
    peak: Number(s.affected_stock_fraction_peak ?? 0)
  }));

  const windows: Array<{ store_id: string; count: number }> = (blast?.affected_transactions_window ?? []).map(
    (w: any) => ({
      store_id: String(w.store_id),
      count: Array.isArray(w.transaction_ids) ? w.transaction_ids.length : 0
    })
  );

  const byStoreCount = new Map<string, number>();
  for (const w of windows) byStoreCount.set(w.store_id, w.count);

  stores.forEach((s, idx) => {
    const storeNodeId = `store:${s.store_id}`;
    nodes.push({
      id: storeNodeId,
      position: { x: 260, y: idx * 110 - 40 },
      data: { label: `Store ${s.store_id.slice(0, 6)} · peak ${(s.peak * 100).toFixed(0)}%` },
      style: baseNodeStyle("#020617", "#a78bfa")
    });
    edges.push({
      id: `e:recall:${storeNodeId}`,
      source: "recall",
      target: storeNodeId,
      animated: true,
      style: { stroke: "#64748b" }
    });

    const txCount = byStoreCount.get(s.store_id) ?? 0;
    const txNodeId = `tx:${s.store_id}`;
    nodes.push({
      id: txNodeId,
      position: { x: 560, y: idx * 110 - 40 },
      data: { label: `${txCount.toLocaleString()} transactions` },
      style: baseNodeStyle("#020617", "#fb7185")
    });
    edges.push({
      id: `e:${storeNodeId}:${txNodeId}`,
      source: storeNodeId,
      target: txNodeId,
      animated: true,
      style: { stroke: "#64748b" }
    });
  });

  return { nodes, edges };
}

function baseNodeStyle(bg: string, ring: string) {
  return {
    background: bg,
    color: "#e2e8f0",
    border: `1px solid ${ring}`,
    borderRadius: 12,
    padding: 10,
    fontSize: 12,
    minWidth: 190
  } as const;
}
