-- =====================================================================
-- Addendum 2ter — paliers P1-P4, tranches, critères, routines 5 et 6.
-- Migration IDEMPOTENTE (rejouable) : uniquement des ajouts. Aucune donnée
-- supprimée, aucun sens de colonne existante modifié. Les bras A, B, C sont
-- inchangés ; les paliers vivent dans le portefeuille virtuel séparé « T ».
-- =====================================================================

-- ---------------------------------------------- colonnes ajoutées
alter table strategy_versions add column if not exists tier text;
alter table positions add column if not exists tier text;
alter table positions add column if not exists tranches jsonb;
alter table positions add column if not exists mfe_r numeric;
alter table positions add column if not exists time_to_peak_h numeric;
alter table positions add column if not exists peak_at timestamptz;
alter table positions add column if not exists lowest_price numeric;

-- Élargissement des listes de valeurs (les anciennes restent valides).
alter table strategy_versions drop constraint if exists strategy_versions_arm_check;
alter table strategy_versions add constraint strategy_versions_arm_check check (arm in ('A','B','C','T'));
alter table strategy_versions drop constraint if exists strategy_versions_status_check;
alter table strategy_versions add constraint strategy_versions_status_check
  check (status in ('explore','shadow','challenger','champion','retired'));
alter table strategy_versions drop constraint if exists strategy_versions_tier_check;
alter table strategy_versions add constraint strategy_versions_tier_check
  check (tier is null or tier in ('P1','P2','P3','P4'));
alter table positions drop constraint if exists positions_arm_check;
alter table positions add constraint positions_arm_check check (arm in ('A','B','C','T'));
alter table positions drop constraint if exists positions_tier_check;
alter table positions add constraint positions_tier_check check (tier is null or tier in ('P1','P2','P3','P4'));

-- ---------------------------------------------- tables nouvelles
create table if not exists candles (
  pair text not null,
  interval text not null,
  t timestamptz not null,
  o numeric, h numeric, l numeric, c numeric, vq numeric,
  source text,
  primary key (pair, interval, t)
);

create table if not exists signal_features (
  signal_id bigint primary key references signals(id),
  decision_ts timestamptz not null,
  pair text not null,
  features jsonb not null,                 -- calculées avec des bougies fermées avant decision_ts
  criteria jsonb,                          -- critères binaires dérivés
  outcomes jsonb,                          -- résultats par palier (ombre) et par découpe
  outcomes_complete boolean not null default false,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists shadow_trades (
  id bigint generated always as identity primary key,
  signal_id bigint references signals(id),
  tier text not null check (tier in ('P1','P2','P3','P4')),
  strategy_version_id bigint references strategy_versions(id),
  opened_at timestamptz,
  entry_price numeric,
  stop_pct numeric,
  win boolean,
  exit_reason text,
  r numeric,
  r_slip2 numeric,
  mfe_pct numeric,
  mae_pct numeric,
  hold_hours numeric,
  complete boolean not null default false,
  updated_at timestamptz default now(),
  unique (signal_id, tier)
);

create table if not exists entry_filters (
  id bigint generated always as identity primary key,
  created_at timestamptz default now(),
  tier text not null,
  criterion text not null,
  status text not null default 'hypothèse' check (status in ('hypothèse','retenu','rejeté','retiré')),
  n_with int, n_without int,
  wr_with numeric, wr_without numeric, lift numeric, lo80 numeric, hi80 numeric,
  p numeric, p_adj numeric, valid_lift numeric,
  validity text,                            -- « marche seulement si… »
  active boolean not null default false,
  unique (tier, criterion)
);

create table if not exists promotion_decisions (
  id bigint generated always as identity primary key,
  created_at timestamptz default now(),
  routine text,
  tier text,
  action text,                              -- unlock | risk_up | demote | stay_shadow | split_change | readonly_note
  detail jsonb,
  applied boolean not null default false,
  read_only boolean not null default false
);

create index if not exists candles_pair_t_idx on candles(pair, t);
create index if not exists shadow_trades_tier_idx on shadow_trades(tier);
create index if not exists positions_tier_idx on positions(tier);

alter table candles enable row level security;
alter table signal_features enable row level security;
alter table shadow_trades enable row level security;
alter table entry_filters enable row level security;
alter table promotion_decisions enable row level security;

-- ---------------------------------------------- garde-fous (extension)
-- Bras A, B, C : règles d'origine inchangées. Portefeuille T (paliers) : en plus,
-- levier <= 3x, position <= 25 % du capital, notionnel total <= 150 %,
-- liquidation estimée >= 3x plus loin que le stop.
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
  v_sd numeric;
  v_liq_dist numeric;
  v_total numeric;
  v_mmr numeric := coalesce((public.paper_cfg('maintenance_margin_rate')#>>'{}')::numeric, 0.01);
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

  -- Limites supplémentaires de l'addendum 2ter (portefeuille des paliers).
  if new.arm = 'T' then
    v_sd := (new.entry_price - new.stop_price) / new.entry_price;
    if new.leverage > 3 then
      raise exception 'GUARDRAIL 2ter: levier % > 3x', new.leverage;
    end if;
    if new.size_usd > 0.25 * v_equity * 1.0001 then
      raise exception 'GUARDRAIL 2ter: position % > 25 %% du capital', round(new.size_usd, 2);
    end if;
    select coalesce(sum(size_usd), 0) + new.size_usd into v_total
      from public.positions where arm = 'T' and status = 'open';
    if v_total > 1.5 * v_equity * 1.0001 then
      raise exception 'GUARDRAIL 2ter: notionnel total % > 150 %% du capital', round(v_total, 2);
    end if;
    v_liq_dist := 1 / new.leverage - v_mmr;
    if v_liq_dist < 3 * v_sd * 0.9999 then
      raise exception 'GUARDRAIL 2ter: liquidation à % %% < 3x la distance du stop (% %%)',
        round(v_liq_dist * 100, 1), round(v_sd * 100, 1);
    end if;
  end if;

  new.risk_usd := round(v_risk, 6);
  new.initial_stop_price := new.stop_price;
  new.highest_price := coalesce(new.highest_price, new.entry_price);
  return new;
end;
$$;

create or replace function enforce_paper_strategy() returns trigger
language plpgsql set search_path = '' as $$
begin
  if coalesce((new.params->>'max_leverage')::numeric, 0) > 10 then
    raise exception 'GUARDRAIL: levier maximum 10x';
  end if;
  if new.arm = 'A' and coalesce((new.params->>'max_leverage')::numeric, 0) > 2 then
    raise exception 'GUARDRAIL: le bras A est limité à 2x';
  end if;
  if new.arm = 'T' and coalesce((new.params->>'max_leverage')::numeric, 0) > 3 then
    raise exception 'GUARDRAIL 2ter: les paliers sont limités à 3x';
  end if;
  return new;
end;
$$;

-- ---------------------------------------------- verrous des routines (dans config)
create or replace function paper_lock_acquire(p_name text, p_holder text, p_ttl_minutes int default 45)
returns boolean language plpgsql set search_path = '' as $$
declare cur jsonb;
begin
  select value into cur from public.config where key = 'lock:' || p_name for update;
  if cur is not null and (cur->>'expires_at')::timestamptz > now() and cur->>'holder' <> p_holder then
    return false;
  end if;
  insert into public.config(key, value) values ('lock:' || p_name,
    jsonb_build_object('holder', p_holder, 'acquired_at', now(), 'expires_at', now() + make_interval(mins => p_ttl_minutes)))
  on conflict (key) do update set value = excluded.value;
  return true;
end;
$$;

create or replace function paper_lock_release(p_name text, p_holder text)
returns boolean language plpgsql set search_path = '' as $$
begin
  update public.config set value = jsonb_build_object('holder', null, 'released_at', now(), 'expires_at', now())
   where key = 'lock:' || p_name and value->>'holder' = p_holder;
  return found;
end;
$$;

-- Dernière exécution réussie d'une routine (lue par la routine 6).
create or replace function paper_last_run(p_routine text) returns jsonb
language sql stable set search_path = '' as $$
  select to_jsonb(l) from public.iteration_log l
   where l.routine = p_routine order by l.id desc limit 1;
$$;

-- ---------------------------------------------- état élargi (lecture)
create or replace function paper_state() returns jsonb
language sql stable set search_path = '' as $$
  select jsonb_build_object(
    'now', now(),
    'today_paris', (now() at time zone 'Europe/Paris')::date,
    'config', (select jsonb_object_agg(key, value) from public.config where key not like 'lock:%'),
    'hard_limits', public.paper_hard_limits(),
    'arms', (select jsonb_object_agg(a, jsonb_build_object(
        'equity', public.paper_equity(a),
        'peak_equity', public.paper_peak_equity(a),
        'drawdown', public.paper_drawdown(a),
        'n_open', (select count(*) from public.positions where arm = a and status = 'open'),
        'entries_today', (select count(*) from public.positions where arm = a
             and (opened_at at time zone 'Europe/Paris')::date = (now() at time zone 'Europe/Paris')::date),
        'active_version', (select to_jsonb(v) from public.strategy_versions v
             where v.arm = a and v.status <> 'retired' and (a <> 'T' or v.tier = 'P1')
             order by v.id desc limit 1)))
      from unnest(array['A','B','C','T']) a),
    'tier_versions', coalesce((select jsonb_agg(to_jsonb(v) order by v.tier, v.id) from public.strategy_versions v
        where v.arm = 'T' and v.status <> 'retired'), '[]'::jsonb),
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

-- Données pour les routines 5 et 6 (signaux, critères, résultats d'ombre).
create or replace function paper_tier_data() returns jsonb
language sql stable set search_path = '' as $$
  select jsonb_build_object(
    'now', now(),
    'config', (select jsonb_object_agg(key, value) from public.config where key not like 'lock:%'),
    'tier_versions', coalesce((select jsonb_agg(to_jsonb(v) order by v.id) from public.strategy_versions v where v.arm = 'T'), '[]'::jsonb),
    'signals', coalesce((select jsonb_agg(jsonb_build_object('id', s.id, 'pair', s.pair, 'detected_at', s.detected_at,
        'decision', s.decision, 'price_at_detection', s.price_at_detection, 'atr14', s.metrics->'atr14',
        'outcome_max_gain_pct', s.outcome_max_gain_pct, 'outcome_max_dd_pct', s.outcome_max_dd_pct,
        'is_reference', s.is_reference) order by s.id) from public.signals s), '[]'::jsonb),
    'features', coalesce((select jsonb_agg(to_jsonb(f) order by f.signal_id) from public.signal_features f), '[]'::jsonb),
    'shadow_trades', coalesce((select jsonb_agg(to_jsonb(t) order by t.id) from public.shadow_trades t), '[]'::jsonb),
    'tier_positions', coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from public.positions p where p.arm = 'T'), '[]'::jsonb),
    'entry_filters', coalesce((select jsonb_agg(to_jsonb(e) order by e.id) from public.entry_filters e), '[]'::jsonb),
    'last_r5', public.paper_last_run('routine5'),
    'last_r6', public.paper_last_run('routine6')
  );
$$;

create or replace function paper_record_daily(p_unrealized jsonb default '{}'::jsonb)
returns jsonb language plpgsql set search_path = '' as $$
declare
  d date := (now() at time zone 'Europe/Paris')::date;
  by_arm jsonb := '{}'::jsonb;
  a text;
  r record;
  tot_eq numeric := 0; tot_pnl numeric := 0;
  tot_open int := 0; tot_closed int := 0; tot_wins int := 0;
  eq numeric; unreal numeric;
begin
  foreach a in array array['A','B','C','T'] loop
    unreal := coalesce((p_unrealized->>a)::numeric, 0);
    eq := public.paper_equity(a) + unreal;
    select coalesce(sum(pnl_usd) filter (where status='closed'
                 and (closed_at at time zone 'Europe/Paris')::date = d), 0) as pnl,
           count(*) filter (where status='open') as n_open,
           count(*) filter (where status='closed'
                 and (closed_at at time zone 'Europe/Paris')::date = d) as n_closed,
           count(*) filter (where status='closed' and pnl_usd > 0
                 and (closed_at at time zone 'Europe/Paris')::date = d) as wins
      into r from public.positions where arm = a;
    by_arm := by_arm || jsonb_build_object(a, jsonb_build_object(
      'equity', round(eq, 2), 'realized_equity', round(public.paper_equity(a), 2),
      'unrealized', round(unreal, 2), 'pnl_usd', round(r.pnl, 2),
      'n_open', r.n_open, 'n_closed', r.n_closed, 'wins', r.wins,
      'drawdown', round(public.paper_drawdown(a), 4)));
    -- La ligne agrégée garde son sens d'origine : somme des bras A, B, C.
    if a <> 'T' then
      tot_eq := tot_eq + eq; tot_pnl := tot_pnl + r.pnl;
      tot_open := tot_open + r.n_open; tot_closed := tot_closed + r.n_closed; tot_wins := tot_wins + r.wins;
    end if;
  end loop;
  insert into public.daily_results(date, equity, pnl_usd, n_open, n_closed, wins, notes, by_arm)
  values (d, round(tot_eq, 2), round(tot_pnl, 2), tot_open, tot_closed, tot_wins,
          'equity = somme des 3 portefeuilles virtuels (A, B, C), PnL latent inclus ; paliers (T) dans by_arm ; démo uniquement', by_arm)
  on conflict (date) do update set equity = excluded.equity, pnl_usd = excluded.pnl_usd,
    n_open = excluded.n_open, n_closed = excluded.n_closed, wins = excluded.wins,
    notes = excluded.notes, by_arm = excluded.by_arm;
  return by_arm;
end;
$$;

revoke all on function paper_lock_acquire(text, text, int), paper_lock_release(text, text),
  paper_last_run(text), paper_tier_data(), paper_state(), paper_record_daily(jsonb)
  from public, anon, authenticated;

-- ---------------------------------------------- données de départ (idempotentes)
insert into strategy_versions(name, arm, tier, status, params, rationale)
select v.name, 'T', v.tier, v.status, v.params::jsonb, v.rationale
from (values
  ('T-P1-base-v1', 'P1', 'champion',
   '{"stop":{"type":"atr","mult":1.5,"period":14,"min_pct":0.08,"max_pct":0.12},"tp":{"type":"r_multiple","r":2.5},"max_leverage":3,"max_hold_days":10,"tranches":{"split":[0.5,0.3,0.2],"A":{"r":2.5},"B":{"r":6},"C":{"chandelier_atr":3,"max_hold_days":30}},"risk_pct":0.01}',
   'Palier P1 « base » : stop structurel 8-12 %, objectif 2,5 R, toujours actif (capital papier). Tranches A/B/C.'),
  ('T-P2-precision-v1', 'P2', 'shadow',
   '{"stop":{"type":"atr","mult":0.6,"period":14,"min_pct":0.03,"max_pct":0.06},"tp":{"type":"r_multiple","r":6},"max_leverage":3,"max_hold_days":10,"risk_pct":0}',
   'Palier P2 « précision » 6 R, équilibre 14 %. En ombre tant que non débloqué. Substitut d''E5 (absente) : stop structurel serré 0,6 x ATR borné 3-6 %.'),
  ('T-P3-grosse-hausse-v1', 'P3', 'shadow',
   '{"stop":{"type":"atr","mult":0.6,"period":14,"min_pct":0.03,"max_pct":0.06},"tp":{"type":"r_multiple","r":10},"max_leverage":3,"max_hold_days":30,"risk_pct":0}',
   'Palier P3 « grosse hausse » 10 R, équilibre 9 %. En ombre ; déblocage seulement avec critères validés.'),
  ('T-P4-x50-v1', 'P4', 'shadow',
   '{"stop":{"type":"atr","mult":0.6,"period":14,"min_pct":0.03,"max_pct":0.06},"tp":{"type":"r_multiple","r":50},"max_leverage":3,"max_hold_days":30,"risk_pct":0,"risk_cap":0.005}',
   'Palier P4 « x50 » coureur 50 R, équilibre 2 %, moitié de risque au plus. Évalué aussi sur la fréquence des hausses > 250 %.')
) as v(name, tier, status, params, rationale)
where not exists (select 1 from strategy_versions s where s.name = v.name);

insert into config(key, value) values
  ('tier_state', '{"P1":{"status":"unlocked","risk_pct":0.01},"P2":{"status":"shadow","risk_pct":0},"P3":{"status":"shadow","risk_pct":0},"P4":{"status":"shadow","risk_pct":0}}'),
  ('tranche_split', '{"name":"50/30/20","split":[0.5,0.3,0.2]}'),
  ('r6_readonly_until', 'null'),
  ('addendum_2ter', '{"version":1,"t_book_capital":"initial_capital_usdt","notes":"paliers en portefeuille T séparé ; bras A/B/C inchangés"}')
on conflict (key) do nothing;
