"use client";

import { useQuery } from "@tanstack/react-query";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";
const DEFAULT_MAX = 50 * 1024 * 1024;

type PublicConfig = { max_file_bytes: number };

export function useConfig() {
  return useQuery<PublicConfig | null>({
    queryKey: ["public-config"],
    queryFn: async () => {
      try {
        const r = await fetch(`${API}/api/v1/config`);
        if (!r.ok) return null;
        return await r.json();
      } catch {
        return null;
      }
    },
    staleTime: 1000 * 60 * 60,
    retry: false,
    refetchOnWindowFocus: false,
  });
}

export function getMaxFileBytes(cfg: PublicConfig | null | undefined): number {
  return cfg?.max_file_bytes ?? DEFAULT_MAX;
}
