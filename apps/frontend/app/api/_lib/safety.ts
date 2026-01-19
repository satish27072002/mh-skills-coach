export type Exercise = {
  type: string;
  steps: string[];
  duration_seconds: number;
};

export type Resource = {
  title: string;
  url: string;
  description?: string;
};

export type PremiumCta = {
  enabled: boolean;
  message: string;
};

export type TherapistResult = {
  name: string;
  address: string;
  url: string;
  phone: string;
  distance_km: number;
};

export type ChatResponse = {
  coach_message: string;
  exercise?: Exercise;
  resources?: Resource[];
  premium_cta?: PremiumCta;
  therapists?: TherapistResult[];
  risk_level?: string;
};

const CRISIS_KEYWORDS = [
  "suicide",
  "kill myself",
  "self-harm",
  "hurt myself",
  "end my life",
  "ending my life",
  "harm myself",
  "suicidal",
  "i want to die",
  "want to die",
  "end it all",
  "can't go on",
  "cannot go on",
  "life isn't worth living"
];

const THERAPIST_SEARCH_KEYWORDS = [
  "find therapist",
  "find a therapist",
  "therapist near me",
  "book therapist",
  "book a therapist",
  "counsellor near me",
  "counselor near me",
  "find me a therapist"
];

const PRESCRIPTION_KEYWORDS = [
  "prescribe",
  "prescription",
  "medication",
  "medicine",
  "meds",
  "mg",
  "pill",
  "pills",
  "tablet",
  "capsule",
  "dose",
  "dosage",
  "side effect",
  "side effects",
  "withdrawal",
  "taper",
  "tapering",
  "overdose",
  "antidepressant",
  "ssri",
  "benzodiazepine",
  "benzo",
  "xanax",
  "diazepam",
  "prozac",
  "sertraline",
  "zoloft",
  "citalopram",
  "escitalopram",
  "fluoxetine",
  "venlafaxine",
  "duloxetine",
  "sleeping pill",
  "sleeping pills",
  "painkiller",
  "ibuprofen",
  "paracetamol",
  "acetaminophen",
  "antibiotic",
  "opioid",
  "adderall",
  "ritalin",
  "vyvanse",
  "diagnosis",
  "diagnose"
];

const containsAny = (message: string, keywords: string[]) => {
  const lowered = message.toLowerCase();
  return keywords.some((keyword) => lowered.includes(keyword));
};

export type Intent = "crisis" | "therapist_search" | "prescription" | "default";

export const classifyIntent = (message: string): Intent => {
  if (containsAny(message, CRISIS_KEYWORDS)) {
    return "crisis";
  }
  if (containsAny(message, THERAPIST_SEARCH_KEYWORDS)) {
    return "therapist_search";
  }
  if (containsAny(message, PRESCRIPTION_KEYWORDS)) {
    return "prescription";
  }
  const lowered = message.toLowerCase();
  const hasTherapistTerm = ["therapist", "counselor", "counsellor"].some((term) =>
    lowered.includes(term)
  );
  const hasIntent = ["find", "near me", "book", "search"].some((term) => lowered.includes(term));
  if (hasTherapistTerm && hasIntent) {
    return "therapist_search";
  }
  return "default";
};

export const crisisResponse = (): ChatResponse => ({
  coach_message:
    "I am really sorry you are feeling this way. If you are in immediate danger, please call your local emergency number right now. In Sweden, call 112 for emergencies. If you can, reach out to someone you trust and let them know you need support.",
  resources: [
    { title: "Emergency services (Sweden)", url: "https://www.112.se/" },
    { title: "Find local crisis lines", url: "https://www.iasp.info/resources/Crisis_Centres/" }
  ],
  risk_level: "crisis"
});

export const prescriptionResponse = (): ChatResponse => ({
  coach_message:
    "This is beyond my capability. I cannot help with prescriptions, dosing, or medication changes. Please contact a licensed clinician or pharmacist. If you think you may be in immediate danger, call your local emergency number now (Sweden: 112).",
  resources: [
    { title: "Emergency services (Sweden)", url: "https://www.112.se/" },
    { title: "Healthcare advice (Sweden)", url: "https://www.1177.se/" }
  ],
  premium_cta: {
    enabled: true,
    message: "Premium members can use the therapist directory to find licensed support."
  },
  risk_level: "crisis"
});

export const defaultResponse = (): ChatResponse => ({
  coach_message: "Thanks for sharing. Let us slow things down together. Here is a short grounding exercise to try.",
  exercise: {
    type: "5-4-3-2-1 grounding",
    steps: [
      "Name 5 things you can see.",
      "Name 4 things you can feel.",
      "Name 3 things you can hear.",
      "Name 2 things you can smell.",
      "Name 1 thing you can taste."
    ],
    duration_seconds: 90
  }
});

export const therapistCta = (): PremiumCta => ({
  enabled: true,
  message: "Premium is required to unlock therapist search."
});
