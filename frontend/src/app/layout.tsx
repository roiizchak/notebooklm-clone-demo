import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "NotebookLM Reimagined",
  description: "API-first research intelligence platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen antialiased" suppressHydrationWarning>
        {process.env.NODE_ENV !== "production" && (
          <div
            id="hydration-banner"
            style={{
              position: "fixed",
              top: 0,
              left: 0,
              right: 0,
              zIndex: 9999,
              padding: "8px 16px",
              background: "#dc2626",
              color: "#fff",
              fontSize: "13px",
              fontFamily: "ui-monospace, monospace",
              textAlign: "center",
            }}
          >
            JS not hydrated — likely stale .next cache. Run{" "}
            <code style={{ background: "rgba(0,0,0,0.25)", padding: "0 4px", borderRadius: 2 }}>
              rm -rf .next &amp;&amp; npm run dev
            </code>
            .
          </div>
        )}
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
