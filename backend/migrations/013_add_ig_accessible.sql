-- Add ig_accessible flag and ig_checked_at timestamp to athletes table.
-- ig_accessible = FALSE means the account is personal (Business Discovery fails).
-- ig_checked_at tracks when this was last verified; the nightly job re-checks after 7 days.

ALTER TABLE athletes ADD COLUMN IF NOT EXISTS ig_accessible BOOLEAN DEFAULT TRUE;
ALTER TABLE athletes ADD COLUMN IF NOT EXISTS ig_checked_at TIMESTAMPTZ;
