-- Support the single-query order investigation endpoint.
-- Run with autocommit enabled because PostgreSQL requires CONCURRENTLY outside
-- an explicit transaction block.
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_order_items_order_item
    ON public.order_items (order_id, item_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_delivery_events_order_time_event
    ON public.delivery_events (order_id, event_time, event_id);

CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_returns_refunds_order_requested_return
    ON public.returns_refunds (order_id, requested_at, return_id);
