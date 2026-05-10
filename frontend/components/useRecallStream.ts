"use client";

import React from "react";

const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8001";

export function useRecallStream(recallCaseId: string, onAnyEvent: () => void) {
  React.useEffect(() => {
    if (!recallCaseId) return;
    const es = new EventSource(`${baseUrl}/recalls/${recallCaseId}/stream`);
    es.onmessage = () => onAnyEvent();
    es.onerror = () => {
      // Keep the UI up even if SSE drops; polling queries still work.
    };
    return () => es.close();
  }, [recallCaseId, onAnyEvent]);
}

