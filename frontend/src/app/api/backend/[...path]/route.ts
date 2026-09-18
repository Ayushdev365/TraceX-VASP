/**
 * Server-side proxy to the FastAPI backend.
 *
 * The browser never talks to the backend directly. Every request goes through this route
 * handler, which runs on the server and injects `X-Api-Key` from the environment — so the
 * key is never shipped in a bundle, a network tab, or a page source (brief: "Keep API keys
 * server-side").
 *
 * It also means the frontend has no CORS surface and no public backend URL to leak.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = (
  process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000/api/v1"
).replace(/\/$/, "");

/** Headers we forward upstream. An allowlist, so a browser cannot smuggle anything else. */
const FORWARD_REQUEST_HEADERS = ["content-type", "x-request-id", "idempotency-key"];

/** Headers we return downstream. */
const FORWARD_RESPONSE_HEADERS = [
  "content-type",
  "content-disposition",
  "x-request-id",
  "retry-after",
  "etag",
  "x-ratelimit-limit",
  "x-ratelimit-remaining",
];

function upstreamUrl(request: NextRequest, path: string[]): string {
  const search = request.nextUrl.search;
  return `${BACKEND_URL}/${path.join("/")}${search}`;
}

function buildHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const apiKey = process.env.DEMO_API_KEY;
  if (apiKey) headers.set("X-Api-Key", apiKey);
  return headers;
}

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const { path } = await context.params;

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl(request, path), {
      method: request.method,
      headers: buildHeaders(request),
      body: request.method === "GET" || request.method === "HEAD" ? undefined : await request.text(),
      cache: "no-store",
      // A trace is budgeted at ~10s server-side; allow headroom before giving up.
      signal: AbortSignal.timeout(30_000),
    });
  } catch (cause) {
    // Never surface the internal URL or the raw cause to the browser.
    const isTimeout = cause instanceof Error && cause.name === "TimeoutError";
    return NextResponse.json(
      {
        error: {
          code: isTimeout ? "BACKEND_TIMEOUT" : "BACKEND_UNAVAILABLE",
          message: isTimeout
            ? "The attribution engine did not respond in time."
            : "The attribution engine is not reachable. Check that the backend is running.",
          details: {},
          request_id: null,
        },
      },
      { status: isTimeout ? 504 : 503 },
    );
  }

  const headers = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }

  return new NextResponse(upstream.body, { status: upstream.status, headers });
}

export const GET = proxy;
export const POST = proxy;
export const dynamic = "force-dynamic";
