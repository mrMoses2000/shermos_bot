import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, requestOtp, verifyOtp } from "./client";

function mockFetch(impl: typeof fetch) {
  vi.stubGlobal("fetch", vi.fn(impl));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("requestOtp", () => {
  it("resolves on 2xx", async () => {
    mockFetch(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));
    await expect(requestOtp("+77005766841")).resolves.toBeUndefined();
  });

  it("throws ApiError with detail from JSON body", async () => {
    mockFetch(
      async () =>
        new Response(JSON.stringify({ detail: "Phone is invalid" }), {
          status: 400,
          headers: { "content-type": "application/json" },
        })
    );
    await expect(requestOtp("xx")).rejects.toMatchObject({
      name: "ApiError",
      status: 400,
      detail: "Phone is invalid",
    });
  });

  it("throws ApiError with status 0 on network failure (CORS / DNS)", async () => {
    mockFetch(async () => {
      throw new TypeError("Failed to fetch");
    });
    const err = await requestOtp("+77005766841").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(err.detail).toContain("Failed to fetch");
  });

  it("falls back gracefully when error body is not JSON", async () => {
    mockFetch(async () => new Response("Internal Server Error", { status: 500 }));
    const err = await requestOtp("+77005766841").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(500);
    expect(err.detail).toContain("Internal Server Error");
  });
});

describe("verifyOtp", () => {
  it("returns access_token on success", async () => {
    mockFetch(
      async () =>
        new Response(JSON.stringify({ access_token: "tok-123", token_type: "bearer" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        })
    );
    await expect(verifyOtp("+77005766841", "12345678")).resolves.toBe("tok-123");
  });

  it("sends credentials so the refresh-token cookie is set", async () => {
    let capturedInit: RequestInit | undefined;
    mockFetch(async (_url, init) => {
      capturedInit = init as RequestInit;
      return new Response(JSON.stringify({ access_token: "tok-x" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    await verifyOtp("+77005766841", "12345678");
    expect(capturedInit?.credentials).toBe("include");
  });

  it("throws ApiError on 401 with server detail", async () => {
    mockFetch(
      async () =>
        new Response(JSON.stringify({ detail: "Invalid code" }), {
          status: 401,
          headers: { "content-type": "application/json" },
        })
    );
    const err = await verifyOtp("+77005766841", "00000000").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(401);
    expect(err.detail).toBe("Invalid code");
  });
});
