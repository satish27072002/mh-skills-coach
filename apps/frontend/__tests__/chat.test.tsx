import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import Home from "../app/page";

describe("Chat UI", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("sends a message and renders assistant reply", async () => {
    const fetchMock = vi.fn()
      // status call
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ agent_mode: "deterministic", model: "demo" }), { status: 200 })
      )
      // chat call
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ coach_message: "Thanks for sharing.", resources: [], premium_cta: null }),
          { status: 200 }
        )
      )
      // future status polls
      .mockResolvedValue(
        new Response(JSON.stringify({ agent_mode: "deterministic", model: "demo" }), { status: 200 })
      );

    vi.stubGlobal("fetch", fetchMock as unknown as typeof fetch);

    render(<Home />);

    const textarea = screen.getByPlaceholderText(/i feel anxious/i);
    fireEvent.change(textarea, { target: { value: "hello" } });
    fireEvent.click(screen.getByText("Send"));

    await waitFor(() => {
      expect(screen.getByText(/thanks for sharing/i)).toBeInTheDocument();
    });
  });
});
