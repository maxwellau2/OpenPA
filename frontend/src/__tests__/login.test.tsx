import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LoginPage from "@/app/login/page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: null, loading: false, setAuth: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  login: vi.fn(),
  signup: vi.fn(),
}));

function renderLogin() {
  const { container } = render(<LoginPage />);
  // Get the first rendered instance to avoid strict-mode duplicates
  const card = container.querySelector("[data-slot='card']")!;
  return within(card as HTMLElement);
}

describe("LoginPage", () => {
  it("renders login form", () => {
    const view = renderLogin();
    expect(view.getByText("OpenPA")).toBeInTheDocument();
    expect(view.getByPlaceholderText("Email")).toBeInTheDocument();
    expect(view.getByPlaceholderText("Password")).toBeInTheDocument();
    expect(view.getByRole("button", { name: "Log In" })).toBeInTheDocument();
  });

  it("toggles between login and signup", async () => {
    const user = userEvent.setup();
    const view = renderLogin();

    await user.click(view.getByText(/Need an account/));
    expect(view.getByPlaceholderText("Display name")).toBeInTheDocument();
    expect(view.getByRole("button", { name: "Sign Up" })).toBeInTheDocument();

    await user.click(view.getByText(/Already have an account/));
    expect(view.queryByPlaceholderText("Display name")).not.toBeInTheDocument();
    expect(view.getByRole("button", { name: "Log In" })).toBeInTheDocument();
  });

  it("shows error on failed login", async () => {
    const { login } = await import("@/lib/api");
    vi.mocked(login).mockRejectedValueOnce(new Error("Invalid credentials"));

    const user = userEvent.setup();
    const view = renderLogin();

    await user.type(view.getByPlaceholderText("Email"), "a@b.com");
    await user.type(view.getByPlaceholderText("Password"), "wrong");
    await user.click(view.getByRole("button", { name: "Log In" }));

    expect(await screen.findByText("Invalid credentials")).toBeInTheDocument();
  });
});
