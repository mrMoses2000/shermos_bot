import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { describeApiError, normalizePhoneInput } from "./Login";

describe("normalizePhoneInput", () => {
  it("strips spaces, dashes and parens", () => {
    expect(normalizePhoneInput("+7 (700) 576-68-41")).toBe("+77005766841");
  });

  it("preserves leading plus", () => {
    expect(normalizePhoneInput("+77085766841")).toBe("+77085766841");
  });

  it("does not invent a leading plus when user did not type one", () => {
    expect(normalizePhoneInput("77085766841")).toBe("77085766841");
  });

  it("returns empty for non-digit garbage", () => {
    expect(normalizePhoneInput("---")).toBe("");
    expect(normalizePhoneInput("   ")).toBe("");
    expect(normalizePhoneInput("")).toBe("");
  });
});

describe("describeApiError", () => {
  it("flags network/CORS failures (status 0) explicitly", () => {
    const msg = describeApiError(new ApiError(0, "fetch failed"), "Не удалось");
    expect(msg).toContain("CORS");
  });

  it("surfaces 429 with retry hint", () => {
    const msg = describeApiError(
      new ApiError(429, "Too many requests"),
      "Не удалось"
    );
    expect(msg).toContain("429");
    expect(msg.toLowerCase()).toContain("подожд");
  });

  it("includes server detail and HTTP status for unexpected errors", () => {
    const msg = describeApiError(
      new ApiError(418, "I'm a teapot"),
      "Не удалось"
    );
    expect(msg).toContain("418");
    expect(msg).toContain("teapot");
  });

  it("falls back to fallback text for non-ApiError throwables", () => {
    const msg = describeApiError(new Error("boom"), "Что-то сломалось");
    expect(msg).toContain("Что-то сломалось");
    expect(msg).toContain("boom");
  });
});
