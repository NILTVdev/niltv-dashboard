-- 028: When the agreement envelope was last re-sent to the athlete.
--
-- A resend re-notifies the existing DocuSign envelope. agreement_sent_at keeps
-- the date the envelope first went out; this column records the latest reminder.
--
-- Applied automatically by scripts/migrate.py on deploy.

ALTER TABLE applications ADD COLUMN IF NOT EXISTS agreement_reminded_at TIMESTAMPTZ;
