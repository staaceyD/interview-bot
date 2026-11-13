// Grouped so the picker can show headings, and labelled so neither the picker
// nor a question tag has to render a raw value like "data_structures".
export const TOPIC_GROUPS = [
  {
    label: "Languages and frameworks",
    topics: [
      { value: "python", label: "Python" },
      { value: "javascript", label: "JavaScript" },
      { value: "typescript", label: "TypeScript" },
      { value: "react", label: "React" },
    ],
  },
  {
    label: "Engineering fundamentals",
    topics: [
      { value: "system_design", label: "System design" },
      { value: "databases", label: "Databases and SQL" },
      { value: "algorithms", label: "Algorithms" },
      { value: "data_structures", label: "Data structures" },
      { value: "concurrency", label: "Concurrency" },
      { value: "networking", label: "Networking and HTTP" },
      { value: "api_design", label: "API design" },
      { value: "security", label: "Security" },
      { value: "testing", label: "Testing" },
      { value: "operating_systems", label: "Operating systems" },
      { value: "devops", label: "DevOps and deployment" },
    ],
  },
] as const;

export type Topic = (typeof TOPIC_GROUPS)[number]["topics"][number]["value"];

// Every topic, flattened, in the order the picker shows them. A selection is
// kept in this order rather than the order it was clicked, so an interview
// reads back the same however it was picked.
export const TOPICS: readonly Topic[] = TOPIC_GROUPS.flatMap((group) =>
  group.topics.map((topic) => topic.value),
);

export const TOPIC_LABELS: Record<Topic, string> = Object.fromEntries(
  TOPIC_GROUPS.flatMap((group) => group.topics.map((topic) => [topic.value, topic.label])),
) as Record<Topic, string>;

// Labelled here rather than read from the server, like the topic list: which
// models to offer is a product decision, not a configuration detail. The values
// are the provider names the API accepts.
export const MODEL_PROVIDERS = [
  { value: "ollama", label: "Ollama (free)" },
  { value: "anthropic", label: "Claude" },
] as const;

export type ModelProvider = (typeof MODEL_PROVIDERS)[number]["value"];

// The hosted build runs on Claude alone: there is no Ollama next to the server,
// so there is nothing to pick between. Read when called, so a test can stub it.
export const isHosted = () => import.meta.env.VITE_APP_ENV === "production";

export const SIGN_IN_PROVIDERS = {
  google: "Google",
  github: "GitHub",
} as const;

export type SignInProvider = keyof typeof SIGN_IN_PROVIDERS;

export type Account = {
  sign_in_required: boolean;
  providers: SignInProvider[];
  user: { name: string; email: string | null } | null;
  // Null when the visitor is not counted: signed out, unlimited, or sign-in
  // is not required.
  questions_left: number | null;
};

export const DIFFICULTIES = ["junior", "mid", "senior"] as const;

export type Difficulty = (typeof DIFFICULTIES)[number];

export type Session = {
  session_id: string;
  topics: Topic[];
  difficulty: Difficulty;
  model_provider: string;
};

export type Question = {
  question_id: string;
  prompt: string;
  topic: Topic;
  difficulty: Difficulty;
};

export type Grade = {
  score: number;
  verdict: string;
  covered: string[];
  missed: string[];
};

export type ExplanationPoint = {
  point: string;
  detail: string;
};

export type Explanation = {
  answer: string;
  points: ExplanationPoint[];
  pitfalls: string[];
};

export type SessionState = {
  session_id: string;
  topics: Topic[];
  difficulty: Difficulty;
  model_provider: string;
  current_question: Question | null;
  current_grade: Grade | null;
  current_explanation: Explanation | null;
};

export const MAX_SCORE = 5;
