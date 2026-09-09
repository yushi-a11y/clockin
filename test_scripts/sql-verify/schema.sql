CREATE TABLE IF NOT EXISTS public.config (id text PRIMARY KEY, data jsonb, updated_at bigint);
CREATE TABLE IF NOT EXISTS public.picks (
  date text NOT NULL, mid text NOT NULL, sid int NOT NULL,
  created_at timestamptz DEFAULT now(), PRIMARY KEY (date, mid, sid)
);
CREATE INDEX IF NOT EXISTS idx_picks_date_sid ON public.picks (date, sid);
CREATE OR REPLACE FUNCTION public.picks_snapshot()
RETURNS jsonb LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object(
    'data', COALESCE((
      SELECT jsonb_object_agg(p_date, members)
      FROM (
        SELECT date AS p_date, jsonb_object_agg(mid, sids) AS members
        FROM (
          SELECT date, mid, jsonb_agg(sid ORDER BY sid) AS sids
          FROM public.picks GROUP BY date, mid
        ) dm GROUP BY date
      ) d
    ), '{}'::jsonb),
    'updated_at', (EXTRACT(epoch FROM now()) * 1000)::bigint
  );
$$;
