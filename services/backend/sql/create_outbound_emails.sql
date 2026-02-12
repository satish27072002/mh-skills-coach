-- Create outbound_emails table for email send logging.
-- Idempotent.
CREATE TABLE IF NOT EXISTS outbound_emails (
    id serial PRIMARY KEY,
    user_id text NOT NULL,
    to_email text NOT NULL,
    subject text NOT NULL,
    status text NOT NULL,
    error text NULL,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS outbound_emails_user_id_idx
    ON outbound_emails (user_id);

CREATE INDEX IF NOT EXISTS outbound_emails_created_at_idx
    ON outbound_emails (created_at);
