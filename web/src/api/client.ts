// Cliente HTTP de la API v1. No guarda nada en el navegador: recibe el token en cada llamada.

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, code: string | null, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export class SessionExpiredError extends ApiError {
  constructor() {
    super(401, "session_expired", "Session expired");
  }
}

export class NetworkError extends Error {}

export type TokenSource = () => string | null;

export type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  idempotencyKey?: string;
  signal?: AbortSignal;
};

export function newIdempotencyKey(): string {
  return `web-${crypto.randomUUID()}`;
}

export function createApi(baseUrl: string, getToken: TokenSource, onSessionExpired: () => void) {
  async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const token = getToken();
    if (!token) {
      onSessionExpired();
      throw new SessionExpiredError();
    }
    const headers: Record<string, string> = { Authorization: `Bearer ${token}`, Accept: "application/json" };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;
    let response: Response;
    try {
      response = await fetch(`${baseUrl}${path}`, {
        method: options.method ?? "GET",
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: options.signal,
        credentials: "omit",
        cache: "no-store",
      });
    } catch (error) {
      if ((error as Error).name === "AbortError") throw error;
      throw new NetworkError("network");
    }
    if (response.status === 401) {
      onSessionExpired();
      throw new SessionExpiredError();
    }
    if (response.status === 204) return undefined as T;
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = data && typeof data.detail === "string" ? data.detail : "Request failed";
      const code = data && typeof data.code === "string" ? data.code : null;
      throw new ApiError(response.status, code, detail);
    }
    return data as T;
  }

  async function download(path: string): Promise<Blob> {
    const token = getToken();
    if (!token) {
      onSessionExpired();
      throw new SessionExpiredError();
    }
    const response = await fetch(`${baseUrl}${path}`, { headers: { Authorization: `Bearer ${token}` }, credentials: "omit", cache: "no-store" });
    if (response.status === 401) {
      onSessionExpired();
      throw new SessionExpiredError();
    }
    if (!response.ok) throw new ApiError(response.status, null, "Request failed");
    return response.blob();
  }

  return { request, download };
}

export type Api = ReturnType<typeof createApi>;
