import { afterEach, describe, expect, test, vi } from "vitest";
import { ApiError, NetworkError, SessionExpiredError, createApi } from "./client";

function mockFetch(response: Partial<Response> & { json?: () => Promise<unknown> }) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}), ...response });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("createApi", () => {
  test("envía el token, la clave de idempotencia y nunca credenciales del navegador", async () => {
    const fetch = mockFetch({ json: async () => ({ ok: 1 }) });
    const api = createApi("https://api.test", () => "token-1", () => undefined);
    await api.request("/v1/plans", { method: "POST", body: {}, idempotencyKey: "web-key-123" });
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("https://api.test/v1/plans");
    expect(init.headers.Authorization).toBe("Bearer token-1");
    expect(init.headers["Idempotency-Key"]).toBe("web-key-123");
    expect(init.credentials).toBe("omit");
  });

  test("un 401 marca la sesión como vencida", async () => {
    mockFetch({ ok: false, status: 401 });
    const expired = vi.fn();
    const api = createApi("https://api.test", () => "t", expired);
    await expect(api.request("/v1/me")).rejects.toBeInstanceOf(SessionExpiredError);
    expect(expired).toHaveBeenCalledOnce();
  });

  test("sin token no llama a la API", async () => {
    const fetch = mockFetch({});
    const expired = vi.fn();
    const api = createApi("https://api.test", () => null, expired);
    await expect(api.request("/v1/me")).rejects.toBeInstanceOf(SessionExpiredError);
    expect(fetch).not.toHaveBeenCalled();
    expect(expired).toHaveBeenCalledOnce();
  });

  test("los errores conservan el código estable de la API", async () => {
    mockFetch({ ok: false, status: 409, json: async () => ({ detail: "x", code: "plan_superseded" }) });
    const api = createApi("https://api.test", () => "t", () => undefined);
    const error = (await api.request("/v1/scenarios/1/adoption", { method: "POST" }).catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("plan_superseded");
    expect(error.status).toBe(409);
  });

  test("un fallo de red se distingue de un error de la API", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const api = createApi("https://api.test", () => "t", () => undefined);
    await expect(api.request("/v1/me")).rejects.toBeInstanceOf(NetworkError);
  });
});
