-- Additive development schema for scoped loyalty and prior-contact evidence.
-- No operational balances are modified by the application; runtime connections
-- read these rows through the read-only database session.

CREATE TABLE IF NOT EXISTS customer_loyalty_accounts (
    account_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL UNIQUE REFERENCES customers(customer_id),
    loyalty_tier TEXT NOT NULL,
    points_balance INTEGER NOT NULL CHECK (points_balance >= 0),
    account_status TEXT NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS loyalty_transactions (
    event_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    order_id TEXT REFERENCES orders(order_id),
    event_type TEXT NOT NULL CHECK (event_type IN (
        'points_earned', 'reward_redeemed', 'points_expired', 'points_adjusted'
    )),
    points_delta INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('posted', 'pending', 'reversed')),
    occurred_at TIMESTAMPTZ NOT NULL,
    expires_at DATE,
    reward_code TEXT,
    source TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS loyalty_transactions_customer_time_idx
    ON loyalty_transactions (customer_id, occurred_at DESC, event_id);

CREATE TABLE IF NOT EXISTS customer_communications (
    communication_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    order_id TEXT REFERENCES orders(order_id),
    channel TEXT NOT NULL,
    direction TEXT NOT NULL,
    topic TEXT NOT NULL,
    summary TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    outcome TEXT NOT NULL,
    source TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS customer_communications_customer_time_idx
    ON customer_communications (customer_id, occurred_at DESC, communication_id);
