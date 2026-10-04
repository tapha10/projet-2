-- Système d'analyse plus/moins 2,5 buts — simulation papier uniquement.
-- Idempotent : peut être rejoué sans perte (IF NOT EXISTS / OR REPLACE / ON CONFLICT DO NOTHING).
-- Toutes les tables portent le préfixe foot_ ; aucune autre table n'est touchée.

create table if not exists foot_config (
  key text primary key,
  value jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists foot_source_audit (
  id bigserial primary key,
  source text not null,
  url text,
  checked_at timestamptz not null default now(),
  accessible boolean not null,
  status_code integer,
  freshness text,
  coverage text,
  limits text,
  terms text,
  notes text
);

create table if not exists foot_matches (
  match_id text primary key,
  league text not null,
  season text,
  kickoff timestamptz,
  home text not null,
  away text not null,
  referee text,
  status text not null default 'SCHEDULED',
  created_at timestamptz not null default now()
);

create table if not exists foot_odds_snapshots (
  id bigserial primary key,
  match_id text not null references foot_matches(match_id),
  side text not null check (side in ('over','under')),
  line numeric not null default 2.5,
  odds numeric not null check (odds > 1),
  source text not null,
  captured_at timestamptz not null,
  unique (match_id, side, line, source, captured_at)
);

create table if not exists foot_team_news (
  id bigserial primary key,
  match_id text not null references foot_matches(match_id),
  team text not null,
  player text,
  role text,
  status text,
  impact_metric text,
  impact_value numeric,
  source text not null,
  captured_at timestamptz not null,
  after_lock boolean not null default false,
  notes text
);

create table if not exists foot_features (
  match_id text not null references foot_matches(match_id),
  model_version text not null,
  computed_at timestamptz not null,
  data_cutoff timestamptz not null,
  features jsonb not null,
  primary key (match_id, model_version, computed_at)
);

create table if not exists foot_model_versions (
  version text primary key,
  model text not null,
  params jsonb not null default '{}'::jsonb,
  status text not null default 'candidate' check (status in ('candidate','active','observation','retired')),
  validation jsonb,
  notes text,
  created_at timestamptz not null default now()
);

create table if not exists foot_predictions (
  id text primary key,
  match_id text not null references foot_matches(match_id),
  model text not null,
  model_version text not null,
  variant text not null default 'principal',
  side text not null check (side in ('over','under')),
  prob numeric not null check (prob >= 0 and prob <= 1),
  odds numeric check (odds > 1),
  odds_source text,
  odds_captured_at timestamptz,
  ev numeric,
  selected boolean not null default false,
  phase text not null,
  counted boolean not null default false,
  kickoff timestamptz not null,
  locked_at timestamptz not null,
  payload_hash text not null,
  created_at timestamptz not null default now(),
  check (locked_at < kickoff)
);

create table if not exists foot_combos (
  combo_id text primary key,
  day date not null,
  variant text not null,
  n_legs integer not null,
  combo_odds numeric,
  p_est numeric,
  breakeven numeric,
  phase text not null,
  counted boolean not null default false,
  locked_at timestamptz not null,
  payload_hash text not null,
  notes text,
  created_at timestamptz not null default now(),
  unique (day, variant)
);

create table if not exists foot_combo_legs (
  combo_id text not null references foot_combos(combo_id),
  leg_no integer not null,
  prediction_id text not null references foot_predictions(id),
  match_id text not null references foot_matches(match_id),
  primary key (combo_id, leg_no)
);

create table if not exists foot_results (
  match_id text primary key references foot_matches(match_id),
  fthg integer,
  ftag integer,
  total integer,
  status text not null check (status in ('FT','POSTPONED','CANCELLED','ABANDONED')),
  source text not null,
  settled_at timestamptz not null default now()
);

create table if not exists foot_combo_results (
  combo_id text primary key references foot_combos(combo_id),
  outcome text not null check (outcome in ('win','loss','void','pending')),
  payout numeric,
  legs_void integer not null default 0,
  notes text,
  settled_at timestamptz not null default now()
);

create table if not exists foot_daily_reports (
  day date primary key,
  phase text not null,
  n_predictions_cum integer,
  content text not null,
  created_at timestamptz not null default now()
);

create table if not exists foot_weekly_reports (
  week_start date primary key,
  phase text not null,
  verdict text,
  content text not null,
  created_at timestamptz not null default now()
);

create table if not exists foot_experiments (
  id bigserial primary key,
  exp_key text not null unique,
  hypothesis text not null,
  protocol jsonb not null,
  data_desc text,
  period text,
  model text,
  result jsonb,
  ci_low numeric,
  ci_high numeric,
  conclusion text not null check (conclusion in ('confirmé','infirmé','inconclusif','en cours')),
  rerun_of text,
  rerun_reason text,
  created_at timestamptz not null default now()
);

create table if not exists foot_lessons (
  id bigserial primary key,
  error text not null,
  rule text not null,
  source_ref text,
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists foot_error_analysis (
  id bigserial primary key,
  prediction_id text not null references foot_predictions(id),
  match_id text not null references foot_matches(match_id),
  cause text not null check (cause in ('variance normale','absence tardive','carton rouge précoce',
    'météo','rotation','mauvais modèle','mauvaise donnée','erreur de procédure','indéterminé')),
  evidence text not null,
  created_at timestamptz not null default now(),
  unique (prediction_id)
);

create table if not exists foot_hypotheses (
  id bigserial primary key,
  title text not null unique,
  description text,
  priority integer not null default 3,
  status text not null default 'à tester' check (status in ('à tester','en cours','testée','abandonnée')),
  experiment_key text,
  created_at timestamptz not null default now()
);

create table if not exists foot_iteration_log (
  id bigserial primary key,
  routine text not null,
  run_day date,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null check (status in ('en cours','succès','échec','non exécutée','sec')),
  read_summary jsonb,
  changed_summary jsonb,
  why text,
  details text
);

create table if not exists foot_locks (
  name text primary key,
  holder text not null,
  acquired_at timestamptz not null default now(),
  expires_at timestamptz not null
);

-- Prédictions et combinés : ajout seulement (aucune modification, aucune suppression)
create or replace function foot_forbid_change() returns trigger
language plpgsql set search_path = '' as $$
begin
  raise exception 'Table % en ajout seulement : modification/suppression interdite', tg_table_name;
end $$;

drop trigger if exists foot_predictions_append_only on foot_predictions;
create trigger foot_predictions_append_only before update or delete on foot_predictions
  for each row execute function foot_forbid_change();
drop trigger if exists foot_combos_append_only on foot_combos;
create trigger foot_combos_append_only before update or delete on foot_combos
  for each row execute function foot_forbid_change();
drop trigger if exists foot_features_append_only on foot_features;
create trigger foot_features_append_only before update or delete on foot_features
  for each row execute function foot_forbid_change();
drop trigger if exists foot_combo_legs_append_only on foot_combo_legs;
create trigger foot_combo_legs_append_only before update or delete on foot_combo_legs
  for each row execute function foot_forbid_change();

-- RLS activée partout, sans politique pour anon/authenticated : seules les clés de service
-- (et le propriétaire via l'outil SQL) lisent et écrivent.
do $$
declare t text;
begin
  for t in select tablename from pg_tables where schemaname = 'public' and tablename like 'foot\_%' loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end $$;

create index if not exists foot_predictions_match_idx on foot_predictions(match_id);
create index if not exists foot_predictions_locked_idx on foot_predictions(locked_at);
create index if not exists foot_odds_match_idx on foot_odds_snapshots(match_id);
create index if not exists foot_team_news_match_idx on foot_team_news(match_id);
create index if not exists foot_combo_legs_pred_idx on foot_combo_legs(prediction_id);
create index if not exists foot_error_pred_idx on foot_error_analysis(match_id);
