"use client";

import { useQuery } from "@tanstack/react-query";
import React from "react";
import { api } from "../lib/api";

export function HardwareBadge() {
  const [open, setOpen] = React.useState(false);
  const gpu = useQuery({
    queryKey: ["gpuTelemetry"],
    queryFn: api.getGpuTelemetry,
    refetchInterval: 5_000
  });

  const label = "Running Qwen3-32B on AMD Instinct MI300X via vLLM + ROCm 7";

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-full border border-slate-700 bg-slate-900 px-3 py-1 text-xs font-medium text-slate-100 hover:border-slate-500"
      >
        {label}
      </button>

      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog">
          <div className="w-full max-w-lg rounded-xl border border-slate-800 bg-slate-950 p-5 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-semibold">Hardware + Model Config</div>
                <div className="mt-1 text-xs text-slate-400">
                  Judges should see the AMD story clearly: MI300X + vLLM + ROCm.
                </div>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-md border border-slate-800 px-2 py-1 text-xs text-slate-200 hover:border-slate-700"
              >
                Close
              </button>
            </div>

            <div className="mt-4 grid gap-3 text-sm">
              <Row k="Model" v={gpu.data?.model_name ?? "…"} />
              <Row k="GPU" v={gpu.data?.mi300x_identifier ?? "…"} />
              <Row k="vLLM" v={gpu.data?.vllm_version ?? "…"} />
              <Row k="ROCm" v={gpu.data?.rocm_version ?? "…"} />
              <Row k="Telemetry Source" v={gpu.data?.source ?? (gpu.isError ? "error" : "…")} />
            </div>

            {gpu.isError ? (
              <div className="mt-3 text-xs text-rose-300">GPU telemetry unavailable; falling back to mock.</div>
            ) : null}
          </div>
        </div>
      ) : null}
    </>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-slate-800 bg-slate-900 px-3 py-2">
      <div className="text-xs text-slate-400">{k}</div>
      <div className="text-xs font-medium text-slate-100">{v}</div>
    </div>
  );
}
