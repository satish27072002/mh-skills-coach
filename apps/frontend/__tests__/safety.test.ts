import { classifyIntent, crisisResponse, prescriptionResponse } from "../app/api/_lib/safety";

describe("safety routing", () => {
  it("classifies crisis intent", () => {
    expect(classifyIntent("I want to die")).toBe("crisis");
  });

  it("classifies prescription intent", () => {
    expect(classifyIntent("Can you prescribe medication?")).toBe("prescription");
  });

  it("includes premium CTA for prescription requests", () => {
    const response = prescriptionResponse();
    expect(response.premium_cta?.enabled).toBe(true);
  });

  it("does not upsell during crisis responses", () => {
    const response = crisisResponse();
    expect(response.premium_cta).toBeUndefined();
  });
});
