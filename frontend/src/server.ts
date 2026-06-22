import "./lib/error-capture";

import {
  backendPathFromFrontendApiPath,
  normalizeDashboardSummaryResponse,
  normalizeQueueResponse,
  normalizeReasoningEventsResponse,
} from "./lib/backend-api";
import { consumeLastCapturedError } from "./lib/error-capture";
import { renderErrorPage } from "./lib/error-page";

type ServerEntry = {
  fetch: (request: Request, env: unknown, ctx: unknown) => Promise<Response> | Response;
};

let serverEntryPromise: Promise<ServerEntry> | undefined;

async function getServerEntry(): Promise<ServerEntry> {
  if (!serverEntryPromise) {
    serverEntryPromise = import("@tanstack/react-start/server-entry").then(
      (m) => ((m as { default?: ServerEntry }).default ?? (m as unknown as ServerEntry)),
    );
  }
  return serverEntryPromise;
}

function brandedErrorResponse(): Response {
  return new Response(renderErrorPage(), {
    status: 500,
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}

function jsonResponse(payload: unknown, init?: ResponseInit): Response {
  return new Response(JSON.stringify(payload), {
    ...init,
    headers: {
      "content-type": "application/json; charset=utf-8",
      ...(init?.headers ?? {}),
    },
  });
}

function getBackendBaseUrl(): string {
  const value = process.env.PYTHON_API_BASE_URL?.trim();
  if (!value) {
    throw new Error("PYTHON_API_BASE_URL is not configured");
  }
  return value.endsWith("/") ? value : `${value}/`;
}

async function maybeHandleApiProxy(request: Request): Promise<Response | null> {
  const incomingUrl = new URL(request.url);
  const backendPath = backendPathFromFrontendApiPath(incomingUrl.pathname);
  if (!backendPath) return null;

  let backendBaseUrl: string;
  try {
    backendBaseUrl = getBackendBaseUrl();
  } catch (error) {
    return jsonResponse(
      { message: error instanceof Error ? error.message : "Backend URL configuration error" },
      { status: 500 },
    );
  }

  const targetUrl = new URL(backendPath.replace(/^\//, ""), backendBaseUrl);
  targetUrl.search = incomingUrl.search;
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  headers.set("accept", "application/json");
  const body =
    request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer();

  let upstream: Response;
  try {
    upstream = await fetch(targetUrl, {
      method: request.method,
      headers,
      body,
    });
  } catch (error) {
    return jsonResponse(
      {
        message:
          error instanceof Error
            ? `Python API is unreachable at ${backendBaseUrl}`
            : "Python API is unreachable",
      },
      { status: 503 },
    );
  }

  if (!upstream.ok) {
    const body = await upstream.text();
    return new Response(body, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json; charset=utf-8",
      },
    });
  }

  let payload: unknown;
  try {
    const contentLength = upstream.headers.get("content-length");
    if (upstream.status === 204 || contentLength === "0") {
      payload = {};
    } else {
      payload = await upstream.json();
    }
  } catch (error) {
    return jsonResponse(
      { message: `Failed to parse response from backend: ${error instanceof Error ? error.message : 'unknown error'}` },
      { status: 502 },
    );
  }

  if (incomingUrl.pathname === "/api/queue") {
    return jsonResponse(normalizeQueueResponse(payload));
  }
  if (incomingUrl.pathname === "/api/reasoning-events") {
    return jsonResponse(normalizeReasoningEventsResponse(payload));
  }
  if (incomingUrl.pathname === "/api/dashboard-summary") {
    return jsonResponse(normalizeDashboardSummaryResponse(payload));
  }
  if (incomingUrl.pathname === "/api/human-decisions") {
    return jsonResponse(payload, { status: upstream.status });
  }
  if (
    incomingUrl.pathname === "/api/simulation/run" ||
    incomingUrl.pathname === "/api/simulation/status" ||
    incomingUrl.pathname === "/api/simulation/stop" ||
    incomingUrl.pathname === "/api/simulation/reset" ||
    incomingUrl.pathname === "/api/simulation/speed"
  ) {
    return jsonResponse(payload, { status: upstream.status });
  }

  return null;
}

function isCatastrophicSsrErrorBody(body: string, responseStatus: number): boolean {
  let payload: unknown;
  try {
    payload = JSON.parse(body);
  } catch {
    return false;
  }

  if (!payload || Array.isArray(payload) || typeof payload !== "object") {
    return false;
  }

  const fields = payload as Record<string, unknown>;
  const expectedKeys = new Set(["message", "status", "unhandled"]);
  if (!Object.keys(fields).every((key) => expectedKeys.has(key))) {
    return false;
  }

  return (
    fields.unhandled === true &&
    fields.message === "HTTPError" &&
    (fields.status === undefined || fields.status === responseStatus)
  );
}

// h3 swallows in-handler throws into a normal 500 Response with body
// {"unhandled":true,"message":"HTTPError"} — try/catch alone never fires for those.
async function normalizeCatastrophicSsrResponse(response: Response): Promise<Response> {
  if (response.status < 500) return response;
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) return response;

  const body = await response.clone().text();
  if (!isCatastrophicSsrErrorBody(body, response.status)) {
    return response;
  }

  console.error(consumeLastCapturedError() ?? new Error(`h3 swallowed SSR error: ${body}`));
  return brandedErrorResponse();
}

export default {
  async fetch(request: Request, env: unknown, ctx: unknown) {
    try {
      const proxiedResponse = await maybeHandleApiProxy(request);
      if (proxiedResponse) return proxiedResponse;

      const handler = await getServerEntry();
      const response = await handler.fetch(request, env, ctx);
      return await normalizeCatastrophicSsrResponse(response);
    } catch (error) {
      console.error(error);
      return brandedErrorResponse();
    }
  },
};
