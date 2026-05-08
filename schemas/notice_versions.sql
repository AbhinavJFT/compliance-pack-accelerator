-- Lakebase notice_versions DDL (§5.3)
-- Runs in the Lakebase instance alongside consent_events.sql

CREATE TABLE IF NOT EXISTS public.notice_versions (
    notice_version_id       UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    notice_id               VARCHAR(64)  NOT NULL,
    version_number          INTEGER      NOT NULL,
    language                CHAR(5)      NOT NULL,
    published_at            TIMESTAMPTZ  NOT NULL,
    retired_at              TIMESTAMPTZ,
    content_text            TEXT         NOT NULL,
    content_hash            VARCHAR(64)  NOT NULL,
    legal_basis             VARCHAR(64)  NOT NULL,
    purposes_covered        TEXT[]       NOT NULL,
    retention_policy_ref    VARCHAR(128),
    approved_by             VARCHAR(128) NOT NULL,
    approved_at             TIMESTAMPTZ  NOT NULL,

    UNIQUE (notice_id, version_number, language),

    CONSTRAINT chk_legal_basis
        CHECK (legal_basis IN (
            'consent','contract','legal_obligation',
            'vital_interests','public_interest','legitimate_interest'
        )),
    CONSTRAINT chk_version_positive
        CHECK (version_number > 0),
    CONSTRAINT chk_retired_after_published
        CHECK (retired_at IS NULL OR retired_at > published_at)
);

CREATE INDEX IF NOT EXISTS idx_notice_currently_live
    ON public.notice_versions(notice_id, language)
    WHERE retired_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_notice_hash
    ON public.notice_versions(content_hash);

COMMENT ON TABLE public.notice_versions IS
    'Every notice ever presented to a data principal. Consent events reference by notice_version_id. Never delete rows; supersede by retiring and creating a new version.';

-- ============================================================================
-- Seed the POC's single notice version (Day 8)
-- Replace SERVICE_PRINCIPAL with the actual service principal identity
-- ============================================================================
INSERT INTO public.notice_versions (
    notice_id,
    version_number,
    language,
    published_at,
    content_text,
    content_hash,
    legal_basis,
    purposes_covered,
    approved_by,
    approved_at
) VALUES (
    'marketing_notice',
    1,
    'en-IN',
    now(),
    E'We collect and process your personal data for the following purposes:\n\n'
    E'1. Core service delivery (contractual necessity)\n'
    E'2. Marketing communications via email (requires your consent)\n'
    E'3. Marketing communications via SMS (requires your consent)\n'
    E'4. Product usage analytics (requires your consent)\n'
    E'5. Sharing with third parties for their marketing (requires your consent)\n'
    E'6. Product personalization based on your behavior (requires your consent)\n\n'
    E'You may withdraw consent at any time via account settings or by contacting our DPO.\n'
    E'For questions or rights requests, contact dpo@example.com.\n\n'
    E'This notice complies with the Digital Personal Data Protection Act 2023.',
    encode(sha256(
        E'marketing_notice_v1_en-IN_' ||
        'core_service,marketing_email,marketing_sms,analytics,third_party_sharing,product_personalization'
    )::bytea, 'hex'),
    'consent',
    ARRAY['core_service','marketing_email','marketing_sms','analytics','third_party_sharing','product_personalization'],
    'GC_REVIEW_PENDING_STUB',  -- replace with actual GC identity in production
    now()
)
ON CONFLICT (notice_id, version_number, language) DO NOTHING;
