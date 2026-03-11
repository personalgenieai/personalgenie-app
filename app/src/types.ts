// PersonalGenie — shared TypeScript types

export interface User {
  user_id: string;
  name: string;
  phone: string;
  whatsapp_consented: boolean;
}

export interface Memory {
  description: string;
  created_at?: string;
}

export interface Person {
  id: string;
  name: string;
  relationship_type: string;
  closeness_score: number;
  last_meaningful_exchange?: string;
  status?: string;          // 'active' | 'deceased'
  memories: Memory[];
}

export interface Moment {
  id: string;
  person_id: string;
  suggestion: string;
  triggered_by: string;
  status: string;
  created_at: string;
  people?: { name: string; relationship_type?: string };
}

export interface HealthSummary {
  today: {
    id?: string;
    summary_date: string;
    total_calories: number;
    total_protein: number;
    trained: boolean;
    nudge_sent?: boolean;
  } | null;
  days_logging: number;
  habit_established: boolean;
}

export interface WeeklyRollup {
  days_logged: number;
  avg_calories: number;
  avg_protein_g: number;
  training_sessions: number;
}

export interface GenieRule {
  id: string;
  user_id: string;
  plain_english: string;
  trigger_type: string;
  action_type: string;
  trigger_config: Record<string, any>;
  action_config: Record<string, any>;
  is_active: boolean;
  created_at: string;
}

export interface Subscription {
  plan: string;
  status: string;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
}

export interface TrainingSession {
  id: string;
  session_date: string;
  duration_minutes: number | null;
  exercises: Array<{
    name: string;
    sets: Array<{ reps: number; weight_kg: number }>;
  }>;
  summary: string;
  trainer_notes: string;
  calories_burned: number | null;
}

export interface Plan {
  id: string;
  name: string;
  price_monthly: number;
  features: string[];
  stripe_price_id?: string;
}
