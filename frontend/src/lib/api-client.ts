/**
 * Typed client for the backend, via the server-side proxy at `/api/backend/*`.
 *
 * Errors always arrive in the backend's uniform envelope, so `ApiRequestError` carries the
 * machine code and the request id — the id is what an investigator quotes when something
 * goes wrong mid-case.
 */

import type {
  ApiError,
  DemoSubjectsResponse,
  DisclosureDraft,
  HealthResponse,
  PublicConfig,
  TraceReport,
  TraceRequest,
  TraceResult,
} from "@/lib/types";

const PROXY_BASE = "/api/backend";

export class ApiRequestError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId: string | null;
  readonly details: Record<string, unknown>;

  constructor(
    message: string,
    options: {
      code: string;
      status: number;
      requestId?: string | null;
      details?: Record<string, unknown>;
    },
  ) {
    super(message);
    this.name = "ApiRequestError";
    this.code = options.code;
    this.status = options.status;
    this.requestId = options.requestId ?? null;
    this.details = options.details ?? {};
  }
}

function isApiError(value: unknown): value is ApiError {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof (value as ApiError).error?.code === "string"
  );
}

async function request<T>(
  path: string,
  init: RequestInit & { signal?: AbortSignal } = {},
): Promise<T> {
  const response = await fetch(`${PROXY_BASE}${path}`, {
    ...init,
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });

  const payload: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    if (isApiError(payload)) {
      throw new ApiRequestError(payload.error.message, {
        code: payload.error.code,
        status: response.status,
        requestId: payload.error.request_id,
        details: payload.error.details,
      });
    }
    throw new ApiRequestError("The request could not be completed.", {
      code: "UNKNOWN_ERROR",
      status: response.status,
    });
  }

  return payload as T;
}

export const api = {
  health: (signal?: AbortSignal) => request<HealthResponse>("/health", { signal }),
  config: (signal?: AbortSignal) => request<PublicConfig>("/meta/config", { signal }),
  demoSubjects: (signal?: AbortSignal) =>
    request<DemoSubjectsResponse>("/traces/demo-subjects", { signal }),
  createTrace: (body: TraceRequest, signal?: AbortSignal) =>
    request<TraceResult>("/traces", {
      method: "POST",
      body: JSON.stringify(body),
      signal,
    }),
  getTrace: (traceId: string, signal?: AbortSignal) =>
    request<TraceResult>(`/traces/${traceId}`, { signal }),
  getReport: (traceId: string, signal?: AbortSignal) =>
    request<TraceReport>(`/traces/${traceId}/report.json`, { signal }),
  reviewTrace: (traceId: string, signal?: AbortSignal) =>
    request<{ trace_id: string; decision: string; note: string | null }>(
      `/traces/${traceId}/review`,
      {
        method: "POST",
        body: JSON.stringify({ decision: "accepted", note: "Accepted in demo UI." }),
        signal,
      },
    ),
  createDisclosure: (traceId: string, signal?: AbortSignal) =>
    request<DisclosureDraft>(`/traces/${traceId}/disclosure`, {
      method: "POST",
      signal,
    }),
};
