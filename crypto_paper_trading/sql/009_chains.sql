-- 009 : routine 7 « chaînes de victoires » (PAPIER UNIQUEMENT). Idempotent.
-- Ajouts seulement : nouvelles tables, deux colonnes de positions (chain_id, chain_step),
-- portefeuille virtuel « K » (1 000 USDT) ; les règles des bras A, B, C et du portefeuille T
-- sont recopiées à l'identique dans les fonctions étendues ci-dessous.

alter table public.positions add column if not exists chain_id bigint;
alter table public.positions add column if not exists chain_step int;

alter table public.positions drop constraint if exists positions_arm_check;
alter table public.positions add constraint positions_arm_check check (arm in ('A','B','C','T','K'));
alter table public.strategy_versions drop constraint if exists strategy_versions_arm_check;
alter table public.strategy_versions add constraint strategy_versions_arm_check check (arm in ('A','B','C','T','K'));

create table if not exists public.chain_params (
  id bigint generated always as identity primary key,
  parent_id bigint references public.chain_params(id),
  name text not null unique,
  params jsonb not null,               -- longueur, stops et objectif par niveau, R, part réinvestie, levier,
                                       -- seuils par niveau, option attendre/sécuriser/réinitialiser, part encaissée
  status text not null default 'ombre' check (status in ('explore','ombre','challenger','champion','restreint',
                                                          'pause','retiré','inconclusif')),
  reason text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists public.chains (
  id bigint generated always as identity primary key,
  params_id bigint not null references public.chain_params(id),
  source text not null check (source in ('live_paper','shadow','replay_history','monte_carlo')),
  state text not null default 'ouverte' check (state in ('ouverte','réussie','échouée','sécurisée')),
  level int not null default 0,        -- victoires acquises
  gate_level int not null default 0,   -- niveau utilisé pour le seuil (option « réinitialiser »)
  risk_initial numeric,
  house numeric not null default 0,    -- gain en jeu pour l'étape suivante
  gains numeric not null default 0,    -- bilan cumulé de la chaîne
  bank numeric not null default 0,     -- gains encaissés
  started_at timestamptz default now(),
  ended_at timestamptz,
  end_reason text,
  detail jsonb
);
create index if not exists chains_state_idx on public.chains(source, state);

create table if not exists public.chain_steps (
  id bigint generated always as identity primary key,
  chain_id bigint not null references public.chains(id),
  k int not null check (k between 1 and 10),
  signal_id bigint references public.signals(id),
  position_id bigint references public.positions(id),
  pair text,
  score numeric, gate numeric,
  entry numeric, stop numeric, target numeric, stop_pct numeric, r_mult numeric,
  risk numeric, size numeric, leverage numeric, vol_24h numeric,
  regime text,
  outcome text check (outcome in ('ouverte','victoire','perte','sortie_temps')),
  result_r numeric, pnl numeric, slippage numeric,
  decided_at timestamptz default now(),
  closed_at timestamptz,
  reason text,
  unique (chain_id, k)
);

create table if not exists public.chain_gating (
  id bigint generated always as identity primary key,
  params_id bigint not null references public.chain_params(id),
  k int not null,
  min_score numeric not null,
  max_wait_days numeric,
  history jsonb not null default '[]'::jsonb,
  updated_at timestamptz default now(),
  unique (params_id, k)
);

create table if not exists public.chain_decisions (
  id bigint generated always as identity primary key,
  created_at timestamptz default now(),
  routine text not null default 'routine7',
  chain_id bigint,
  params_id bigint,
  action text not null,                -- entrer | attendre | sécuriser | réinitialiser | changer_seuil |
                                       -- étape_close | lecture_seule | non_exécutée | ...
  read_only boolean not null default false,
  logic text,                          -- la logique en clair
  numbers jsonb                        -- les chiffres qui ont motivé la décision
);

create table if not exists public.chain_sim_runs (
  id bigint generated always as identity primary key,
  created_at timestamptz default now(),
  source text not null check (source in ('shadow','replay_history','monte_carlo','live_paper')),
  params_id bigint references public.chain_params(id),
  variant text,
  n_chains int,
  p_full numeric, p_full_lo80 numeric, p_full_hi80 numeric,
  ev_chain_r numeric, ev_chain_r_slip2 numeric,
  period_start timestamptz, period_end timestamptz,
  detail jsonb
);

create table if not exists public.chain_stats (
  id bigint generated always as identity primary key,
  day date not null default ((now() at time zone 'Europe/Paris')::date),
  params_id bigint references public.chain_params(id),
  variant text,
  source text,
  n_done int, reach jsonb, p_levels jsonb, p_full numeric, trend text,
  detail jsonb,
  unique (day, variant, source)
);

alter table public.chain_params enable row level security;
alter table public.chains enable row level security;
alter table public.chain_steps enable row level security;
alter table public.chain_gating enable row level security;
alter table public.chain_decisions enable row level security;
alter table public.chain_sim_runs enable row level security;
alter table public.chain_stats enable row level security;

-- --------------------------------------------- drawdown global (tous portefeuilles)
create or replace function public.paper_global_drawdown() returns numeric
language sql stable set search_path = '' as $$
  select 1 - sum(public.paper_equity(a) + public.paper_unrealized(a)) / nullif(sum(public.paper_peak_equity(a)), 0)
    from unnest(array['A','B','C','T','K']) a;
$$;

-- --------------------------------------------- garde-fous d'une position de chaîne (GUARDRAILS 10)
create or replace function public.enforce_chain_position(p public.positions) returns void
language plpgsql set search_path = '' as $$
declare
  c public.chains%rowtype;
  prm jsonb;
  st public.chain_steps%rowtype;
  prev public.chain_steps%rowtype;
  v_sd numeric := (p.entry_price - p.stop_price) / p.entry_price;
  v_tp numeric := (p.tp_price - p.entry_price) / p.entry_price;
  v_risk numeric := p.size_usd * (p.entry_price - p.stop_price) / p.entry_price;
  v_eq numeric := public.paper_equity('K');
  v_lev_max numeric := least(3, coalesce((public.paper_cfg('chain_max_leverage')#>>'{}')::numeric, 3));
  v_slip numeric := coalesce((public.paper_cfg('slippage_pct')#>>'{}')::numeric, 0.001);
  v_mmr numeric := coalesce((public.paper_cfg('maintenance_margin_rate')#>>'{}')::numeric, 0.01);
  v_ro timestamptz := (public.paper_cfg('chain_readonly_until')#>>'{}')::timestamptz;
  v_n int;
begin
  if p.chain_id is null or p.chain_step is null then
    raise exception 'GUARDRAIL 7: une position K doit appartenir à une chaîne (chain_id, chain_step)';
  end if;
  if v_ro is not null and now() < v_ro then
    raise exception 'GUARDRAIL 7: routine 7 en lecture seule jusqu''au %', v_ro;
  end if;
  select * into c from public.chains where id = p.chain_id;
  if not found or c.state <> 'ouverte' or c.source <> 'live_paper' then
    raise exception 'GUARDRAIL 7: chaîne % absente, terminée ou non « papier réel »', p.chain_id;
  end if;
  select params into prm from public.chain_params where id = c.params_id;
  if v_sd > 0.15 + 1e-9 then
    raise exception 'GUARDRAIL 7: stop % %% > 15 %%', round(v_sd * 100, 2);
  end if;
  if abs(v_tp - v_sd * (prm->>'r_mult')::numeric) > 0.01 * v_tp then
    raise exception 'GUARDRAIL 7: objectif % %% ≠ % x stop', round(v_tp * 100, 2), prm->>'r_mult';
  end if;
  if p.chain_step = 1 then
    if v_risk > 0.01 * v_eq * 1.0001 then
      raise exception 'GUARDRAIL 7: étape 1 : risque % > 1 %% du capital (%)', round(v_risk, 2), round(v_eq, 2);
    end if;
  else
    select * into prev from public.chain_steps where chain_id = p.chain_id and k = p.chain_step - 1;
    if not found or prev.outcome <> 'victoire' then
      raise exception 'GUARDRAIL 7: l''étape % n''a pas été gagnée', p.chain_step - 1;
    end if;
    if v_risk > coalesce(prev.pnl, 0) * 1.0001 then
      raise exception 'GUARDRAIL 7: risque % > gain de l''étape précédente (%)', round(v_risk, 2), round(prev.pnl, 2);
    end if;
  end if;
  if p.leverage > v_lev_max or p.size_usd > v_lev_max * v_eq * 1.0001 then
    raise exception 'GUARDRAIL 7: levier > %x', v_lev_max;
  end if;
  if 1 / greatest(p.leverage, p.size_usd / v_eq) - v_mmr < 2 * (v_sd + v_slip) * 0.9999 then
    raise exception 'GUARDRAIL 7: liquidation à moins de 2 fois la distance du stop';
  end if;
  select * into st from public.chain_steps where chain_id = p.chain_id and k = p.chain_step;
  if not found or st.vol_24h is null or p.size_usd > 0.001 * st.vol_24h * 1.0001 then
    raise exception 'GUARDRAIL 7: position > 0,1 %% du volume 24 h (ou volume inconnu)';
  end if;
  select count(*) into v_n from public.positions where arm = 'K' and status = 'open' and chain_id = p.chain_id;
  if v_n > 0 then
    raise exception 'GUARDRAIL 7: une seule position par chaîne';
  end if;
  select count(*) into v_n from public.positions where arm = 'K' and status = 'open' and pair = p.pair;
  if v_n > 0 then
    raise exception 'GUARDRAIL 7: % déjà ouvert dans les chaînes (pas de moyenne à la baisse)', p.pair;
  end if;
  if public.paper_global_drawdown() >= 0.15 then
    raise exception 'GUARDRAIL 7: drawdown global % %% >= 15 %% — routine 7 suspendue',
      round(public.paper_global_drawdown() * 100, 1);
  end if;
end;
$$;

-- au plus 3 chaînes « papier réel » ouvertes
create or replace function public.enforce_chain_open() returns trigger
language plpgsql set search_path = '' as $$
declare v_n int;
begin
  if new.source = 'live_paper' and new.state = 'ouverte' and (tg_op = 'INSERT' or old.state <> 'ouverte') then
    select count(*) into v_n from public.chains where source = 'live_paper' and state = 'ouverte';
    if v_n >= 3 then
      raise exception 'GUARDRAIL 7: déjà 3 chaînes ouvertes';
    end if;
  end if;
  return new;
end;
$$;
drop trigger if exists chains_guardrails on public.chains;
create trigger chains_guardrails before insert or update on public.chains
  for each row execute function public.enforce_chain_open();

-- clôture d'une position de chaîne (routine 2) -> étape et chaîne mises à jour
create or replace function public.chain_on_position_close() returns trigger
language plpgsql set search_path = '' as $$
declare
  c public.chains%rowtype;
  prm jsonb;
  win boolean := new.exit_reason = 'tp';
  n int;
  reinv numeric;
begin
  if new.chain_id is null or old.status <> 'open' or new.status <> 'closed' then
    return new;
  end if;
  select * into c from public.chains where id = new.chain_id for update;
  select params into prm from public.chain_params where id = c.params_id;
  n := coalesce((prm->>'chain_len')::int, 5);
  reinv := coalesce((prm->>'reinvest')::numeric, 1);
  update public.chain_steps set outcome = case when win then 'victoire'
                                               when new.exit_reason = 'time' then 'sortie_temps' else 'perte' end,
         result_r = new.r_multiple, pnl = new.pnl_usd, closed_at = new.closed_at
   where chain_id = new.chain_id and k = new.chain_step;
  if win then
    update public.chains set level = new.chain_step, gate_level = gate_level + 1,
           gains = gains + new.pnl_usd, house = new.pnl_usd * reinv,
           bank = bank + new.pnl_usd * (1 - reinv),
           state = case when new.chain_step >= n then 'réussie' else 'ouverte' end,
           ended_at = case when new.chain_step >= n then new.closed_at end,
           end_reason = case when new.chain_step >= n then n || ' victoires : gain encaissé' end
     where id = new.chain_id;
    update public.chains set bank = gains, house = 0 where id = new.chain_id and state = 'réussie';
  else
    update public.chains set gains = gains + new.pnl_usd, house = 0, bank = gains + new.pnl_usd,
           state = 'échouée', ended_at = new.closed_at,
           end_reason = 'étape ' || new.chain_step || ' : ' || new.exit_reason
     where id = new.chain_id;
  end if;
  insert into public.chain_decisions(chain_id, params_id, action, logic, numbers)
  values (new.chain_id, c.params_id, 'étape_close',
          'Étape ' || new.chain_step || case when win then ' gagnée (objectif touché)' else ' perdue (' || new.exit_reason || ')' end,
          jsonb_build_object('position_id', new.id, 'pnl', new.pnl_usd, 'r', new.r_multiple, 'pair', new.pair));
  return new;
end;
$$;
drop trigger if exists positions_chain_close on public.positions;
create trigger positions_chain_close after update on public.positions
  for each row execute function public.chain_on_position_close();

-- données de la routine 7 (et de la section « chaînes » du rapport)
create or replace function public.paper_chain_data() returns jsonb
language sql stable set search_path = '' as $$
  select jsonb_build_object(
    'now', now(),
    'config', (select jsonb_object_agg(key, value) from public.config where key not like 'lock:%'),
    'params', coalesce((select jsonb_agg(to_jsonb(x) order by x.id) from public.chain_params x), '[]'::jsonb),
    'gating', coalesce((select jsonb_agg(to_jsonb(x) order by x.params_id, x.k) from public.chain_gating x), '[]'::jsonb),
    'chains', coalesce((select jsonb_agg(to_jsonb(x) order by x.id) from public.chains x
                         where x.source = 'live_paper' or x.started_at > now() - interval '35 days'), '[]'::jsonb),
    'steps', coalesce((select jsonb_agg(to_jsonb(x) order by x.id) from public.chain_steps x
                        join public.chains c on c.id = x.chain_id
                        where c.source = 'live_paper' or c.started_at > now() - interval '35 days'), '[]'::jsonb),
    'open_k', coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from public.positions p
                         where p.arm = 'K' and p.status = 'open'), '[]'::jsonb),
    'signals', coalesce((select jsonb_agg(jsonb_build_object('id', s.id, 'pair', s.pair, 'detected_at', s.detected_at,
                           'decision', s.decision, 'score', s.score, 'price_at_detection', s.price_at_detection,
                           'atr14', s.metrics->'atr14', 'quote_vol_24h', s.metrics->'quote_vol_24h',
                           'signal_types', s.signal_types, 'criteria', f.criteria, 'is_reference', s.is_reference,
                           'alerts', s.alerts, 'decision_reason', s.decision_reason)
                           order by s.id)
                         from public.signals s left join public.signal_features f on f.signal_id = s.id
                         where s.detected_at > now() - interval '60 days'), '[]'::jsonb),
    'entry_filters', coalesce((select jsonb_agg(to_jsonb(x)) from public.entry_filters x where x.status = 'retenu'), '[]'::jsonb),
    'sim_runs', coalesce((select jsonb_agg(to_jsonb(x) order by x.id) from (select * from public.chain_sim_runs
                           order by id desc limit 200) x), '[]'::jsonb),
    'stats', coalesce((select jsonb_agg(to_jsonb(x) order by x.id) from public.chain_stats x
                        where x.day > (now() - interval '35 days')::date), '[]'::jsonb),
    'decisions', coalesce((select jsonb_agg(to_jsonb(x) order by x.id) from (select * from public.chain_decisions
                            order by id desc limit 200) x), '[]'::jsonb),
    'routine_log', coalesce((select jsonb_agg(jsonb_build_object('routine', l.routine, 'change', l.change,
                              'created_at', l.created_at) order by l.id)
                            from public.iteration_log l where l.created_at > now() - interval '2 days'
                              and l.routine in ('routine5','routine6','routine7')), '[]'::jsonb),
    'global_drawdown', public.paper_global_drawdown(),
    'k_equity', public.paper_equity('K')
  );
$$;

-- --------------------------------------------- fonctions étendues (A/B/C/T inchangés, K ajouté)
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

  -- Routine 7 (chaînes de victoires, GUARDRAILS section 10) : règles propres au portefeuille K.
  if new.arm = 'K' then
    perform public.enforce_chain_position(new);
    v_risk := new.size_usd * (new.entry_price - new.stop_price) / new.entry_price;
    new.risk_usd := round(v_risk, 6);
    new.initial_stop_price := new.stop_price;
    new.highest_price := coalesce(new.highest_price, new.entry_price);
    return new;
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
  if new.arm = 'K' and coalesce((new.params->>'max_leverage')::numeric, 0) > 3 then
    raise exception 'GUARDRAIL 7: les chaînes en papier sont limitées à 3x (5x et 7x : ombre seulement)';
  end if;
  return new;
end;
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
  foreach a in array array['A','B','C','T','K'] loop
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
    if a not in ('T', 'K') then
      tot_eq := tot_eq + eq; tot_pnl := tot_pnl + r.pnl;
      tot_open := tot_open + r.n_open; tot_closed := tot_closed + r.n_closed; tot_wins := tot_wins + r.wins;
    end if;
  end loop;
  insert into public.daily_results(date, equity, pnl_usd, n_open, n_closed, wins, notes, by_arm)
  values (d, round(tot_eq, 2), round(tot_pnl, 2), tot_open, tot_closed, tot_wins,
          'equity = somme des 3 portefeuilles virtuels (A, B, C), PnL latent inclus ; paliers (T) et chaînes (K) dans by_arm ; démo uniquement', by_arm)
  on conflict (date) do update set equity = excluded.equity, pnl_usd = excluded.pnl_usd,
    n_open = excluded.n_open, n_closed = excluded.n_closed, wins = excluded.wins,
    notes = excluded.notes, by_arm = excluded.by_arm;
  return by_arm;
end;
$$;

create or replace function public.paper_set_marks(p jsonb) returns jsonb
language plpgsql set search_path = '' as $$
declare
  a text;
  pos jsonb;
  eq numeric;
begin
  foreach a in array array['A','B','C','T','K'] loop
    select coalesce(jsonb_object_agg(m.key, round(m.value::numeric, 4)), '{}'::jsonb) into pos
      from jsonb_each_text(coalesce((select positions from public.arm_marks where arm = a), '{}'::jsonb)
                           || coalesce(p->a, '{}'::jsonb)) m
      join public.positions x on x.id = m.key::bigint and x.arm = a and x.status = 'open';
    insert into public.arm_marks(arm, marked_at, positions) values (a, now(), pos)
      on conflict (arm) do update set marked_at = now(), positions = excluded.positions;
    eq := public.paper_equity(a) + public.paper_unrealized(a);
    update public.arm_marks set peak_equity = greatest(coalesce(peak_equity, 0), eq) where arm = a;
  end loop;
  return (select jsonb_object_agg(arm, jsonb_build_object(
            'unrealized', round(public.paper_unrealized(arm), 2),
            'drawdown', round(public.paper_drawdown(arm), 4)))
            from public.arm_marks);
end;
$$;

-- --------------------------------------------- données initiales
insert into public.chain_params(name, params, status, reason) values ('utilisateur_5x3R', '{"name": "utilisateur_5x3R", "chain_len": 5, "stops": [0.1, 0.05, 0.05, 0.05, 0.05], "r_mult": 3, "reinvest": 1.0, "max_leverage": 3.0, "gating": [3, 3, 4, 5, 5], "option": "wait", "wait_days": null, "cash_share": 0.5, "risk_pct": 0.01, "max_open_chains": 3, "max_hold_days": 10}'::jsonb, 'champion', 'modèle de l''utilisateur : variante de départ (pas une vérité), seule à ouvrir des chaînes en papier réel après 7 jours de lecture seule') on conflict (name) do nothing;
insert into public.chain_params(name, params, status, reason) values ('chaine_3', '{"name": "chaine_3", "chain_len": 3, "stops": [0.1, 0.05, 0.05], "r_mult": 3, "reinvest": 1.0, "max_leverage": 3.0, "gating": [3, 3, 4], "option": "wait", "wait_days": null, "cash_share": 0.5, "risk_pct": 0.01, "max_open_chains": 3, "max_hold_days": 10}'::jsonb, 'ombre', 'variante comparée en ombre') on conflict (name) do nothing;
insert into public.chain_params(name, params, status, reason) values ('R2', '{"name": "R2", "chain_len": 5, "stops": [0.1, 0.05, 0.05, 0.05, 0.05], "r_mult": 2, "reinvest": 1.0, "max_leverage": 3.0, "gating": [3, 3, 4, 5, 5], "option": "wait", "wait_days": null, "cash_share": 0.5, "risk_pct": 0.01, "max_open_chains": 3, "max_hold_days": 10}'::jsonb, 'ombre', 'variante comparée en ombre') on conflict (name) do nothing;
insert into public.chain_params(name, params, status, reason) values ('R4', '{"name": "R4", "chain_len": 5, "stops": [0.1, 0.05, 0.05, 0.05, 0.05], "r_mult": 4, "reinvest": 1.0, "max_leverage": 3.0, "gating": [3, 3, 4, 5, 5], "option": "wait", "wait_days": null, "cash_share": 0.5, "risk_pct": 0.01, "max_open_chains": 3, "max_hold_days": 10}'::jsonb, 'ombre', 'variante comparée en ombre') on conflict (name) do nothing;
insert into public.chain_params(name, params, status, reason) values ('R5', '{"name": "R5", "chain_len": 5, "stops": [0.1, 0.05, 0.05, 0.05, 0.05], "r_mult": 5, "reinvest": 1.0, "max_leverage": 3.0, "gating": [3, 3, 4, 5, 5], "option": "wait", "wait_days": null, "cash_share": 0.5, "risk_pct": 0.01, "max_open_chains": 3, "max_hold_days": 10}'::jsonb, 'ombre', 'variante comparée en ombre') on conflict (name) do nothing;
insert into public.chain_params(name, params, status, reason) values ('stop10_constant', '{"name": "stop10_constant", "chain_len": 5, "stops": [0.1, 0.1, 0.1, 0.1, 0.1], "r_mult": 3, "reinvest": 1.0, "max_leverage": 3.0, "gating": [3, 3, 4, 5, 5], "option": "wait", "wait_days": null, "cash_share": 0.5, "risk_pct": 0.01, "max_open_chains": 3, "max_hold_days": 10}'::jsonb, 'ombre', 'variante comparée en ombre') on conflict (name) do nothing;
insert into public.chain_params(name, params, status, reason) values ('stop5_constant', '{"name": "stop5_constant", "chain_len": 5, "stops": [0.05, 0.05, 0.05, 0.05, 0.05], "r_mult": 3, "reinvest": 1.0, "max_leverage": 3.0, "gating": [3, 3, 4, 5, 5], "option": "wait", "wait_days": null, "cash_share": 0.5, "risk_pct": 0.01, "max_open_chains": 3, "max_hold_days": 10}'::jsonb, 'ombre', 'variante comparée en ombre') on conflict (name) do nothing;
insert into public.chain_params(name, params, status, reason) values ('stop15_45pc', '{"name": "stop15_45pc", "chain_len": 5, "stops": [0.15, 0.15, 0.15, 0.15, 0.15], "r_mult": 3, "reinvest": 1.0, "max_leverage": 3.0, "gating": [3, 3, 4, 5, 5], "option": "wait", "wait_days": null, "cash_share": 0.5, "risk_pct": 0.01, "max_open_chains": 3, "max_hold_days": 10}'::jsonb, 'ombre', 'variante comparée en ombre') on conflict (name) do nothing;
insert into public.chain_params(name, params, status, reason) values ('reinvest_75', '{"name": "reinvest_75", "chain_len": 5, "stops": [0.1, 0.05, 0.05, 0.05, 0.05], "r_mult": 3, "reinvest": 0.75, "max_leverage": 3.0, "gating": [3, 3, 4, 5, 5], "option": "wait", "wait_days": null, "cash_share": 0.5, "risk_pct": 0.01, "max_open_chains": 3, "max_hold_days": 10}'::jsonb, 'ombre', 'variante comparée en ombre') on conflict (name) do nothing;
insert into public.chain_params(name, params, status, reason) values ('reinvest_50', '{"name": "reinvest_50", "chain_len": 5, "stops": [0.1, 0.05, 0.05, 0.05, 0.05], "r_mult": 3, "reinvest": 0.5, "max_leverage": 3.0, "gating": [3, 3, 4, 5, 5], "option": "wait", "wait_days": null, "cash_share": 0.5, "risk_pct": 0.01, "max_open_chains": 3, "max_hold_days": 10}'::jsonb, 'ombre', 'variante comparée en ombre') on conflict (name) do nothing;
insert into public.chain_params(name, params, status, reason) values ('securiser_3j', '{"name": "securiser_3j", "chain_len": 5, "stops": [0.1, 0.05, 0.05, 0.05, 0.05], "r_mult": 3, "reinvest": 1.0, "max_leverage": 3.0, "gating": [3, 3, 4, 5, 5], "option": "secure", "wait_days": 3, "cash_share": 0.5, "risk_pct": 0.01, "max_open_chains": 3, "max_hold_days": 10}'::jsonb, 'ombre', 'variante comparée en ombre') on conflict (name) do nothing;
insert into public.chain_params(name, params, status, reason) values ('reinitialiser_50', '{"name": "reinitialiser_50", "chain_len": 5, "stops": [0.1, 0.05, 0.05, 0.05, 0.05], "r_mult": 3, "reinvest": 1.0, "max_leverage": 3.0, "gating": [3, 3, 4, 5, 5], "option": "reset", "wait_days": 3, "cash_share": 0.5, "risk_pct": 0.01, "max_open_chains": 3, "max_hold_days": 10}'::jsonb, 'ombre', 'variante comparée en ombre') on conflict (name) do nothing;
insert into public.chain_params(name, params, status, reason) values ('seuils_plats_3', '{"name": "seuils_plats_3", "chain_len": 5, "stops": [0.1, 0.05, 0.05, 0.05, 0.05], "r_mult": 3, "reinvest": 1.0, "max_leverage": 3.0, "gating": [3, 3, 3, 3, 3], "option": "wait", "wait_days": null, "cash_share": 0.5, "risk_pct": 0.01, "max_open_chains": 3, "max_hold_days": 10}'::jsonb, 'ombre', 'variante comparée en ombre') on conflict (name) do nothing;
insert into public.chain_params(name, params, status, reason) values ('seuils_stricts', '{"name": "seuils_stricts", "chain_len": 5, "stops": [0.1, 0.05, 0.05, 0.05, 0.05], "r_mult": 3, "reinvest": 1.0, "max_leverage": 3.0, "gating": [4, 4, 5, 6, 6], "option": "wait", "wait_days": null, "cash_share": 0.5, "risk_pct": 0.01, "max_open_chains": 3, "max_hold_days": 10}'::jsonb, 'ombre', 'variante comparée en ombre') on conflict (name) do nothing;
insert into public.chain_params(name, params, status, reason) values ('levier_5x_ombre', '{"name": "levier_5x_ombre", "chain_len": 5, "stops": [0.1, 0.05, 0.05, 0.05, 0.05], "r_mult": 3, "reinvest": 1.0, "max_leverage": 5.0, "gating": [3, 3, 4, 5, 5], "option": "wait", "wait_days": null, "cash_share": 0.5, "risk_pct": 0.01, "max_open_chains": 3, "max_hold_days": 10}'::jsonb, 'ombre', 'levier > 3x : ombre seulement tant que non validé') on conflict (name) do nothing;
insert into public.chain_params(name, params, status, reason) values ('levier_7x_ombre', '{"name": "levier_7x_ombre", "chain_len": 5, "stops": [0.1, 0.05, 0.05, 0.05, 0.05], "r_mult": 3, "reinvest": 1.0, "max_leverage": 7.0, "gating": [3, 3, 4, 5, 5], "option": "wait", "wait_days": null, "cash_share": 0.5, "risk_pct": 0.01, "max_open_chains": 3, "max_hold_days": 10}'::jsonb, 'ombre', 'levier > 3x : ombre seulement tant que non validé') on conflict (name) do nothing;

insert into public.chain_gating(params_id, k, min_score, max_wait_days)
select cp.id, g.k, (cp.params->'gating'->>(g.k - 1))::numeric, (cp.params->>'wait_days')::numeric
  from public.chain_params cp
  cross join lateral generate_series(1, (cp.params->>'chain_len')::int) as g(k)
on conflict (params_id, k) do nothing;

insert into public.strategy_versions(name, arm, params, status, rationale)
select 'K-chaines-v1', 'K', jsonb_build_object('max_leverage', 3, 'chain_params', 'utilisateur_5x3R'), 'champion',
       'Chaînes de victoires (routine 7) — papier uniquement'
 where not exists (select 1 from public.strategy_versions where arm = 'K');

insert into public.config(key, value) values
  ('chain_max_leverage', '3'::jsonb),
  ('chain_readonly_until', to_jsonb((now() + interval '7 days')::text)),
  ('chain_activated_at', to_jsonb(now()::text))
on conflict (key) do nothing;

revoke all on function public.paper_global_drawdown(), public.enforce_chain_position(public.positions),
  public.enforce_chain_open(), public.chain_on_position_close(), public.paper_chain_data()
  from public, anon, authenticated;

insert into public.iteration_log(routine, change, rationale, evidence)
select 'setup', '{"action":"routine7_migration","status":"ok"}'::jsonb,
       'Migration 009 : tables des chaînes de victoires, portefeuille K, garde-fous section 10. Routine 7 en lecture seule 7 jours.',
       jsonb_build_object('readonly_until', public.paper_cfg('chain_readonly_until'))
 where not exists (select 1 from public.iteration_log where change->>'action' = 'routine7_migration');
