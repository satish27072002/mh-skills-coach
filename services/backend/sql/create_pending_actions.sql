-- Create pending_actions table for chat confirmation state.
-- Idempotent.
CREATE TABLE IF NOT EXISTS pending_actions (
    id serial PRIMARY KEY,
    user_id text NOT NULL,
    action_type text NOT NULL,
    payload_json text NOT NULL,
    created_at timestamptz DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS pending_actions_user_action_idx
    ON pending_actions (user_id, action_type);

CREATE INDEX IF NOT EXISTS pending_actions_expires_at_idx
    ON pending_actions (expires_at);
