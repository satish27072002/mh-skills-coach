-- Create or migrate users table to UUID primary key and premium fields.
-- Idempotent for PostgreSQL.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
    IF to_regclass('public.users') IS NULL THEN
        CREATE TABLE public.users (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            google_sub text NOT NULL UNIQUE,
            email text NULL,
            name text NULL,
            is_premium boolean NOT NULL DEFAULT false,
            stripe_customer_id text NULL,
            premium_until timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
    ELSE
        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'users'
              AND column_name = 'id'
              AND data_type <> 'uuid'
        ) THEN
            ALTER TABLE public.users ADD COLUMN IF NOT EXISTS id_uuid uuid;
            UPDATE public.users
            SET id_uuid = COALESCE(id_uuid, gen_random_uuid());
            ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_pkey;
            ALTER TABLE public.users DROP COLUMN IF EXISTS id;
            ALTER TABLE public.users RENAME COLUMN id_uuid TO id;
            ALTER TABLE public.users ADD PRIMARY KEY (id);
        END IF;

        ALTER TABLE public.users ADD COLUMN IF NOT EXISTS google_sub text;
        ALTER TABLE public.users ADD COLUMN IF NOT EXISTS email text;
        ALTER TABLE public.users ADD COLUMN IF NOT EXISTS name text;
        ALTER TABLE public.users ADD COLUMN IF NOT EXISTS is_premium boolean NOT NULL DEFAULT false;
        ALTER TABLE public.users ADD COLUMN IF NOT EXISTS stripe_customer_id text;
        ALTER TABLE public.users ADD COLUMN IF NOT EXISTS premium_until timestamptz;
        ALTER TABLE public.users ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
        ALTER TABLE public.users ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

        UPDATE public.users
        SET google_sub = COALESCE(NULLIF(google_sub, ''), 'legacy-' || id::text)
        WHERE google_sub IS NULL OR google_sub = '';

        ALTER TABLE public.users ALTER COLUMN google_sub SET NOT NULL;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS users_google_sub_idx
    ON public.users (google_sub);

CREATE UNIQUE INDEX IF NOT EXISTS users_email_idx
    ON public.users (email)
    WHERE email IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS users_stripe_customer_id_idx
    ON public.users (stripe_customer_id)
    WHERE stripe_customer_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.set_users_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS users_set_updated_at ON public.users;
CREATE TRIGGER users_set_updated_at
BEFORE UPDATE ON public.users
FOR EACH ROW
EXECUTE FUNCTION public.set_users_updated_at();
