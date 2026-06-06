/** @type {import('next').NextConfig} */

// F6e — baseline security headers. CSP is intentionally pragmatic: it locks down
// framing (clickjacking) and object/base-uri while allowing the inline scripts/
// styles Next + Tailwind require and the https/wss connections to Supabase + the
// backend API. Tighten script-src with nonces in a future hardening pass.
const ContentSecurityPolicy = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  "media-src 'self' blob: https:",
  // https/wss covers Supabase + an HTTPS backend in prod; localhost covers the
  // dev API (NEXT_PUBLIC_API_URL defaults to http://localhost:8001) so CSP does
  // not break `npm run dev`.
  "connect-src 'self' https: wss: http://localhost:* http://127.0.0.1:*",
  "font-src 'self' data:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: ContentSecurityPolicy },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig = {
  reactStrictMode: true,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
