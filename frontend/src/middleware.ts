import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

/**
 * F6d — default-deny auth gate (defense-in-depth).
 *
 * The backend (FastAPI) is the real authorization boundary; this middleware
 * adds a server-side check so a newly added page isn't accidentally public.
 * Unauthenticated requests to any matched (non-/auth) route are redirected to
 * /auth/login.
 *
 * Uses ONLY the public anon key — never the service-role key — and validates
 * the session server-side via getUser() (not getSession(), which doesn't
 * re-verify the JWT). Cookie refresh follows the @supabase/ssr getAll/setAll
 * contract. If Supabase is unreachable, we fail open (let the request through)
 * so an auth outage can't lock everyone out; the backend still rejects
 * unauthenticated API calls.
 */
export async function middleware(request: NextRequest) {
  let supabaseResponse = NextResponse.next({ request });

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  // Misconfiguration: don't block the app if env is missing.
  if (!url || !anonKey) return supabaseResponse;

  const supabase = createServerClient(url, anonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(
        cookiesToSet: {
          name: string;
          value: string;
          options?: Record<string, unknown>;
        }[],
      ) {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
        supabaseResponse = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          supabaseResponse.cookies.set(name, value, options),
        );
      },
    },
  });

  let user = null;
  try {
    const { data } = await supabase.auth.getUser();
    user = data.user;
  } catch {
    // Auth backend unreachable → fail open (client-side guard + backend still gate).
    return supabaseResponse;
  }

  const isAuthRoute = request.nextUrl.pathname.startsWith("/auth");
  if (!user && !isAuthRoute) {
    const redirectUrl = request.nextUrl.clone();
    redirectUrl.pathname = "/auth/login";
    redirectUrl.search = "";
    return NextResponse.redirect(redirectUrl);
  }

  return supabaseResponse;
}

export const config = {
  // Skip Next internals, static assets, image files, and /auth/* (the login/
  // register pages must be reachable while logged out). Backend /api/v1/* is a
  // separate origin and never hits this middleware.
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|icon.svg|logo.svg|auth|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
