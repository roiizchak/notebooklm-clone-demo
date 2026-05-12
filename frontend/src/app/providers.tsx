"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { useEffect, useState, type ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5_000,
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      }),
  );
  useEffect(() => {
    document.getElementById("hydration-banner")?.remove();
  }, []);
  return (
    <QueryClientProvider client={client}>
      {children}
      <Toaster theme="dark" position="bottom-right" richColors />
    </QueryClientProvider>
  );
}
