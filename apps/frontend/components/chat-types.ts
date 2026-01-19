export type ChatResponse = {
  coach_message: string;
  exercise?: {
    type: string;
    steps: string[];
    duration_seconds: number;
  };
  resources?: { title: string; url: string; description?: string }[];
  premium_cta?: { enabled: boolean; message: string };
  therapists?: {
    name: string;
    address: string;
    url: string;
    phone: string;
    distance_km: number;
  }[];
  sources?: { source_id: string; text?: string; snippet?: string }[];
  risk_level?: string;
};

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  exercise?: ChatResponse["exercise"];
  resources?: ChatResponse["resources"];
  therapists?: ChatResponse["therapists"];
  sources?: ChatResponse["sources"];
  premium_cta?: ChatResponse["premium_cta"];
  risk_level?: string;
};
