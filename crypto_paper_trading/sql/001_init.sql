-- =====================================================================
-- Paper trading crypto — migration initiale
-- DÉMO UNIQUEMENT : aucune table, fonction ou colonne ne permet d'envoyer
-- un ordre réel. Les garde-fous de GUARDRAILS.md sont aussi appliqués ici,
-- côté base, par des triggers que les routines ne peuvent pas contourner.
-- =====================================================================

-- ---------------------------------------------------------------- tables
create table strategy_versions (
  id bigint generated always as identity primary key,
  created_at timestamptz default now(),
  name text not null,
  arm text not null check (arm in ('A','B','C')),
  status text not null default 'challenger'
    check (status in ('champion','challenger','retired')),
  params jsonb not null,
  rationale text,
  parent_id bigint references strategy_versions(id)
);

create table signals (
  id bigint generated always as identity primary key,
  detected_at timestamptz default now(),
  pair text not null,
  signal_types text[] not null,
  score numeric,
  info_published_at timestamptz,
  evidence jsonb,                          -- [{url, titre, date_publication}]
  price_at_detection numeric,
  decision text check (decision in ('enter','wait','skip')),
  decision_reason text,
  data_source text,
  -- ajouts : suivi des "wait", mesure des occasions manquées et de l'avance
  alerts text[],                           -- signaux d'alerte relevés
  metrics jsonb,                           -- volume ratio, variation 24h, OI…
  signal_day_close numeric,                -- clôture du jour du signal (règle des -15 %)
  parent_signal_id bigint references signals(id), -- réévaluation d'un 'wait'
  reevaluate_after timestamptz,
  is_reference boolean not null default false,    -- historique importé (xlsx)
  rise_started_at timestamptz,             -- début de la hausse (calculé a posteriori)
  peak_at timestamptz,
  peak_price numeric,
  outcome_max_gain_pct numeric,            -- plus haut sur 10 j depuis la détection
  outcome_max_dd_pct numeric,              -- plus bas sur 10 j depuis la détection
  counterfactual jsonb,                    -- R simulé par bras, même si non entré
  outcome_computed_at timestamptz
);

create table positions (
  id bigint generated always as identity primary key,
  signal_id bigint references signals(id),
  strategy_version_id bigint references strategy_versions(id),
  pair text not null,
  side text not null default 'long' check (side = 'long'),
  opened_at timestamptz default now(),
  entry_price numeric not null check (entry_price > 0),
  size_usd numeric not null check (size_usd > 0),
  leverage numeric not null check (leverage >= 1 and leverage <= 10),
  stop_price numeric not null,
  tp_price numeric not null,
  breakeven_trigger_price numeric,
  trailing_pct numeric,
  max_hold_until timestamptz,
  status text not null default 'open' check (status in ('open','closed')),
  closed_at timestamptz,
  exit_price numeric,
  exit_reason text check (exit_reason in ('tp','sl','breakeven','trailing','time','liquidation','manual')),
  pnl_usd numeric,
  pnl_pct numeric,
  r_multiple numeric,
  fees_usd numeric,
  mfe_pct numeric,
  mae_pct numeric,
  last_checked_at timestamptz,
  -- ajouts
  arm text not null check (arm in ('A','B','C')),
  initial_stop_price numeric,
  risk_usd numeric,
  liquidation_price numeric,
  highest_price numeric,                   -- plus haut depuis l'entrée (stop suiveur)
  funding_usd numeric
);

create table price_checks (
  id bigint generated always as identity primary key,
  position_id bigint references positions(id),
  checked_at timestamptz default now(),
  last_price numeric,
  high_since_last numeric,
  low_since_last numeric,
  note text
);

create table daily_results (
  date date primary key,
  equity numeric,
  pnl_usd numeric,
  n_open int,
  n_closed int,
  wins int,
  notes text,
  by_arm jsonb                             -- même chiffres, par bras
);

create table weekly_reports (
  id bigint generated always as identity primary key,
  week_start date,
  report_md text,
  metrics jsonb,
  created_at timestamptz default now()
);

create table iteration_log (
  id bigint generated always as identity primary key,
  created_at timestamptz default now(),
  routine text,
  change jsonb,
  rationale text,
  evidence jsonb
);

create table config (
  key text primary key,
  value jsonb,
  updated_at timestamptz default now()
);

create index positions_open_idx on positions(status, arm);
create index positions_signal_idx on positions(signal_id);
create index price_checks_position_idx on price_checks(position_id);
create index signals_pair_idx on signals(pair, detected_at);
create index signals_parent_idx on signals(parent_signal_id);
create index strategy_versions_parent_idx on strategy_versions(parent_id);
create index positions_version_idx on positions(strategy_version_id);
-- Règle 3 : un même pair ne peut pas être ouvert deux fois dans le même bras.
create unique index positions_one_open_pair_per_arm
  on positions(arm, pair) where status = 'open';

-- ------------------------------------------------------------------- RLS
-- Aucune politique publique : seule la clé service / le rôle postgres
-- (utilisés par les routines via le connecteur Supabase) y accèdent.
alter table strategy_versions enable row level security;
alter table signals          enable row level security;
alter table positions        enable row level security;
alter table price_checks     enable row level security;
alter table daily_results    enable row level security;
alter table weekly_reports   enable row level security;
alter table iteration_log    enable row level security;
alter table config           enable row level security;

-- ---------------------------------------------------- limites absolues
-- Valeurs plafonds de GUARDRAILS.md, codées en dur (la table config peut
-- les rendre plus strictes, jamais plus laxistes).
create or replace function paper_hard_limits() returns jsonb
language sql immutable set search_path = '' as $$
  select jsonb_build_object(
    'risk_pct_max', 0.01,
    'leverage_max', 10,
    'max_open_per_arm', 8,
    'max_entries_per_day_per_arm', 3,
    'drawdown_halt', 0.15
  );
$$;

create or replace function paper_cfg(k text) returns jsonb
language sql stable set search_path = '' as $$
  select value from public.config where key = k;
$$;

-- Capital virtuel d'un bras = capital de départ + PnL réalisé du bras.
create or replace function paper_equity(p_arm text) returns numeric
language sql stable set search_path = '' as $$
  select (public.paper_cfg('initial_capital_usdt')#>>'{}')::numeric
       + coalesce((select sum(pnl_usd) from public.positions
                   where arm = p_arm and status = 'closed'), 0);
$$;

-- Plus haut historique du capital réalisé d'un bras.
create or replace function paper_peak_equity(p_arm text) returns numeric
language sql stable set search_path = '' as $$
  with c as (select (public.paper_cfg('initial_capital_usdt')#>>'{}')::numeric as cap),
  eq as (
    select c.cap + sum(p.pnl_usd) over (order by p.closed_at, p.id) as e
    from public.positions p, c
    where p.arm = p_arm and p.status = 'closed'
  )
  select greatest((select cap from c), coalesce((select max(e) from eq), 0));
$$;

create or replace function paper_drawdown(p_arm text) returns numeric
language sql stable set search_path = '' as $$
  select 1 - public.paper_equity(p_arm) / nullif(public.paper_peak_equity(p_arm), 0);
$$;

-- ------------------------------------------- trigger garde-fous (insert)
create or replace function enforce_paper_guardrails() returns trigger
language plpgsql set search_path = '' as $$
declare
  hl jsonb := public.paper_hard_limits();
  v_mode text := public.paper_cfg('mode')#>>'{}';
  v_equity numeric := public.paper_equity(new.arm);
  v_dd numeric := public.paper_drawdown(new.arm);
  v_risk_pct numeric := least((hl->>'risk_pct_max')::numeric,
                              coalesce((public.paper_cfg('risk_pct')#>>'{}')::numeric, 1));
  v_lev_max numeric := least((hl->>'leverage_max')::numeric,
                             coalesce((public.paper_cfg('max_leverage')#>>'{}')::numeric, 1000));
  v_max_open int := least((hl->>'max_open_per_arm')::int,
                          coalesce((public.paper_cfg('max_open_positions_per_arm')#>>'{}')::int, 1000));
  v_max_day int := least((hl->>'max_entries_per_day_per_arm')::int,
                         coalesce((public.paper_cfg('max_new_entries_per_day_per_arm')#>>'{}')::int, 1000));
  v_dd_halt numeric := least((hl->>'drawdown_halt')::numeric,
                             coalesce((public.paper_cfg('drawdown_halt_pct')#>>'{}')::numeric, 1));
  v_version public.strategy_versions%rowtype;
  v_arm_lev numeric;
  v_risk numeric;
  v_n int;
begin
  if v_mode is distinct from 'paper' then
    raise exception 'GUARDRAIL: mode=% — seul le mode paper est autorisé', v_mode;
  end if;
  if new.status <> 'open' then
    raise exception 'GUARDRAIL: une position doit être insérée ouverte';
  end if;
  if new.stop_price >= new.entry_price or new.tp_price <= new.entry_price then
    raise exception 'GUARDRAIL: long uniquement, stop < entrée < objectif';
  end if;

  select * into v_version from public.strategy_versions where id = new.strategy_version_id;
  if not found or v_version.arm <> new.arm or v_version.status = 'retired' then
    raise exception 'GUARDRAIL: version de stratégie absente, retirée ou d''un autre bras';
  end if;

  v_arm_lev := least(v_lev_max, coalesce((v_version.params->>'max_leverage')::numeric, v_lev_max));
  if new.leverage > v_arm_lev then
    raise exception 'GUARDRAIL: levier % > maximum % (bras %)', new.leverage, v_arm_lev, new.arm;
  end if;
  if new.size_usd > v_lev_max * v_equity then
    raise exception 'GUARDRAIL: notionnel % > levier max x capital', new.size_usd;
  end if;

  v_risk := new.size_usd * (new.entry_price - new.stop_price) / new.entry_price;
  if v_risk > v_risk_pct * v_equity * 1.0001 then
    raise exception 'GUARDRAIL: risque % USDT > % %% du capital (% USDT)',
      round(v_risk, 2), v_risk_pct * 100, round(v_equity, 2);
  end if;

  if v_dd > v_dd_halt then
    raise exception 'GUARDRAIL: drawdown du bras % = % %% > % %% — entrées suspendues',
      new.arm, round(v_dd * 100, 1), v_dd_halt * 100;
  end if;

  select count(*) into v_n from public.positions where arm = new.arm and status = 'open';
  if v_n >= v_max_open then
    raise exception 'GUARDRAIL: déjà % positions ouvertes dans le bras %', v_n, new.arm;
  end if;

  select count(*) into v_n from public.positions
   where arm = new.arm
     and (opened_at at time zone 'Europe/Paris')::date
         = (coalesce(new.opened_at, now()) at time zone 'Europe/Paris')::date;
  if v_n >= v_max_day then
    raise exception 'GUARDRAIL: déjà % nouvelles entrées aujourd''hui dans le bras %', v_n, new.arm;
  end if;

  new.risk_usd := round(v_risk, 6);
  new.initial_stop_price := new.stop_price;
  new.highest_price := coalesce(new.highest_price, new.entry_price);
  return new;
end;
$$;

create trigger positions_guardrails_insert
  before insert on positions
  for each row execute function enforce_paper_guardrails();

-- ----------------------------------- trigger garde-fous (mise à jour)
-- Les paramètres d'entrée sont immuables ; un stop ne peut que monter.
create or replace function enforce_paper_position_update() returns trigger
language plpgsql set search_path = '' as $$
begin
  if new.entry_price <> old.entry_price or new.size_usd <> old.size_usd
     or new.leverage <> old.leverage or new.arm <> old.arm or new.pair <> old.pair
     or new.opened_at <> old.opened_at
     or new.initial_stop_price is distinct from old.initial_stop_price
     or new.risk_usd is distinct from old.risk_usd then
    raise exception 'GUARDRAIL: les paramètres d''entrée d''une position sont immuables';
  end if;
  if old.status = 'closed' and new.status = 'open' then
    raise exception 'GUARDRAIL: une position fermée ne peut pas être rouverte';
  end if;
  if new.stop_price < old.stop_price then
    raise exception 'GUARDRAIL: un stop ne peut être que remonté (% -> %)', old.stop_price, new.stop_price;
  end if;
  return new;
end;
$$;

create trigger positions_guardrails_update
  before update on positions
  for each row execute function enforce_paper_position_update();

-- ------------------------------------------- protection de la config
create or replace function enforce_paper_config() returns trigger
language plpgsql set search_path = '' as $$
declare
  hl jsonb := public.paper_hard_limits();
  v numeric;
begin
  if tg_op = 'DELETE' then
    raise exception 'GUARDRAIL: suppression de config interdite';
  end if;
  new.updated_at := now();
  if new.key = 'mode' and new.value #>> '{}' <> 'paper' then
    raise exception 'GUARDRAIL: le mode ne peut être que paper';
  end if;
  if new.key in ('risk_pct','max_leverage','max_open_positions_per_arm',
                 'max_new_entries_per_day_per_arm','drawdown_halt_pct') then
    v := (new.value #>> '{}')::numeric;
    if (new.key = 'risk_pct' and v > (hl->>'risk_pct_max')::numeric)
       or (new.key = 'max_leverage' and v > (hl->>'leverage_max')::numeric)
       or (new.key = 'max_open_positions_per_arm' and v > (hl->>'max_open_per_arm')::numeric)
       or (new.key = 'max_new_entries_per_day_per_arm' and v > (hl->>'max_entries_per_day_per_arm')::numeric)
       or (new.key = 'drawdown_halt_pct' and v > (hl->>'drawdown_halt')::numeric) then
      raise exception 'GUARDRAIL: % = % dépasse la limite de GUARDRAILS.md', new.key, v;
    end if;
  end if;
  return new;
end;
$$;

create trigger config_guardrails
  before insert or update or delete on config
  for each row execute function enforce_paper_config();

-- Limite de levier par version de stratégie (et jamais de levier > 10).
create or replace function enforce_paper_strategy() returns trigger
language plpgsql set search_path = '' as $$
begin
  if coalesce((new.params->>'max_leverage')::numeric, 0) > 10 then
    raise exception 'GUARDRAIL: levier maximum 10x';
  end if;
  if new.arm = 'A' and coalesce((new.params->>'max_leverage')::numeric, 0) > 2 then
    raise exception 'GUARDRAIL: le bras A est limité à 2x';
  end if;
  return new;
end;
$$;

create trigger strategy_guardrails
  before insert or update on strategy_versions
  for each row execute function enforce_paper_strategy();

-- ------------------------------------ état compact pour les routines
-- Une seule requête renvoie tout ce qu'une routine sans mémoire doit savoir.
create or replace function paper_state() returns jsonb
language sql stable set search_path = '' as $$
  select jsonb_build_object(
    'now', now(),
    'today_paris', (now() at time zone 'Europe/Paris')::date,
    'config', (select jsonb_object_agg(key, value) from public.config),
    'hard_limits', public.paper_hard_limits(),
    'arms', (select jsonb_object_agg(a, jsonb_build_object(
        'equity', public.paper_equity(a),
        'peak_equity', public.paper_peak_equity(a),
        'drawdown', public.paper_drawdown(a),
        'n_open', (select count(*) from public.positions where arm = a and status = 'open'),
        'entries_today', (select count(*) from public.positions where arm = a
             and (opened_at at time zone 'Europe/Paris')::date = (now() at time zone 'Europe/Paris')::date),
        'active_version', (select to_jsonb(v) from public.strategy_versions v
             where v.arm = a and v.status <> 'retired' order by v.id desc limit 1)))
      from unnest(array['A','B','C']) a),
    'open_positions', coalesce((select jsonb_agg(to_jsonb(p) order by p.id)
        from public.positions p where p.status = 'open'), '[]'::jsonb),
    'pending_waits', coalesce((select jsonb_agg(to_jsonb(s) order by s.id)
        from public.signals s where s.decision = 'wait'
          and s.detected_at > now() - interval '3 days'
          and not exists (select 1 from public.signals c where c.parent_signal_id = s.id)), '[]'::jsonb),
    'recent_signals', coalesce((select jsonb_agg(jsonb_build_object('id', id, 'pair', pair,
          'detected_at', detected_at, 'decision', decision) order by id)
        from public.signals where detected_at > now() - interval '14 days'), '[]'::jsonb)
  );
$$;

-- Historique complet pour l'adaptation et le rapport.
create or replace function paper_history() returns jsonb
language sql stable set search_path = '' as $$
  select jsonb_build_object(
    'now', now(),
    'config', (select jsonb_object_agg(key, value) from public.config),
    'versions', coalesce((select jsonb_agg(to_jsonb(v) order by v.id) from public.strategy_versions v), '[]'::jsonb),
    'positions', coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from public.positions p), '[]'::jsonb),
    'signals', coalesce((select jsonb_agg(to_jsonb(s) - 'evidence' order by s.id) from public.signals s), '[]'::jsonb),
    'iteration_log', coalesce((select jsonb_agg(to_jsonb(l) order by l.id)
        from (select * from public.iteration_log order by id desc limit 200) l), '[]'::jsonb),
    'daily_results', coalesce((select jsonb_agg(to_jsonb(d) order by d.date) from public.daily_results d), '[]'::jsonb)
  );
$$;

revoke all on function paper_state(), paper_history() from public, anon, authenticated;
