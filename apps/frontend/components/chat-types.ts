export type ChatResponse = {
  coach_message: string;
  booking_proposal?: {
    therapist_email: string;
    requested_time: string;
    subject: string;
    body: string;
    expires_at: string;
  };
  requires_confirmation?: boolean;
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
    url?: string;
    source_url?: string;
    phone?: string;
    email?: string;
    distance_km: number;
  }[];
  sources?: { source_id: string; text?: string; snippet?: string }[];
  risk_level?: string;
};

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  booking_proposal?: ChatResponse["booking_proposal"];
  requires_confirmation?: boolean;
  exercise?: ChatResponse["exercise"];
  resources?: ChatResponse["resources"];
  therapists?: ChatResponse["therapists"];
  sources?: ChatResponse["sources"];
  premium_cta?: ChatResponse["premium_cta"];
  risk_level?: string;
};
