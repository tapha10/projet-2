-- Détection précoce (annonces d'exchanges, avant la hausse, scans toutes les 4 h).
-- Migration idempotente, ajouts seulement.

insert into config(key, value) values ('early_detection', '{
  "enabled": true,
  "pre_move": {"min_quote_volume_24h": 1000000, "max_abs_change_24h": 0.10, "max_change_7d": 0.20,
               "min_vol_ratio": 2.0, "min_oi_change_3d": 0.15, "max_compression": 0.85,
               "max_candidates": 8, "max_scan": 250, "threads": 8},
  "announcements": {"hours": 48, "fresh_hours": 24, "max_candidates": 10,
                    "sources": ["binance", "okx", "kucoin", "bitget", "bithumb"]},
  "intraday_scans_paris": ["02:00", "06:00", "10:00", "14:00", "18:00", "22:00"]
}')
on conflict (key) do nothing;

-- Nouveaux poids (les anciens sont inchangés) ; version 2.
update config
   set value = value || '{"pre_move_accumulation": 2.0, "annonce_exchange_fraiche": 1.0,
                          "alert_exchange_warning": -3.0, "version": 2}'::jsonb
 where key = 'signal_weights' and not (value ? 'pre_move_accumulation');

-- Étiquette de mode pour les signaux déjà enregistrés (tous issus du tri momentum d'origine).
update signals
   set signal_types = signal_types || array['mode_momentum']
 where not is_reference
   and detected_at < '2026-10-04'
   and not (signal_types && array['mode_momentum', 'mode_pre_move', 'mode_announcement']);

insert into iteration_log(routine, change, rationale)
select 'setup', '{"action": "early_detection", "status": "ok", "weights_version": 2}'::jsonb,
       'Détection précoce ajoutée : annonces d''exchanges (Binance, OKX, KuCoin, Bitget, Bithumb), '
       'mode « avant la hausse » (volume et open interest qui montent, prix calme), scans toutes les 4 h, '
       'comparaison des modes. Poids ajoutés : pre_move_accumulation 2,0 ; annonce_exchange_fraiche 1,0 ; '
       'alert_exchange_warning −3,0 (skip). Hypothèses à valider, comme les autres poids.'
where not exists (select 1 from iteration_log where change->>'action' = 'early_detection');
