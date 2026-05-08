-- Unity Catalog column masks for DPDP data minimization (§5(2)).
--
-- Unmasks only for members of the workspace `admins` group (the
-- deployer / service principal). Persona demo users (CCO/GC/CMO/CFO)
-- and any other non-admin user see redacted values regardless of the
-- SQL path they take — dashboard tile, Genie, SQL editor, or REST API.
--
-- Masking strategy by PII type:
--   email                  → "x****@****.com"
--   phone / mobile         → "******" + last 4
--   aadhaar / pan / bank   → "****" + last 4
--   passport / ifsc        → full redaction
--   medical free-text      → "<REDACTED>"
--   date_of_birth          → keep year only
--
-- Apply with:  python3 scripts/apply_pii_masks.py
-- Idempotent: CREATE OR REPLACE FUNCTION + SET MASK is safe to re-run.

-- ---------------------------------------------------------------------------
-- UDFs — all accept STRING and return STRING
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION dpdp_poc.compliance.mask_email(val STRING)
RETURNS STRING
RETURN CASE
  WHEN is_member('admins') THEN val
  WHEN val IS NULL OR val = '' THEN val
  WHEN INSTR(val, '@') = 0 THEN '****'
  ELSE CONCAT(SUBSTR(val, 1, 1), '****@****',
              SUBSTR(val, INSTR(val, '.'), LENGTH(val)))
END;

CREATE OR REPLACE FUNCTION dpdp_poc.compliance.mask_phone(val STRING)
RETURNS STRING
RETURN CASE
  WHEN is_member('admins') THEN val
  WHEN val IS NULL OR val = '' THEN val
  WHEN LENGTH(val) < 4 THEN '****'
  ELSE CONCAT('******', SUBSTR(val, LENGTH(val) - 3, 4))
END;

CREATE OR REPLACE FUNCTION dpdp_poc.compliance.mask_id_last4(val STRING)
RETURNS STRING
RETURN CASE
  WHEN is_member('admins') THEN val
  WHEN val IS NULL OR val = '' THEN val
  WHEN LENGTH(val) < 4 THEN '****'
  ELSE CONCAT('****', SUBSTR(val, LENGTH(val) - 3, 4))
END;

CREATE OR REPLACE FUNCTION dpdp_poc.compliance.mask_full(val STRING)
RETURNS STRING
RETURN CASE
  WHEN is_member('admins') THEN val
  WHEN val IS NULL OR val = '' THEN val
  ELSE '<REDACTED>'
END;

CREATE OR REPLACE FUNCTION dpdp_poc.compliance.mask_dob(val DATE)
RETURNS DATE
RETURN CASE
  WHEN is_member('admins') THEN val
  WHEN val IS NULL THEN val
  ELSE MAKE_DATE(YEAR(val), 1, 1)
END;

-- ---------------------------------------------------------------------------
-- Apply masks to PII columns discovered by the register
-- ---------------------------------------------------------------------------
-- employees_tagged
ALTER TABLE dpdp_poc.silver.employees_tagged
  ALTER COLUMN email             SET MASK dpdp_poc.compliance.mask_email;
ALTER TABLE dpdp_poc.silver.employees_tagged
  ALTER COLUMN phone_number      SET MASK dpdp_poc.compliance.mask_phone;
ALTER TABLE dpdp_poc.silver.employees_tagged
  ALTER COLUMN aadhaar_number    SET MASK dpdp_poc.compliance.mask_id_last4;
ALTER TABLE dpdp_poc.silver.employees_tagged
  ALTER COLUMN pan_number        SET MASK dpdp_poc.compliance.mask_id_last4;
ALTER TABLE dpdp_poc.silver.employees_tagged
  ALTER COLUMN passport_number   SET MASK dpdp_poc.compliance.mask_full;
ALTER TABLE dpdp_poc.silver.employees_tagged
  ALTER COLUMN bank_account      SET MASK dpdp_poc.compliance.mask_id_last4;
ALTER TABLE dpdp_poc.silver.employees_tagged
  ALTER COLUMN ifsc_code         SET MASK dpdp_poc.compliance.mask_full;

-- customers_tagged
ALTER TABLE dpdp_poc.silver.customers_tagged
  ALTER COLUMN email_address     SET MASK dpdp_poc.compliance.mask_email;
ALTER TABLE dpdp_poc.silver.customers_tagged
  ALTER COLUMN mobile            SET MASK dpdp_poc.compliance.mask_phone;

-- users_tagged
ALTER TABLE dpdp_poc.silver.users_tagged
  ALTER COLUMN email             SET MASK dpdp_poc.compliance.mask_email;
ALTER TABLE dpdp_poc.silver.users_tagged
  ALTER COLUMN phone             SET MASK dpdp_poc.compliance.mask_phone;

-- transactions_tagged (caught by 2026-04-27 smoke test — ip_address was the
-- only finding without a mask)
ALTER TABLE dpdp_poc.silver.transactions_tagged
  ALTER COLUMN ip_address        SET MASK dpdp_poc.compliance.mask_full;

-- patients_tagged
ALTER TABLE dpdp_poc.silver.patients_tagged
  ALTER COLUMN email                     SET MASK dpdp_poc.compliance.mask_email;
ALTER TABLE dpdp_poc.silver.patients_tagged
  ALTER COLUMN phone                     SET MASK dpdp_poc.compliance.mask_phone;
ALTER TABLE dpdp_poc.silver.patients_tagged
  ALTER COLUMN emergency_contact_phone   SET MASK dpdp_poc.compliance.mask_phone;
ALTER TABLE dpdp_poc.silver.patients_tagged
  ALTER COLUMN aadhaar_number            SET MASK dpdp_poc.compliance.mask_id_last4;
ALTER TABLE dpdp_poc.silver.patients_tagged
  ALTER COLUMN insurance_id              SET MASK dpdp_poc.compliance.mask_id_last4;
ALTER TABLE dpdp_poc.silver.patients_tagged
  ALTER COLUMN medical_record_number     SET MASK dpdp_poc.compliance.mask_id_last4;
ALTER TABLE dpdp_poc.silver.patients_tagged
  ALTER COLUMN primary_diagnosis         SET MASK dpdp_poc.compliance.mask_full;
ALTER TABLE dpdp_poc.silver.patients_tagged
  ALTER COLUMN current_prescription      SET MASK dpdp_poc.compliance.mask_full;
ALTER TABLE dpdp_poc.silver.patients_tagged
  ALTER COLUMN allergies                 SET MASK dpdp_poc.compliance.mask_full;

-- ---------------------------------------------------------------------------
-- Lakeflow Connect (Salesforce) ingestion — silver tables populated by
-- scripts/seed_salesforce_data.py. Same governance treatment as Auto Loader
-- sources: non-admin personas see masked Aadhaar/PAN/IFSC/email/phone.
-- ---------------------------------------------------------------------------

-- sf_leads_tagged
ALTER TABLE dpdp_poc.silver.sf_leads_tagged
  ALTER COLUMN email             SET MASK dpdp_poc.compliance.mask_email;
ALTER TABLE dpdp_poc.silver.sf_leads_tagged
  ALTER COLUMN phone             SET MASK dpdp_poc.compliance.mask_phone;
ALTER TABLE dpdp_poc.silver.sf_leads_tagged
  ALTER COLUMN mobile            SET MASK dpdp_poc.compliance.mask_phone;
ALTER TABLE dpdp_poc.silver.sf_leads_tagged
  ALTER COLUMN aadhaar           SET MASK dpdp_poc.compliance.mask_id_last4;
ALTER TABLE dpdp_poc.silver.sf_leads_tagged
  ALTER COLUMN pan               SET MASK dpdp_poc.compliance.mask_id_last4;

-- sf_contacts_tagged
ALTER TABLE dpdp_poc.silver.sf_contacts_tagged
  ALTER COLUMN email             SET MASK dpdp_poc.compliance.mask_email;
ALTER TABLE dpdp_poc.silver.sf_contacts_tagged
  ALTER COLUMN phone             SET MASK dpdp_poc.compliance.mask_phone;
ALTER TABLE dpdp_poc.silver.sf_contacts_tagged
  ALTER COLUMN mobile            SET MASK dpdp_poc.compliance.mask_phone;
ALTER TABLE dpdp_poc.silver.sf_contacts_tagged
  ALTER COLUMN aadhaar           SET MASK dpdp_poc.compliance.mask_id_last4;
ALTER TABLE dpdp_poc.silver.sf_contacts_tagged
  ALTER COLUMN pan               SET MASK dpdp_poc.compliance.mask_id_last4;
ALTER TABLE dpdp_poc.silver.sf_contacts_tagged
  ALTER COLUMN ifsc              SET MASK dpdp_poc.compliance.mask_full;

-- sf_accounts_tagged (company-level — only PAN + phone are PII here)
ALTER TABLE dpdp_poc.silver.sf_accounts_tagged
  ALTER COLUMN company_pan       SET MASK dpdp_poc.compliance.mask_id_last4;
ALTER TABLE dpdp_poc.silver.sf_accounts_tagged
  ALTER COLUMN primary_phone     SET MASK dpdp_poc.compliance.mask_phone;

-- ---------------------------------------------------------------------------
-- Lakehouse Federation simulation — masks live on the federation_mock backing
-- tables. The silver views (federation_*_tagged) SELECT * over them, so the
-- mask propagates at query time. Reason: ALTER VIEW SET MASK is not always
-- supported across UC runtimes, but ALTER TABLE SET MASK on the source is.
-- ---------------------------------------------------------------------------

-- federation_mock.lead_scoring
ALTER TABLE dpdp_poc.federation_mock.lead_scoring
  ALTER COLUMN email             SET MASK dpdp_poc.compliance.mask_email;
ALTER TABLE dpdp_poc.federation_mock.lead_scoring
  ALTER COLUMN phone             SET MASK dpdp_poc.compliance.mask_phone;

-- federation_mock.campaign_response
ALTER TABLE dpdp_poc.federation_mock.campaign_response
  ALTER COLUMN email             SET MASK dpdp_poc.compliance.mask_email;
