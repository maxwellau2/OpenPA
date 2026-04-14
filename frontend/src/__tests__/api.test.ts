import { describe, it, expect, vi, beforeEach } from "vitest";

const mockFetch = vi.fn();
global.fetch = mockFetch;

// Must import after mocking fetch
const { login, signup, getMe } = await import("@/lib/api");

describe("api", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    localStorage.clear();
  });

  it("login sends correct request", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ token: "t", user: { id: 1, email: "a@b.com" } }),
    });

    const res = await login("a@b.com", "pass");
    expect(res.token).toBe("t");

    const [url, opts] = mockFetch.mock.calls[0];
    expect(url).toContain("/api/auth/login");
    expect(JSON.parse(opts.body)).toEqual({ email: "a@b.com", password: "pass" });
  });

  it("signup sends display name", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ token: "t", user: { id: 1, email: "a@b.com" } }),
    });

    await signup("a@b.com", "pass", "Test");

    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.display_name).toBe("Test");
  });

  it("throws on non-ok response", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: () => Promise.resolve({ detail: "Invalid credentials" }),
    });

    await expect(login("a@b.com", "bad")).rejects.toThrow("Invalid credentials");
  });

  it("includes auth header when token exists", async () => {
    localStorage.setItem("openpa_token", "mytoken");
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ user: { id: 1 }, connected_services: { services: [] } }),
    });

    await getMe();

    const headers = mockFetch.mock.calls[0][1].headers;
    expect(headers.Authorization).toBe("Bearer mytoken");
  });
});
