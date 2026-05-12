"use client";
import { useEffect } from "react";

const EVENT = "source-highlight";

export function dispatchHighlight(sourceId: string) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(EVENT, { detail: sourceId }));
}

export function useHighlightListener(handler: (sourceId: string) => void) {
  useEffect(() => {
    const fn = (e: Event) => {
      const ce = e as CustomEvent<string>;
      if (ce.detail) handler(ce.detail);
    };
    window.addEventListener(EVENT, fn);
    return () => window.removeEventListener(EVENT, fn);
  }, [handler]);
}
