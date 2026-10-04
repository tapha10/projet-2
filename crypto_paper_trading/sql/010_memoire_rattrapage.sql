-- 010 : mémoire du projet, rattrapage des passages manqués, exploration (04/10/2026). Idempotent.

-- 1) État : date de la dernière entrée par bras (exploration après 7 jours sans entrée).
do $$ begin
  if not exists (select 1 from pg_proc where proname = 'paper_state_core') then
    alter function public.paper_state() rename to paper_state_core;
  end if;
end $$;
create or replace function public.paper_state() returns jsonb
language sql stable set search_path = '' as $$
  select public.paper_state_core() || jsonb_build_object(
    'last_entry', coalesce((select jsonb_object_agg(arm, m) from (select arm, max(opened_at) m
                                from public.positions group by arm) x), '{}'::jsonb));
$$;

insert into public.config(key, value) values ('exploration_after_days', '7'::jsonb) on conflict (key) do nothing;

-- 2) Rattrapage : ce qui manque aujourd'hui (heure de Paris) et la clôture d'hier.
create or replace function public.paper_catchup() returns jsonb
language sql stable set search_path = '' as $$
  with d as (select (now() at time zone 'Europe/Paris')::date as today),
  sun as (select today - (extract(isodow from today)::int % 7) as last_sunday from d),
  ok as (
    select routine, change, (created_at at time zone 'Europe/Paris')::date as day
      from public.iteration_log
     where created_at > now() - interval '3 days' and coalesce(change->>'status', 'ok') = 'ok'
  )
  select jsonb_build_object(
    'today', (select today from d),
    'hier', (select today - 1 from d),
    'routine5', exists (select 1 from ok, d where routine = 'routine5' and day = today),
    'routine6', exists (select 1 from ok, d where routine = 'routine6' and day = today),
    'routine7', exists (select 1 from ok, d where routine = 'routine7' and day = today),
    'adaptation', exists (select 1 from ok, d where routine = 'adaptation' and day = today),
    'verification', exists (select 1 from ok, d where routine = 'verification' and day = today),
    'cloture_hier', exists (select 1 from public.daily_results, d where date = today - 1),
    'dernier_dimanche', (select last_sunday from sun),
    'rapport_manque', (select extract(isodow from today) <> 7 from d)
                      and not exists (select 1 from public.weekly_reports, sun
                                       where (created_at at time zone 'Europe/Paris')::date >= last_sunday),
    'dimanche', extract(isodow from (select today from d)) = 7
  );
$$;

-- 3) Mémoire : résumé compact de l'état du projet pour reprendre sans souvenir.
create or replace function public.paper_memory() returns jsonb
language sql stable set search_path = '' as $$
  select jsonb_build_object(
    'now', now(),
    'mode', public.paper_cfg('mode'),
    'lecture_seule', jsonb_build_object('routine6', public.paper_cfg('r6_readonly_until'),
                                        'routine7', public.paper_cfg('chain_readonly_until')),
    'rattrapage', public.paper_catchup(),
    'positions_ouvertes', coalesce((select jsonb_object_agg(arm, n) from (select arm, count(*) n
                              from public.positions where status = 'open' group by arm) x), '{}'::jsonb),
    'trades_fermes', coalesce((select jsonb_object_agg(arm, n) from (select arm, count(*) n
                         from public.positions where status = 'closed' group by arm) x), '{}'::jsonb),
    'derniere_entree', coalesce((select jsonb_object_agg(arm, m) from (select arm, max(opened_at) m
                           from public.positions group by arm) x), '{}'::jsonb),
    'chaines', jsonb_build_object('ouvertes', (select count(*) from public.chains where source = 'live_paper' and state = 'ouverte'),
                                  'terminees', (select count(*) from public.chains where source = 'live_paper' and state <> 'ouverte')),
    'journal', coalesce((select jsonb_agg(jsonb_build_object('quand', created_at, 'routine', routine,
                           'quoi', left(rationale, 220)) order by id desc)
                         from (select * from public.iteration_log order by id desc limit 15) l), '[]'::jsonb)
  );
$$;

-- 4) Données routine 7 : alertes et motif de décision des signaux (exploration des chaînes).
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

revoke all on function public.paper_chain_data() from public, anon, authenticated;
revoke all on function public.paper_state_core(), public.paper_state(), public.paper_catchup(), public.paper_memory()
  from public, anon, authenticated;

-- 5) Rattrapage d'une clôture journalière manquée (écrite le lendemain, jamais par-dessus une clôture existante).
--    Fonction séparée : paper_record_daily(jsonb) reste inchangée.
create or replace function public.paper_record_daily_late(p_unrealized jsonb, p_date date)
 returns jsonb language plpgsql set search_path to ''
as $function$
declare
  d date := p_date;
  by_arm jsonb := '{}'::jsonb;
  a text; r record;
  tot_eq numeric := 0; tot_pnl numeric := 0;
  tot_open int := 0; tot_closed int := 0; tot_wins int := 0;
  eq numeric; unreal numeric;
begin
  if d is null or d >= (now() at time zone 'Europe/Paris')::date then
    raise exception 'paper_record_daily_late : date passée uniquement';
  end if;
  if exists (select 1 from public.daily_results where date = d) then
    return '{}'::jsonb;  -- ne remplace jamais une clôture déjà écrite
  end if;
  foreach a in array array['A','B','C','T','K'] loop
    unreal := coalesce((p_unrealized->>a)::numeric, 0);
    eq := public.paper_equity(a) + unreal;
    select coalesce(sum(pnl_usd) filter (where status='closed'
                 and (closed_at at time zone 'Europe/Paris')::date = d), 0) as pnl,
           count(*) filter (where status='open') as n_open,
           count(*) filter (where status='closed' and (closed_at at time zone 'Europe/Paris')::date = d) as n_closed,
           count(*) filter (where status='closed' and pnl_usd > 0 and (closed_at at time zone 'Europe/Paris')::date = d) as wins
      into r from public.positions where arm = a;
    by_arm := by_arm || jsonb_build_object(a, jsonb_build_object(
      'equity', round(eq, 2), 'realized_equity', round(public.paper_equity(a), 2),
      'unrealized', round(unreal, 2), 'pnl_usd', round(r.pnl, 2),
      'n_open', r.n_open, 'n_closed', r.n_closed, 'wins', r.wins,
      'drawdown', round(public.paper_drawdown(a), 4)));
    if a not in ('T', 'K') then
      tot_eq := tot_eq + eq; tot_pnl := tot_pnl + r.pnl;
      tot_open := tot_open + r.n_open; tot_closed := tot_closed + r.n_closed; tot_wins := tot_wins + r.wins;
    end if;
  end loop;
  insert into public.daily_results(date, equity, pnl_usd, n_open, n_closed, wins, notes, by_arm)
  values (d, round(tot_eq, 2), round(tot_pnl, 2), tot_open, tot_closed, tot_wins,
          'RATTRAPAGE écrit le lendemain (capital et latent au moment du rattrapage) ; equity = A+B+C, latent inclus ; démo uniquement', by_arm)
  on conflict (date) do nothing;
  return by_arm;
end;
$function$;
revoke all on function public.paper_record_daily_late(jsonb, date) from public, anon, authenticated;
