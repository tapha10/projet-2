-- Colonnes et fonction utilisées par le moteur (engine/).
alter table positions add column if not exists trailing_activate_price numeric;
alter table positions add column if not exists atr_at_entry numeric;
alter table positions add column if not exists margin_usd numeric;

insert into config(key, value) values ('slippage_pct', '0.001')
on conflict (key) do nothing;

-- Ligne du jour dans daily_results (heure de Paris).
-- p_unrealized : {"A": pnl latent, "B": ..., "C": ...} calculé par la routine 2.
-- Chaque bras est un portefeuille virtuel séparé ; equity = somme des trois.
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
  foreach a in array array['A','B','C'] loop
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
    tot_eq := tot_eq + eq; tot_pnl := tot_pnl + r.pnl;
    tot_open := tot_open + r.n_open; tot_closed := tot_closed + r.n_closed; tot_wins := tot_wins + r.wins;
  end loop;
  insert into public.daily_results(date, equity, pnl_usd, n_open, n_closed, wins, notes, by_arm)
  values (d, round(tot_eq, 2), round(tot_pnl, 2), tot_open, tot_closed, tot_wins,
          'equity = somme des 3 portefeuilles virtuels (A, B, C), PnL latent inclus ; démo uniquement', by_arm)
  on conflict (date) do update set equity = excluded.equity, pnl_usd = excluded.pnl_usd,
    n_open = excluded.n_open, n_closed = excluded.n_closed, wins = excluded.wins,
    notes = excluded.notes, by_arm = excluded.by_arm;
  return by_arm;
end;
$$;

revoke all on function paper_record_daily(jsonb) from public, anon, authenticated;
