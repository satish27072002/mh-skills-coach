import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { StatusBadge } from "../app/page";

describe("StatusBadge", () => {
  it("renders mode badge from /status response", async () => {
    const mockFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          agent_mode: "llm_rag",
          model: "demo-model"
        }),
        { status: 200 }
      )
    );

    render(React.createElement(StatusBadge, { fetcher: mockFetch }));

    await waitFor(() => {
      expect(screen.getByText(/LLM\+RAG/i)).toBeInTheDocument();
      expect(screen.getByText(/demo-model/i)).toBeInTheDocument();
    });
  });
});
