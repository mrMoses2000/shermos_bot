/**
 * Smoke tests for the CMS pages — only Login was tested before, so any
 * regression in PricingEditor / Materials / Orders / etc. would have shipped
 * to Netlify silently. These render each page against a stubbed fetch and
 * assert the component (a) imports without throwing, (b) survives an empty
 * API response, (c) shows the expected fallback UI.
 *
 * No @testing-library/react — we drive React directly via react-dom/client
 * to keep the test deps minimal (we already have happy-dom + react + vitest).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import PricingEditor from "./PricingEditor";
import MaterialsPage from "./Materials";

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => {
    root.unmount();
  });
  container.remove();
  vi.unstubAllGlobals();
});

const flushAsync = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

const stubFetch = (responses: Record<string, unknown>) => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : (input as Request).url;
    for (const path in responses) {
      if (url.includes(path)) {
        return new Response(JSON.stringify(responses[path]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
    }
    return new Response(JSON.stringify({ error: "not stubbed" }), { status: 404 });
  }));
};

describe("PricingEditor — smoke", () => {
  it("renders empty-state when prices list is empty", async () => {
    stubFetch({
      "/api/pricing/prices": { items: [] },
      "/api/pricing/materials": { items: [] },
    });

    await act(async () => {
      root.render(<PricingEditor initData={{ jwt: true }} />);
      await flushAsync();
    });

    expect(container.innerHTML).toContain("Прайс-лист пока не загружен");
  });

  it("renders the prices section heading when prices exist", async () => {
    stubFetch({
      "/api/pricing/prices": {
        items: [
          { id: 1, category: "frame", name: "Алюминий", value: 100, currency: "USD" },
        ],
      },
      "/api/pricing/materials": {
        items: [
          { id: "1", kind: "frame", name: "Серебро", color: [0.8, 0.8, 0.8] },
        ],
      },
    });

    await act(async () => {
      root.render(<PricingEditor initData={{ jwt: true }} />);
      await flushAsync();
    });

    expect(container.innerHTML).toContain("Цены");
  });

  it("does not crash when API returns 404 for both endpoints", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ error: "x" }), { status: 404 })),
    );

    await act(async () => {
      root.render(<PricingEditor initData={{ jwt: true }} />);
      await flushAsync();
    });

    // Component falls back to empty arrays in the catch handler, which then
    // hits the empty-state branch.
    expect(container.innerHTML).toContain("Прайс-лист пока не загружен");
  });
});

describe("Materials — smoke", () => {
  it("renders without crashing on empty API responses", async () => {
    stubFetch({
      "/api/pricing/materials": { items: [] },
      "/api/pricing/codegen/tasks": { items: [] },
    });

    await act(async () => {
      root.render(<MaterialsPage initData={{ jwt: true }} />);
      await flushAsync();
    });

    // Some marker that the materials page actually mounted (any text from
    // the component is fine for a smoke test — we just want no JS exception).
    expect(container.innerHTML.length).toBeGreaterThan(0);
  });

  it("displays material when API returns one", async () => {
    stubFetch({
      "/api/pricing/materials": {
        items: [
          {
            id: "1",
            kind: "frame",
            name: "Чёрный матовый",
            color: [0.1, 0.1, 0.1],
            is_active: true,
          },
        ],
      },
      "/api/pricing/codegen/tasks": { items: [] },
    });

    await act(async () => {
      root.render(<MaterialsPage initData={{ jwt: true }} />);
      await flushAsync();
    });

    expect(container.innerHTML).toContain("Чёрный матовый");
  });
});
