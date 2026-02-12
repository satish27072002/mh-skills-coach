import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import Home from "../app/page";

const replaceMock = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock })
}));

describe("Chat UI", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    replaceMock.mockReset();
  });

  it("sends a message and renders assistant reply", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/me")) {
        return Promise.resolve(
          new Response(JSON.stringify({ is_premium: false }), { status: 200 })
        );
      }
      if (url.includes("/api/status")) {
        return Promise.resolve(
          new Response(JSON.stringify({ agent_mode: "deterministic", model: "demo" }), { status: 200 })
        );
      }
      if (url.includes("/api/chat")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({ coach_message: "Thanks for sharing.", resources: [], premium_cta: null }),
            { status: 200 }
          )
        );
      }
      return Promise.resolve(new Response("Not found", { status: 404 }));
    });

    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);

    render(React.createElement(Home));

    const textarea = await screen.findByPlaceholderText(/i feel anxious/i);
    fireEvent.change(textarea, { target: { value: "hello" } });
    fireEvent.click(screen.getByText("Send"));

    await waitFor(() => {
      expect(screen.getByText(/thanks for sharing/i)).toBeInTheDocument();
    });
  });

  it("redirects to login when unauthenticated", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/me")) {
        return Promise.resolve(new Response("Unauthorized", { status: 401 }));
      }
      return Promise.resolve(new Response("Not found", { status: 404 }));
    });

    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);

    render(React.createElement(Home));

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/login");
    });
  });

  it("shows Get Premium therapist CTA in header when user is free", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/me")) {
        return Promise.resolve(
          new Response(JSON.stringify({ is_premium: false }), { status: 200 })
        );
      }
      if (url.includes("/api/status")) {
        return Promise.resolve(
          new Response(JSON.stringify({ agent_mode: "deterministic", model: "demo" }), { status: 200 })
        );
      }
      if (url.includes("/api/chat")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              coach_message: "Here to help.",
              premium_cta: { enabled: true, message: "Find a therapist" }
            }),
            { status: 200 }
          )
        );
      }
      if (url.includes("/api/payments/create-checkout-session")) {
        return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }));
      }
      return Promise.resolve(new Response("Not found", { status: 404 }));
    });

    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);

    render(React.createElement(Home));

    const textarea = await screen.findByPlaceholderText(/i feel anxious/i);
    fireEvent.change(textarea, { target: { value: "find a therapist" } });
    fireEvent.click(screen.getByText("Send"));

    const therapistButton = await screen.findByRole("button", {
      name: /get premium to find a therapist/i
    });
    fireEvent.click(therapistButton);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/payments/create-checkout-session"),
        expect.objectContaining({ method: "POST", credentials: "include" })
      );
    });
  });

  it("shows therapist modal CTA in header when user is premium", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/me")) {
        return Promise.resolve(
          new Response(JSON.stringify({ is_premium: true }), { status: 200 })
        );
      }
      if (url.includes("/api/status")) {
        return Promise.resolve(
          new Response(JSON.stringify({ agent_mode: "deterministic", model: "demo" }), { status: 200 })
        );
      }
      if (url.includes("/api/chat")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              coach_message: "Here to help.",
              premium_cta: { enabled: true, message: "Find a therapist" }
            }),
            { status: 200 }
          )
        );
      }
      return Promise.resolve(new Response("Not found", { status: 404 }));
    });

    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);

    render(React.createElement(Home));

    const textarea = await screen.findByPlaceholderText(/i feel anxious/i);
    fireEvent.change(textarea, { target: { value: "find a therapist" } });
    fireEvent.click(screen.getByText("Send"));

    const therapistButton = await screen.findByRole("button", {
      name: /find a therapist/i
    });
    fireEvent.click(therapistButton);

    await waitFor(() => {
      expect(screen.getByText(/therapist search/i)).toBeInTheDocument();
    });
  });

  it("renders booking proposal card and sends YES/NO through normal chat flow", async () => {
    const chatCalls: string[] = [];
    const proposalPayload = {
      coach_message: "Please confirm this booking request.",
      requires_confirmation: true,
      booking_proposal: {
        therapist_email: "therapist@example.com",
        requested_time: "2026-02-14 15:00 Europe/Stockholm",
        subject: "Appointment request",
        body: "Hello, I would like to request an appointment.",
        expires_at: "2026-02-14T15:15:00+01:00"
      }
    };

    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/me")) {
        return Promise.resolve(
          new Response(JSON.stringify({ is_premium: true }), { status: 200 })
        );
      }
      if (url.includes("/api/status")) {
        return Promise.resolve(
          new Response(JSON.stringify({ agent_mode: "llm_rag", model: "demo" }), { status: 200 })
        );
      }
      if (url.includes("/api/chat")) {
        const payload = JSON.parse((init?.body as string) || "{}") as { message?: string };
        const message = payload.message || "";
        chatCalls.push(message);
        if (message === "book now" || message === "book again") {
          return Promise.resolve(new Response(JSON.stringify(proposalPayload), { status: 200 }));
        }
        if (message === "YES") {
          return Promise.resolve(
            new Response(JSON.stringify({ coach_message: "Email sent.", requires_confirmation: false }), {
              status: 200
            })
          );
        }
        if (message === "NO") {
          return Promise.resolve(
            new Response(JSON.stringify({ coach_message: "Cancelled.", requires_confirmation: false }), {
              status: 200
            })
          );
        }
        return Promise.resolve(new Response(JSON.stringify({ coach_message: "ok" }), { status: 200 }));
      }
      return Promise.resolve(new Response("Not found", { status: 404 }));
    });

    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);

    render(React.createElement(Home));

    const textarea = await screen.findByPlaceholderText(/i feel anxious/i);
    fireEvent.change(textarea, { target: { value: "book now" } });
    fireEvent.click(screen.getByText("Send"));

    await waitFor(() => {
      expect(screen.getByText(/booking proposal/i)).toBeInTheDocument();
      expect(screen.getByText(/therapist@example.com/i)).toBeInTheDocument();
      expect(screen.getByText(/expires at:/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /send email/i }));

    await waitFor(() => {
      expect(chatCalls).toContain("YES");
      expect(screen.getByText(/email sent\./i)).toBeInTheDocument();
    });

    fireEvent.change(textarea, { target: { value: "book again" } });
    fireEvent.click(screen.getByText("Send"));

    await waitFor(() => {
      expect(screen.getByText(/booking proposal/i)).toBeInTheDocument();
    });

    const cancelButtons = screen.getAllByRole("button", { name: /cancel/i });
    fireEvent.click(cancelButtons[cancelButtons.length - 1]);

    await waitFor(() => {
      expect(chatCalls).toContain("NO");
      expect(screen.getByText(/cancelled\./i)).toBeInTheDocument();
    });
  });
});
