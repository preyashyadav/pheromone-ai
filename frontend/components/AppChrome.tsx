"use client";

import Link from "next/link";
import React from "react";
import { AgentTelemetryStrip } from "./AgentTelemetryStrip";
import { HardwareBadge } from "./HardwareBadge";

export function AppChrome({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-slate-800 bg-slate-950">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-4">
            <Link href="/recalls" className="text-sm font-semibold tracking-tight">
              Pheromone
            </Link>
            <span className="hidden text-xs text-slate-400 sm:inline">Trace + notification workflows for recalls.</span>
          </div>
          <HardwareBadge />
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6 pb-24">{children}</main>

      <AgentTelemetryStrip />
    </div>
  );
}
