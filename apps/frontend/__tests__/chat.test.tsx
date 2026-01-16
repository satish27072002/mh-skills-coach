import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import Home from "../app/page";

describe("Chat UI", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sends a message and renders assistant reply", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/me")) {
        return Promise.resolve(
          new Response(JSON.stringify({ is_premium: false }), { status: 200 })
        );
      }
      if (url.includes("/status")) {
        return Promise.resolve(
          new Response(JSON.stringify({ agent_mode: "deterministic", model: "demo" }), { status: 200 })
        );
      }
      if (url.includes("/chat")) {
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

    const textarea = screen.getByPlaceholderText(/i feel anxious/i);
    fireEvent.change(textarea, { target: { value: "hello" } });
    fireEvent.click(screen.getByText("Send"));

    await waitFor(() => {
      expect(screen.getByText(/thanks for sharing/i)).toBeInTheDocument();
    });
  });
});
