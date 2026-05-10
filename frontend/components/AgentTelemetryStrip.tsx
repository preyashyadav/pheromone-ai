"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

export function AgentTelemetryStrip() {
  const agents = useQuery({
    queryKey: ["agentsTelemetry"],
    queryFn: api.getAgentsTelemetry,
    refetchInterval: 2_000
  });
  const gpu = useQuery({
    queryKey: ["gpuTelemetry"],
    queryFn: api.getGpuTelemetry,
    refetchInterval: 5_000
  });

  return (
    <footer className="fixed bottom-0 left-0 right-0 z-30 border-t border-slate-800 bg-slate-950">
      <div className="mx-auto grid max-w-6xl gap-3 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="text-xs text-slate-400">
            Agent telemetry (demo-safe): tokens + latency + GPU utilization
          </div>
          <div className="flex items-center gap-3 text-xs">
            <Metric label="MI300X mem" value={gpu.data ? `${gpu.data.memory_pct}%` : "…"} />
            <Metric label="MI300X compute" value={gpu.data ? `${gpu.data.compute_pct}%` : "…"} />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          {(agents.data?.agents ?? []).map((a) => (
            <div
              key={a.agent}
              className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2"
            >
              <div className="flex items-center justify-between">
                <div className="text-xs font-medium text-slate-100">{a.agent}</div>
                <div className="text-[10px] text-slate-400">{a.state}</div>
              </div>
              <div className="mt-1 flex items-center justify-between text-[10px] text-slate-300">
                <span>in {a.tokens_in}</span>
                <span>out {a.tokens_out}</span>
                <span>{a.latency_ms}ms</span>
              </div>
            </div>
          ))}

          {agents.isLoading ? (
            <div className="col-span-2 text-xs text-slate-500 sm:col-span-3 lg:col-span-6">
              Loading telemetry…
            </div>
          ) : null}

          {agents.isError ? (
            <div className="col-span-2 text-xs text-rose-300 sm:col-span-3 lg:col-span-6">
              Agent telemetry unavailable (check backend `/api/telemetry/agents`).
            </div>
          ) : null}
        </div>
      </div>
    </footer>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-900 px-2 py-1">
      <span className="text-slate-400">{label}:</span> <span className="text-slate-100">{value}</span>
    </div>
  );
}
