-- Récapitulatif lisible : paper_history() renvoie aussi les preuves (evidence) des signaux
-- des 14 derniers jours, pour afficher les sources dans l'e-mail. Ajout seulement.
create or replace function paper_history() returns jsonb
language sql stable set search_path = '' as $$
  select jsonb_build_object(
    'now', now(),
    'config', (select jsonb_object_agg(key, value) from public.config where key not like 'lock:%'),
    'versions', coalesce((select jsonb_agg(to_jsonb(v) order by v.id) from public.strategy_versions v), '[]'::jsonb),
    'positions', coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from public.positions p), '[]'::jsonb),
    'signals', coalesce((select jsonb_agg((to_jsonb(s) - 'evidence')
        || jsonb_build_object('evidence', case when s.detected_at > now() - interval '14 days' then s.evidence end)
        order by s.id) from public.signals s), '[]'::jsonb),
    'iteration_log', coalesce((select jsonb_agg(to_jsonb(l) order by l.id)
        from (select * from public.iteration_log order by id desc limit 200) l), '[]'::jsonb),
    'daily_results', coalesce((select jsonb_agg(to_jsonb(d) order by d.date) from public.daily_results d), '[]'::jsonb)
  );
$$;
revoke all on function paper_history() from public, anon, authenticated;
