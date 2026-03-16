export interface DashboardSessionSummary {
  id: string;
  name: string;
  project_dir: string;
  source: "ccr" | "native";
  status: string;
  current_model: string | null;
  total_cost_usd: number;
  cost_is_estimated: boolean;
  message_count: number;
  context_percent: number | null;
  git_branch: string | null;
  created_at: string;
  updated_at: string;
  owner: string | null;
  claude_session_id: string | null;
  cron_job_id: string | null;
}

export interface DashboardSession extends DashboardSessionSummary {
  messages: Record<string, unknown>[];
  total_messages: number;
}

export interface SessionListResponse {
  sessions: DashboardSessionSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface DashboardAnalytics {
  active_sessions: number;
  total_cost_7d: number;
  top_model: string | null;
  active_cron_jobs: number;
}

export interface CronJobRun {
  id: string;
  cron_job_id: string;
  session_id: string | null;
  status: "success" | "error" | "running" | "timeout";
  started_at: string;
  completed_at: string | null;
  cost_usd: number;
  error_message: string | null;
}

export interface CronJob {
  id: string;
  name: string;
  schedule: string;
  enabled: boolean;
  execution_mode: "spawn" | "persistent";
  session_config: {
    name: string;
    project_dir: string;
    initial_prompt: string;
    model?: string | null;
    skip_permissions?: boolean;
  };
  persistent_session_id: string | null;
  project_dir: string;
  timeout_minutes: number | null;
  prompt_template: string | null;
  created_at: string;
  updated_at: string;
  next_run_at: string | null;
  last_run_at: string | null;
  last_run_status: string | null;
}

export interface CronJobWithRuns extends CronJob {
  recent_runs: CronJobRun[];
}

export interface CronJobCreateRequest {
  name: string;
  schedule: string;
  execution_mode: "spawn" | "persistent";
  session_config: {
    name: string;
    project_dir: string;
    initial_prompt: string;
    model?: string | null;
    skip_permissions?: boolean;
  };
  project_dir?: string;
  timeout_minutes?: number | null;
  prompt_template?: string | null;
  enabled?: boolean;
}
