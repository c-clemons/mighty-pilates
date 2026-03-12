-- =============================================================================
-- MIGHTY PILATES — COMPREHENSIVE REVENUE & SALES ANALYTICS (CLAMPED + DEPOSITS)
-- Global Key + Cross-Region Soft-Link; deposits handled; finite-only breakage
-- UPDATED: Changed table names from BI_* to MART_* naming convention
-- CORRECTED: Fixed capacity enforcement, category duplicates, service type logic
-- =============================================================================

USE ROLE SYSADMIN;
USE WAREHOUSE COMPUTE_WH;
USE DATABASE MIGHTY_PILATES_ANALYTICS;
USE SCHEMA EARNED_REVENUE_ANALYTICS;

-- -----------------------------------------------------------------------------
-- VISIT LINKING REGISTRY — ensures frozen visits survive model rebuilds
-- This table is populated by running "Visit Linking Registry.sql" after month close.
-- If it doesn't exist yet, create it empty so the model runs without error.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS VISIT_LINKING_REGISTRY (
    VISIT_ID            VARCHAR     NOT NULL,
    PACKAGE_ID          VARCHAR     NOT NULL,
    LINK_TYPE           VARCHAR     NOT NULL,
    LINK_RANK           NUMBER      NOT NULL,
    VISIT_DATE          DATE        NOT NULL,
    SERVICE_TYPE        VARCHAR,
    STUDIO_ID           NUMBER,
    STUDIO_NAME         VARCHAR,
    LOCATION_ID         NUMBER,
    LOCATION_NAME       VARCHAR,
    CLIENT_ID           NUMBER,
    GLOBAL_CLIENT_KEY   VARCHAR,
    PAYMENT_KEY         VARCHAR,
    PAYMENT_REF_NO      NUMBER,
    FROZEN_THROUGH_DATE DATE        NOT NULL,
    FROZEN_AT           TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (VISIT_ID)
);

-- -----------------------------------------------------------------------------
-- 0) Utility UDFs
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION EARNED_REVENUE_ANALYTICS.NORM_NAME(s STRING)
RETURNS STRING
LANGUAGE SQL
AS $$ REGEXP_REPLACE(TRIM(REPLACE(s, '-', ' ')), ' +', ' ') $$;

CREATE OR REPLACE FUNCTION EARNED_REVENUE_ANALYTICS.CANON_STUDIO(s STRING)
RETURNS STRING
LANGUAGE SQL
AS $$
  CASE
    WHEN EARNED_REVENUE_ANALYTICS.NORM_NAME(s) = 'Mighty Pilates Westwood Village'
      THEN 'Mighty Pilates Westwood'
    WHEN EARNED_REVENUE_ANALYTICS.NORM_NAME(s) = 'Mighty Pilates Pacific Heights'
      THEN 'Mighty Pilates Presidio Heights'
    ELSE EARNED_REVENUE_ANALYTICS.NORM_NAME(s)
  END
$$;

CREATE OR REPLACE FUNCTION EARNED_REVENUE_ANALYTICS.CANON_LOCATION(s STRING)
RETURNS STRING
LANGUAGE SQL
AS $$
  CASE
    WHEN EARNED_REVENUE_ANALYTICS.NORM_NAME(s) = 'Mighty Pilates Westwood Village'
      THEN 'Mighty Pilates Westwood'
    WHEN EARNED_REVENUE_ANALYTICS.NORM_NAME(s) = 'Mighty Pilates Pacific Heights'
      THEN 'Mighty Pilates Presidio Heights'
    ELSE EARNED_REVENUE_ANALYTICS.NORM_NAME(s)
  END
$$;

-- FIX: Normalize category names for consistent sales/revenue reconciliation
CREATE OR REPLACE FUNCTION EARNED_REVENUE_ANALYTICS.NORMALIZE_CATEGORY(cat STRING)
RETURNS STRING
LANGUAGE SQL
AS $$
  CASE
    WHEN cat IS NULL THEN NULL
    WHEN cat IN ('Private', 'Private Class', 'Privates') THEN 'Private'
    WHEN cat ILIKE '%teacher%training%' THEN 'Mighty Teacher Training'
    WHEN cat IN ('Workshop', 'Workshops', 'Mighty Workshops', 'Mighty Pilates Workshops') THEN 'Workshop'
    WHEN cat IN ('Livestream', 'Livestream Classes') THEN 'Livestream'
    WHEN cat IN ('Apprentice Sessions', 'Apprentice Session') THEN 'Apprentice Sessions'
    ELSE cat
  END
$$;

  
-- -----------------------------------------------------------------------------
-- 1) CLIENT_XWALK — choose a single global key per (studio, client)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE TABLE CLIENT_XWALK AS
WITH v_src AS (
  SELECT DISTINCT STUDIO_ID, CLIENT_ID,
         LOWER(NULLIF(TRIM(EMAIL), ''))      AS email_l,
         LOWER(NULLIF(TRIM(FIRST_NAME), '')) AS fn_l,
         LOWER(NULLIF(TRIM(LAST_NAME),  '')) AS ln_l
  FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_VISITS
  WHERE CLIENT_ID IS NOT NULL
),
s_src AS (
  SELECT DISTINCT STUDIO_ID, CLIENT_ID,
         LOWER(NULLIF(TRIM(EMAIL_ID), ''))   AS email_l,
         LOWER(NULLIF(TRIM(FIRST_NAME), '')) AS fn_l,
         LOWER(NULLIF(TRIM(LAST_NAME),  '')) AS ln_l
  FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS
  WHERE CLIENT_ID IS NOT NULL
),
m_src AS (
  SELECT DISTINCT STUDIO_ID, CLIENT_ID,
         CAST(NULL AS STRING)                AS email_l,
         LOWER(NULLIF(TRIM(FIRST_NAME), '')) AS fn_l,
         LOWER(NULLIF(TRIM(LAST_NAME),  '')) AS ln_l
  FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_MEMBERSHIP_DAILY_DETAILS
  WHERE CLIENT_ID IS NOT NULL
),
u AS (SELECT * FROM v_src UNION SELECT * FROM s_src UNION SELECT * FROM m_src),
valid_names AS (
  SELECT STUDIO_ID, CLIENT_ID, email_l, fn_l, ln_l,
         CASE WHEN fn_l IS NOT NULL AND ln_l IS NOT NULL
               AND NOT REGEXP_LIKE(fn_l, 'test|guest|null|^n.?a$|none|unknown|no.?email|anon|house|generic|default', 'i')
               AND NOT REGEXP_LIKE(ln_l, 'test|guest|null|^n.?a$|none|unknown|no.?email|anon|house|generic|default', 'i')
              THEN CONCAT(fn_l,'|',ln_l) END AS name_key
  FROM u
),
best_key AS (
  SELECT STUDIO_ID, CLIENT_ID,
         COALESCE(email_l, name_key,
                  CONCAT('studio_', STUDIO_ID, '_client_', CLIENT_ID)) AS GLOBAL_CLIENT_KEY,
         ROW_NUMBER() OVER (PARTITION BY STUDIO_ID, CLIENT_ID
                            ORDER BY CASE WHEN email_l IS NOT NULL THEN 1
                                          WHEN name_key IS NOT NULL THEN 2 ELSE 3 END,
                                     email_l, name_key) AS rn
  FROM valid_names
)
SELECT STUDIO_ID, CLIENT_ID, GLOBAL_CLIENT_KEY
FROM best_key
WHERE rn = 1;

-- -----------------------------------------------------------------------------
-- 1B) CATEGORY_COMPATIBILITY_MAPPING — explicit business rules for visit-package matching
-- -----------------------------------------------------------------------------
CREATE OR REPLACE TABLE CATEGORY_COMPATIBILITY_MAPPING AS
SELECT * FROM VALUES
  -- MACHINE FAMILY
  ('Machine', 'Machine', 1, 'Exact match'),
  ('Dynamic Pricing', 'Machine', 2, 'Dynamic pricing for machine'),
  ('Staff Class', 'Machine', 2, 'Staff free machine classes'),
  ('Student Mighty Monthly Pass', 'Machine', 2, 'Student pass for machine'),
  ('Rental', 'Machine', 2, 'Equipment rental for machine'),
  ('New Client Special', 'Machine', 2, 'New client intro for machine'),
  ('Pilates Pods', 'Machine', 2, 'Small group machine'),
  ('Outdoor Mat Pilates', 'Machine', 2, 'Can use machine'),
  ('10 - Day Health Challenge', 'Machine', 2, 'Challenge uses machine'),
  
  -- PRIVATE FAMILY
  ('Private', 'Private', 1, 'Exact match'),
  ('Private Rental', 'Private', 2, 'Private studio rental'),
  ('Master Instructor Privates', 'Private', 2, 'Premium private'),
  ('Master Private Pilates', 'Private', 2, 'Master-level private'),
  ('Apprentice Private Pilates', 'Private', 2, 'Private with apprentice'),
  ('Online Privates', 'Private', 2, 'Online privates are private sessions'),  -- FIX: Moved from Livestream family
  ('Private', 'Semi-Private', 2, 'Private can use semi-private'),
  ('Semi-Private', 'Private', 2, 'Semi-private can use private'),
  
  -- SEMI-PRIVATE
  ('Semi-Private', 'Semi-Private', 1, 'Exact match'),
  
  -- LIVESTREAM / ONLINE FAMILY
  ('Livestream', 'Livestream', 1, 'Exact match'),
  ('Livestream Series', 'Livestream', 1, 'Livestream series'),
  ('Online Classes', 'Livestream', 2, 'Online uses livestream'),
  ('At Pilates - At Home', 'Livestream', 2, 'At-home uses livestream'),
  ('Mat Pilates - At Home', 'Livestream', 2, 'Mat at-home uses livestream'),
  
  -- WORKSHOP FAMILY
  ('Workshop', 'Workshop', 1, 'Exact match'),
  ('Advanced Tower Workshop', 'Workshop', 2, 'Specialty workshop'),
  ('Balance Workshop', 'Workshop', 2, 'Balance workshop'),
  
  -- TEACHER TRAINING FAMILY
  ('Mighty Teacher Training', 'Mighty Teacher Training', 1, 'Exact match'),
  ('Pilates Teacher Training', 'Mighty Teacher Training', 2, 'Alt name'),
  ('Pilates Instructor Certification', 'Mighty Teacher Training', 2, 'Cert uses training'),
  
  -- APPRENTICE FAMILY
  ('Apprentice Sessions', 'Apprentice Sessions', 1, 'Exact match'),
  ('Apprentice Duet', 'Apprentice Sessions', 2, 'Duet sessions'),
  
  -- TRIO FAMILY
  ('Trio', 'Semi-Private', 2, 'Trio uses semi-private'),
  ('Trio', 'Private', 3, 'Trio can use private (fallback)'),
  
  -- FEES
  ('Fees', 'Fees', 1, 'Exact match'),
  
  -- PILATES PODS
  ('Pilates Pods', 'Pilates Pods', 1, 'Exact match'),
  ('Pilates Pods', 'Machine', 2, 'Pods can use machine'),
  
  -- SPECIAL CATEGORIES
  ('Livestream Series', 'Cassandra LS Series', 2, 'Cassandra is livestream series'),
  ('Private Rental', 'Mighty Core Bootcamp', 2, 'Bootcamp uses rental'),
  ('Machine', 'Mighty Core Bootcamp', 3, 'Bootcamp can use machine (fallback)'),
  ('Private', 'New Teacher Private Special', 2, 'New teacher private'),
  ('Machine', 'Other', 3, 'Generic visits default to machine'),
  ('Outdoor Mat Pilates', 'Outdoor Mat Classes', 1, 'Exact match'),
  ('Livestream Series', 'Livestream Series', 1, 'Exact match')
AS t(PACKAGE_CATEGORY, COMPATIBLE_VISIT_TYPE, MATCH_PRIORITY, NOTES);

-- -----------------------------------------------------------------------------
-- 2) SERVICE TYPE mapping
-- -----------------------------------------------------------------------------
CREATE OR REPLACE TABLE SERVICE_TYPE_MAPPING AS
SELECT
  TYPE_GROUP_NAME AS ORIGINAL_TYPE_GROUP_NAME,
  CASE
    WHEN TYPE_GROUP_NAME IN ('Live Stream Privates','Community Class','Livestream Classes') THEN 'Livestream'
    WHEN TYPE_GROUP_NAME = 'Apprentice Sessions' THEN 'Apprentice Sessions'
    WHEN TYPE_GROUP_NAME = 'Private Pilates' THEN 'Private'
    WHEN TYPE_GROUP_NAME = 'Master Trainer Private Appt' THEN 'Mighty Teacher Training'
    WHEN TYPE_GROUP_NAME IN ('Private Class Buyout','Private Room Rental') THEN 'Private Class'
    WHEN TYPE_GROUP_NAME = 'Mighty Teacher Training' THEN 'Mighty Teacher Training'
    WHEN TYPE_GROUP_NAME IN ('Workshop','Workshops','Mighty Pilates Work Shops') THEN 'Workshop'
    WHEN TYPE_GROUP_NAME IN ('Semi-Private','Master Trainer Semi Private','Trio Privates') THEN 'Semi-Private'
    WHEN TYPE_GROUP_NAME = 'Machine' THEN 'Machine'
    WHEN TYPE_GROUP_NAME = 'MMP Member Pop Up' THEN 'MMP Member Pop Up'
    WHEN TYPE_GROUP_NAME = 'Category 2' THEN 'Other'
    ELSE TYPE_GROUP_NAME
  END AS SERVICE_TYPE
FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_VISITS
GROUP BY TYPE_GROUP_NAME;

-- -----------------------------------------------------------------------------
-- Recognition mapping
-- -----------------------------------------------------------------------------

-- Recognition type map (unchanged except this relies on Staff Class now being a real REVENUE_CATEGORY upstream)
CREATE OR REPLACE TABLE REVENUE_CATEGORY_RECOGNITION_TYPE AS
SELECT * FROM VALUES
  ('Machine', 'visits-based'),
  ('Private', 'visits-based'),
  ('Semi-Private', 'visits-based'),
  ('Trio', 'visits-based'),
  ('Dynamic Pricing', 'visits-based'),
  ('Student Mighty Monthly Pass', 'visits-based'),
  ('Master Instructor Privates', 'visits-based'),
  ('New Client Special', 'visits-based'),
  ('Private Rental', 'visits-based'),
  ('Rental', 'visits-based'),
  ('Workshop', 'visits-based'),
  ('Mighty Teacher Training', 'visits-based'),
  ('Apprentice Sessions', 'visits-based'),
  ('Apprentice Duet', 'visits-based'),
  ('Pilates Pods', 'visits-based'),
  ('Outdoor Mat Pilates', 'visits-based'),
  ('Advanced Tower Workshop', 'visits-based'),
  ('Balance Workshop', 'visits-based'),
  ('Mighty Workshops', 'visits-based'),
  ('Pilates Teacher Training', 'visits-based'),
  ('Pilates Instructor Certification', 'visits-based'),
  ('Apprentice Private Pilates', 'visits-based'),
  ('Master Private Pilates', 'visits-based'),
  ('Online Privates', 'visits-based'),

  -- Immediate (do NOT link to visits)
  ('Staff Class', 'immediate'),

  -- Daily pro-rata (do NOT link to visits)
  ('Livestream', 'daily-pro-rata'),
  ('Livestream Series', 'daily-pro-rata'),
  ('Cassandra LS Series', 'daily-pro-rata'),
  ('Online Classes', 'daily-pro-rata'),
  ('At Pilates - At Home', 'daily-pro-rata'),
  ('Mat Pilates - At Home', 'daily-pro-rata'),

  -- Immediate retail-ish
  ('ACCESSORIES', 'immediate'),
  ('GRIP SOCKS', 'immediate'),
  ('NSK RETAIL', 'immediate'),
  ('MIGHTY RETAIL', 'immediate'),
  ('FEES', 'immediate'),
  ('Fees', 'immediate'),
  ('Food/Drink', 'immediate'),
  ('Skin/Body', 'immediate'),
  ('Other Products', 'immediate'),
  ('CLOTHING', 'immediate'),
  ('10 - Day Health Challenge', 'immediate'),
  ('Unassigned', 'immediate'),

  ('ClassPass', 'separate'),
  ('Contract Enrollment Fee', 'price-adjustment'),
  ('Gift Certificate', 'immediate-redemption-based')
AS t(REVENUE_CATEGORY, RECOGNITION_TYPE);

-- -----------------------------------------------------------------------------
-- 3) PRICING_PER_VISIT (sales) — livestream guard + deposits + no NULL PAYMENT_REF_NO
-- -----------------------------------------------------------------------------
-- Identify livestream products by observed livestream visits
CREATE OR REPLACE TABLE LIVESTREAM_PRODUCTS AS
SELECT DISTINCT p.PRODUCT_ID
FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_VISITS v
JOIN PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS p
  ON v.PAYMENT_REF_NO = p.PAYMENT_REF_NO AND v.STUDIO_ID = p.STUDIO_ID  -- FIX: STUDIO_ID instead of CLIENT_ID for recipient visits
WHERE v.TYPE_GROUP_NAME IN ('Live Stream Privates','Community Class','Livestream Classes');

-- -------------------------------------------------------------------------
-- Build base PRICING_PER_VISIT
-- -------------------------------------------------------------------------
CREATE OR REPLACE TABLE PRICING_PER_VISIT AS
SELECT 
  CONCAT(p.PAYMENT_REF_NO, '-', p.CLIENT_ID, '-', p.STUDIO_ID)                        AS UNIQUE_TRANSACTION_ID,
  CONCAT(p.PAYMENT_REF_NO, '-', p.CLIENT_ID, '-', p.STUDIO_ID, '-', p.PRODUCT_ID)     AS PACKAGE_ID,
  p.PAYMENT_REF_NO, p.STUDIO_ID,
  EARNED_REVENUE_ANALYTICS.NORM_NAME(p.STUDIO_NAME)   AS STUDIO_NAME,
  p.LOCATION_ID, EARNED_REVENUE_ANALYTICS.NORM_NAME(p.LOCATION_NAME) AS LOCATION_NAME,
  p.CLIENT_ID, cx.GLOBAL_CLIENT_KEY,
  p.SALE_DATE, p.PRODUCT_ID, p.CATEGORY_ID, p.PRODUCT_DESCRIPTION, 
  EARNED_REVENUE_ANALYTICS.NORMALIZE_CATEGORY(
    CASE
      WHEN p.ITEM_TYPE = 'Pricing Option'
       AND (
         p.PRODUCT_DESCRIPTION ILIKE '%staff class%'
         OR p.PRODUCT_DESCRIPTION ILIKE '%staff drop in%'
         OR p.PRODUCT_DESCRIPTION ILIKE '%staff classes%'
       )
      THEN 'Staff Class'
      ELSE p.REVENUE_CATEGORY
    END
  ) AS REVENUE_CATEGORY,
  p.ITEM_TYPE, p.PO_CAPACITY_TYPE_V1 AS PACKAGE_TYPE,
  p.UNIT_PRICE,
  COALESCE(p.DISCOUNT_AMT_LOCAL, 0) AS DISCOUNT_AMT_LOCAL,
  p.ITEMTAX_LOCAL AS TAX_LOCAL,
  p.QUANTITY, p.GROSS_UNIT_PRICE,
  COALESCE(p.NET_CASH_ON_HAND,0)                       AS NET_CASH_ON_HAND,
  COALESCE(p.ACCOUNT_AND_GIFT_REDEMPTION_AMOUNT,0)     AS ACCOUNT_AND_GIFT_REDEMPTION_AMOUNT,
  COALESCE(p.NET_CASH_ON_HAND,0)+COALESCE(p.ACCOUNT_AND_GIFT_REDEMPTION_AMOUNT,0) AS NET_CASH,
  (p.UNIT_PRICE - COALESCE(p.DISCOUNT_AMT_LOCAL, 0)) AS NET_PACKAGE_PRICE,

  CASE 
    WHEN p.PO_CAPACITY_TYPE_V1 = 'Unlimited' THEN NULL 
    WHEN COALESCE(p.PO_CAPACITY_COUNT, 0) = 0 THEN NULL
    ELSE p.PO_CAPACITY_COUNT 
  END AS PO_CAPACITY_COUNT,

  p.PO_CAPACITY_COUNT AS ORIGINAL_PO_CAPACITY_COUNT,

  IFF(
    p.PO_CAPACITY_TYPE_V1 = 'Unlimited'
    OR COALESCE(p.PO_CAPACITY_COUNT, 0) = 0,
    1, 0
  ) AS IS_UNLIMITED_LIKE,

  IFF(
    EARNED_REVENUE_ANALYTICS.NORMALIZE_CATEGORY(
      CASE
        WHEN p.ITEM_TYPE = 'Pricing Option'
         AND (
           p.PRODUCT_DESCRIPTION ILIKE '%staff class%'
           OR p.PRODUCT_DESCRIPTION ILIKE '%staff drop in%'
           OR p.PRODUCT_DESCRIPTION ILIKE '%staff classes%'
         )
        THEN 'Staff Class'
        ELSE p.REVENUE_CATEGORY
      END
    ) IN (
      'Online Classes',
      'At Pilates - At Home',
      'Mat Pilates - At Home',
      'Livestream',
      'Livestream Classes',
      'Livestream Series'
    )
    OR (p.PRODUCT_DESCRIPTION ILIKE '%Unlimited Livestream%' 
        AND p.REVENUE_CATEGORY NOT IN ('Machine','Private','Semi-Private','Mighty Teacher Training'))
    OR (p.PRODUCT_DESCRIPTION ILIKE '%Livestream Membership%' 
        AND p.REVENUE_CATEGORY NOT IN ('Machine','Private','Semi-Private','Mighty Teacher Training')),
    1, 0
  ) AS IS_LIVESTREAM,

  IFF(
    REGEXP_LIKE(
      COALESCE(p.PRODUCT_DESCRIPTION,'') || ' ' || COALESCE(p.REVENUE_CATEGORY,''),
      'contract\\s*deposit','i'
    ),
    1, 0
  ) AS IS_DEPOSIT,

  IFF(p.SALE_DATE < '2024-12-13', 1, 0) AS IS_OLD_MIGHTY,
  p.IS_RETURN
FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS p
LEFT JOIN CLIENT_XWALK cx 
  ON cx.STUDIO_ID = p.STUDIO_ID 
 AND cx.CLIENT_ID = p.CLIENT_ID
LEFT JOIN LIVESTREAM_PRODUCTS lsp 
  ON lsp.PRODUCT_ID = p.PRODUCT_ID
WHERE
  NOT EXISTS (
    SELECT 1
    FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS dup
    WHERE dup.PAYMENT_REF_NO = p.PAYMENT_REF_NO
      AND dup.CLIENT_ID = p.CLIENT_ID
      AND dup.PRODUCT_ID = p.PRODUCT_ID
      AND dup.SALE_DATE = p.SALE_DATE
      AND dup.STUDIO_NAME LIKE '%Presidio%'
      AND p.STUDIO_NAME LIKE '%Marin%'
      AND p.SALE_DATE < '2025-04-24'
  )
  AND (p.PRODUCT_DESCRIPTION != 'ClassPass' OR p.PRODUCT_DESCRIPTION IS NULL)
  AND (p.ITEM_TYPE != 'Pricing Option' OR p.PAYMENT_REF_NO IS NOT NULL OR p.IS_RETURN = 1)
  AND p.CATEGORY_ID NOT IN (-6, -64, -73);

-- -------------------------------------------------------------------------
-- Stage derived revenue fields
-- -------------------------------------------------------------------------
CREATE OR REPLACE TABLE PRICING_PER_VISIT_STAGE AS
SELECT
  b.*,

  CASE
    WHEN b.ITEM_TYPE = 'Pricing Option'
     AND COALESCE(b.IS_DEPOSIT,0) = 0
    THEN b.NET_PACKAGE_PRICE
    ELSE 0
  END AS DEFERRED_REVENUE,

  CASE
    WHEN b.ITEM_TYPE = 'Pricing Option'
     AND COALESCE(b.IS_DEPOSIT,0) = 0
     AND COALESCE(b.ORIGINAL_PO_CAPACITY_COUNT,0) > 0
    THEN b.NET_PACKAGE_PRICE / b.ORIGINAL_PO_CAPACITY_COUNT
    WHEN b.ITEM_TYPE = 'Pricing Option'
     AND COALESCE(b.IS_DEPOSIT,0) = 0
     AND b.ORIGINAL_PO_CAPACITY_COUNT IS NULL
    THEN NULL
    ELSE 0
  END AS NET_REVENUE_PER_VISIT,

  CASE
    WHEN b.ITEM_TYPE = 'Pricing Option'
     AND COALESCE(b.IS_DEPOSIT,0) = 0
     AND COALESCE(b.ORIGINAL_PO_CAPACITY_COUNT,0) > 0
    THEN b.GROSS_UNIT_PRICE / b.ORIGINAL_PO_CAPACITY_COUNT
    WHEN b.ITEM_TYPE = 'Pricing Option'
     AND COALESCE(b.IS_DEPOSIT,0) = 0
     AND b.ORIGINAL_PO_CAPACITY_COUNT IS NULL
    THEN NULL
    ELSE 0
  END AS GROSS_REVENUE_PER_VISIT,

  CASE
    WHEN b.ITEM_TYPE = 'Pricing Option'
     AND COALESCE(b.IS_DEPOSIT,0) = 0
     AND COALESCE(b.ORIGINAL_PO_CAPACITY_COUNT,0) > 0
    THEN b.TAX_LOCAL / b.ORIGINAL_PO_CAPACITY_COUNT
    WHEN b.ITEM_TYPE = 'Pricing Option'
     AND COALESCE(b.IS_DEPOSIT,0) = 0
     AND b.ORIGINAL_PO_CAPACITY_COUNT IS NULL
    THEN NULL
    ELSE 0
  END AS TAX_PER_VISIT

FROM PRICING_PER_VISIT b;

-- -------------------------------------------------------------------------
-- Swap tables atomically
-- -------------------------------------------------------------------------
DROP TABLE IF EXISTS PRICING_PER_VISIT_BASE;

ALTER TABLE PRICING_PER_VISIT RENAME TO PRICING_PER_VISIT_BASE;
ALTER TABLE PRICING_PER_VISIT_STAGE RENAME TO PRICING_PER_VISIT;



-- keep one row per PACKAGE_ID
CREATE OR REPLACE TABLE PRICING_PER_VISIT_UNIQ AS
SELECT *
FROM (
  SELECT p.*,
         ROW_NUMBER() OVER (
           PARTITION BY p.PACKAGE_ID
           ORDER BY CASE WHEN COALESCE(p.IS_RETURN,0)=1 THEN 1 ELSE 0 END,
                    -COALESCE(p.NET_CASH,0),
                    p.SALE_DATE DESC
         ) AS _rn
  FROM PRICING_PER_VISIT p
)
WHERE _rn=1;

-- Finite, clean subset for usage/linking
CREATE OR REPLACE TABLE PRICING_PER_VISIT_CLEAN AS
SELECT *
FROM PRICING_PER_VISIT_UNIQ
WHERE ITEM_TYPE='Pricing Option'
  AND COALESCE(PO_CAPACITY_COUNT,0)>0
  AND COALESCE(IS_LIVESTREAM,0)=0
  AND COALESCE(IS_DEPOSIT,0)=0;

-- =============================================================================
-- SECTION 4: PACKAGE EXPIRATION (REGISTRY-BASED - PREVENTS HISTORICAL DRIFT)
-- =============================================================================
-- This new approach:
-- 1. Keeps existing packages reading from registry (never recalculated)
-- 2. Only calculates expirations for NEW packages
-- 3. Locks new expirations into registry immediately
-- 4. Historical values NEVER change
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 4A) PACKAGE_EXPIRATION_TRUE (unchanged - this is source data)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE TABLE PACKAGE_EXPIRATION_TRUE AS
WITH membership_dedupe AS (
  SELECT PAYMENT_REF_NO, CLIENT_ID, STUDIO_ID,
         PRICING_OPTION_ACTIVATION_DATE, PRICING_OPTION_EXP_DATE, DATE,
         ROW_NUMBER() OVER (
           PARTITION BY PAYMENT_REF_NO, CLIENT_ID, STUDIO_ID
           ORDER BY DATE DESC, PRICING_OPTION_EXP_DATE DESC
         ) AS rn
  FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_MEMBERSHIP_DAILY_DETAILS
  WHERE PRICING_OPTION_ACTIVATION_DATE IS NOT NULL
    AND PRICING_OPTION_EXP_DATE IS NOT NULL
    AND PRICING_OPTION_EXP_DATE > PRICING_OPTION_ACTIVATION_DATE
    AND PAYMENT_REF_NO IS NOT NULL
)
SELECT pv.PACKAGE_ID,
       m.PRICING_OPTION_ACTIVATION_DATE AS START_DATE,
       m.PRICING_OPTION_EXP_DATE        AS EXPIRATION_DATE,
       DATEDIFF(DAY, m.PRICING_OPTION_ACTIVATION_DATE, m.PRICING_OPTION_EXP_DATE) + 1 AS PACKAGE_DURATION_DAYS
FROM membership_dedupe m
JOIN PRICING_PER_VISIT_UNIQ pv
  ON pv.PAYMENT_REF_NO = m.PAYMENT_REF_NO
 AND pv.CLIENT_ID      = m.CLIENT_ID
 AND pv.STUDIO_ID      = m.STUDIO_ID
WHERE m.rn=1
  AND pv.ITEM_TYPE='Pricing Option'
  AND NOT REGEXP_LIKE(COALESCE(pv.PRODUCT_DESCRIPTION,''), '\\bbooks?\\b', 'i');

-- -----------------------------------------------------------------------------
-- 4B-SHARED) CATEGORY_MONTHS — single source of truth for imputed durations
-- -----------------------------------------------------------------------------
-- Calendar-month durations by revenue category (matches MindBody policy):
--   1 month:  Machine, group classes, memberships, drop-ins, specials, fees
--   6 months: Privates, semi-privates, master instructor, trios, rentals
--  12 months: Livestream, teacher training, certifications
-- Used by both IMPUTED expiration and REGISTRY insertion.
-- -----------------------------------------------------------------------------

CREATE OR REPLACE TEMP TABLE CATEGORY_MONTHS AS
SELECT COLUMN1::VARCHAR AS REVENUE_CATEGORY, COLUMN2::NUMBER AS DURATION_MONTHS FROM VALUES
  ('Machine',                      1),
  ('Student Mighty Monthly Pass',  1),
  ('New Client Special',           1),
  ('Dynamic Pricing',              1),
  ('Gympass Revenue',              1),
  ('Online Classes',               1),
  ('Mat Pilates - At Home',        1),
  ('At Pilates - At Home',         1),
  ('Outdoor Mat Pilates',          1),
  ('Workshop',                     1),
  ('Balance Workshop',             1),
  ('Advanced Tower Workshop',      1),
  ('10 - Day Health Challenge',    1),
  ('Staff Class',                  1),
  ('Rental',                       1),
  ('Fees',                         1),
  ('Pilates Pods',                 1),
  ('Apprentice Sessions',          1),
  ('Apprentice Duet',              1),
  ('Livestream Series',            1),
  ('Private',                      6),
  ('Semi-Private',                 6),
  ('Master Instructor Privates',   6),
  ('Master Private Pilates',       6),
  ('Apprentice Private Pilates',   6),
  ('Online Privates',              6),
  ('Private Rental',               6),
  ('Private Events',               6),
  ('Trio',                         6),
  ('UNKNOWN',                      6),
  ('Livestream',                  12),
  ('Mighty Teacher Training',     12),
  ('Pilates Instructor Certification', 12);

-- -----------------------------------------------------------------------------
-- 4B) PACKAGE_EXPIRATION_IMPUTED (calendar-month based)
-- -----------------------------------------------------------------------------
-- Uses DATEADD(MONTH, N) to match MindBody's calendar-month expiration logic.
-- Only applies to packages NOT already in the PACKAGE_EXPIRATION_TRUE table.
-- -----------------------------------------------------------------------------

CREATE OR REPLACE TABLE PACKAGE_EXPIRATION_IMPUTED AS
WITH EXCLUDE_PRODUCTS AS (
  SELECT COLUMN1::NUMBER AS PRODUCT_ID FROM VALUES
    (10324),(102986),(12085),(103151),(1024),(100018),(10267),(100713),(100628),(2910),(155),(3582)
)
SELECT pv.PACKAGE_ID,
       pv.SALE_DATE AS START_DATE,
       DATEADD(MONTH,
         COALESCE(cm.DURATION_MONTHS, 6),
         pv.SALE_DATE
       ) AS EXPIRATION_DATE,
       DATEDIFF(DAY, pv.SALE_DATE,
         DATEADD(MONTH, COALESCE(cm.DURATION_MONTHS, 6), pv.SALE_DATE)
       ) AS PACKAGE_DURATION_DAYS
FROM PRICING_PER_VISIT_UNIQ pv
LEFT JOIN CATEGORY_MONTHS cm
  ON cm.REVENUE_CATEGORY = COALESCE(pv.REVENUE_CATEGORY, 'UNKNOWN')
LEFT JOIN EXCLUDE_PRODUCTS xp ON xp.PRODUCT_ID = pv.PRODUCT_ID
LEFT JOIN PACKAGE_EXPIRATION_TRUE t ON t.PACKAGE_ID = pv.PACKAGE_ID
WHERE pv.ITEM_TYPE='Pricing Option'
  AND COALESCE(pv.IS_DEPOSIT,0)=0
  AND COALESCE(pv.IS_UNLIMITED_LIKE,0)=0
  AND xp.PRODUCT_ID IS NULL
  AND t.PACKAGE_ID IS NULL
  AND NOT REGEXP_LIKE(COALESCE(pv.PRODUCT_DESCRIPTION,''), '\\bbooks?\\b', 'i');

-- -----------------------------------------------------------------------------
-- 4C) PACKAGE_EXPIRATION_FORCED (12-month fallback for ancient packages)
-- -----------------------------------------------------------------------------

CREATE OR REPLACE TEMP TABLE PACKAGE_EXPIRATION_FORCED AS
SELECT
  pv.PACKAGE_ID,
  pv.SALE_DATE AS START_DATE,
  DATEADD(MONTH, 12, pv.SALE_DATE) AS EXPIRATION_DATE,
  DATEDIFF(DAY, pv.SALE_DATE, DATEADD(MONTH, 12, pv.SALE_DATE)) AS PACKAGE_DURATION_DAYS
FROM PRICING_PER_VISIT_UNIQ pv
JOIN REVENUE_CATEGORY_RECOGNITION_TYPE rct
  ON rct.REVENUE_CATEGORY = EARNED_REVENUE_ANALYTICS.NORMALIZE_CATEGORY(pv.REVENUE_CATEGORY)
 AND rct.RECOGNITION_TYPE = 'visits-based'
LEFT JOIN PACKAGE_EXPIRATION_TRUE t
  ON t.PACKAGE_ID = pv.PACKAGE_ID
LEFT JOIN PACKAGE_EXPIRATION_IMPUTED i
  ON i.PACKAGE_ID = pv.PACKAGE_ID
WHERE pv.ITEM_TYPE = 'Pricing Option'
  AND COALESCE(pv.IS_UNLIMITED_LIKE,0)=0
  AND COALESCE(pv.IS_DEPOSIT,0)=0
  AND pv.SALE_DATE < DATEADD(MONTH, -12, CURRENT_DATE)
  AND t.PACKAGE_ID IS NULL
  AND i.PACKAGE_ID IS NULL
  AND NOT REGEXP_LIKE(COALESCE(pv.PRODUCT_DESCRIPTION,''), '\\bbooks?\\b', 'i');

-- =============================================================================
-- 4D) REGISTRY-BASED PACKAGE_EXPIRATION (NEW APPROACH)
-- =============================================================================
-- This replaces the old UNION ALL approach with registry-based logic
-- =============================================================================

-- Step 1: Identify NEW packages (not yet in registry)
CREATE OR REPLACE TEMP TABLE NEW_PACKAGES_NEEDING_EXPIRATION AS
SELECT pv.PACKAGE_ID
FROM PRICING_PER_VISIT_UNIQ pv
LEFT JOIN PACKAGE_EXPIRATION_REGISTRY per ON per.PACKAGE_ID = pv.PACKAGE_ID
WHERE pv.ITEM_TYPE = 'Pricing Option'
  AND COALESCE(pv.IS_UNLIMITED_LIKE, 0) = 0
  AND COALESCE(pv.IS_DEPOSIT, 0) = 0
  AND per.PACKAGE_ID IS NULL;  -- Only packages NOT in registry

-- Step 2: Calculate expirations for NEW packages
CREATE OR REPLACE TEMP TABLE NEW_PACKAGE_EXPIRATIONS AS
-- TRUE expirations for new packages
SELECT 
  t.PACKAGE_ID, 
  t.START_DATE, 
  t.EXPIRATION_DATE, 
  t.PACKAGE_DURATION_DAYS, 
  'TRUE' AS SOURCE,
  0 AS PRIORITY
FROM PACKAGE_EXPIRATION_TRUE t
WHERE EXISTS (SELECT 1 FROM NEW_PACKAGES_NEEDING_EXPIRATION n WHERE n.PACKAGE_ID = t.PACKAGE_ID)

UNION ALL

-- IMPUTED for new packages (only if no TRUE exists)
SELECT 
  i.PACKAGE_ID, 
  i.START_DATE, 
  i.EXPIRATION_DATE, 
  i.PACKAGE_DURATION_DAYS, 
  'IMPUTED' AS SOURCE,
  1 AS PRIORITY
FROM PACKAGE_EXPIRATION_IMPUTED i
WHERE EXISTS (SELECT 1 FROM NEW_PACKAGES_NEEDING_EXPIRATION n WHERE n.PACKAGE_ID = i.PACKAGE_ID)
  AND NOT EXISTS (SELECT 1 FROM PACKAGE_EXPIRATION_TRUE t WHERE t.PACKAGE_ID = i.PACKAGE_ID)

UNION ALL

-- FORCED for new packages (only if no TRUE or IMPUTED exists)
SELECT 
  f.PACKAGE_ID, 
  f.START_DATE, 
  f.EXPIRATION_DATE, 
  f.PACKAGE_DURATION_DAYS, 
  'FORCED' AS SOURCE,
  2 AS PRIORITY
FROM PACKAGE_EXPIRATION_FORCED f
WHERE EXISTS (SELECT 1 FROM NEW_PACKAGES_NEEDING_EXPIRATION n WHERE n.PACKAGE_ID = f.PACKAGE_ID)
  AND NOT EXISTS (SELECT 1 FROM PACKAGE_EXPIRATION_TRUE t WHERE t.PACKAGE_ID = f.PACKAGE_ID)
  AND NOT EXISTS (SELECT 1 FROM PACKAGE_EXPIRATION_IMPUTED i WHERE i.PACKAGE_ID = f.PACKAGE_ID);

-- Step 3: Deduplicate (pick best expiration for each package)
CREATE OR REPLACE TEMP TABLE NEW_PACKAGE_EXPIRATIONS_FINAL AS
SELECT PACKAGE_ID, START_DATE, EXPIRATION_DATE, PACKAGE_DURATION_DAYS, SOURCE
FROM (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY PACKAGE_ID ORDER BY PRIORITY) AS rn
  FROM NEW_PACKAGE_EXPIRATIONS
)
WHERE rn = 1;

-- Step 4: Add new packages to registry (using CREATE OR REPLACE for reader account)
CREATE OR REPLACE TABLE PACKAGE_EXPIRATION_REGISTRY AS
-- Keep all existing packages
SELECT * FROM PACKAGE_EXPIRATION_REGISTRY

UNION ALL

-- Add new packages
SELECT
  npe.PACKAGE_ID,
  npe.START_DATE,
  npe.EXPIRATION_DATE,
  npe.PACKAGE_DURATION_DAYS,
  npe.SOURCE AS EXPIRATION_SOURCE,
  CURRENT_DATE AS ASSIGNED_ON,
  CASE
    WHEN npe.SOURCE = 'IMPUTED' THEN cm.DURATION_MONTHS
    ELSE NULL
  END AS MEDIAN_USED,  -- Stores DURATION_MONTHS (not days)
  pv.PRODUCT_DESCRIPTION,
  pv.REVENUE_CATEGORY,
  'Assigned on ' || CURRENT_DATE AS NOTES
FROM NEW_PACKAGE_EXPIRATIONS_FINAL npe
LEFT JOIN PRICING_PER_VISIT_UNIQ pv ON pv.PACKAGE_ID = npe.PACKAGE_ID
LEFT JOIN CATEGORY_MONTHS cm  -- Shared temp table from Section 4B
  ON cm.REVENUE_CATEGORY = COALESCE(pv.REVENUE_CATEGORY, 'UNKNOWN');

-- Step 5: Build PACKAGE_EXPIRATION from registry (backward compatible with rest of pipeline)
CREATE OR REPLACE TABLE PACKAGE_EXPIRATION AS
SELECT 
  PACKAGE_ID,
  START_DATE,
  EXPIRATION_DATE,
  PACKAGE_DURATION_DAYS,
  CASE EXPIRATION_SOURCE
    WHEN 'TRUE' THEN 0
    WHEN 'IMPUTED' THEN 1
    WHEN 'FORCED' THEN 2
  END AS IS_IMPUTED
FROM PACKAGE_EXPIRATION_REGISTRY;

-- Step 6: Log what happened (for monitoring)
SELECT 
  'Registry update complete' AS status,
  (SELECT COUNT(*) FROM NEW_PACKAGES_NEEDING_EXPIRATION) AS new_packages_found,
  (SELECT COUNT(*) FROM NEW_PACKAGE_EXPIRATIONS_FINAL) AS new_packages_added_to_registry,
  COUNT(*) AS total_packages_in_registry
FROM PACKAGE_EXPIRATION_REGISTRY;

-- =============================================================================
-- END OF SECTION 4
-- =============================================================================

  

-- -----------------------------------------------------------------------------
-- 5) VISITS (enriched, deduped)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE TABLE VISITS_ENRICHED AS
WITH base AS (
  SELECT
    v.UNIQUE_VISIT_REF_NO,
    CONCAT(v.PAYMENT_REF_NO,'-',v.STUDIO_ID) AS PAYMENT_KEY,  -- FIX: Drop CLIENT_ID so recipient visits match buyer's package
    v.PAYMENT_REF_NO, v.STUDIO_ID,
    EARNED_REVENUE_ANALYTICS.CANON_STUDIO(v.STUDIO_NAME)     AS STUDIO_NAME,
    v.LOCATION_ID,
    EARNED_REVENUE_ANALYTICS.CANON_LOCATION(v.LOCATION_NAME) AS LOCATION_NAME,
    v.CLIENT_ID, cx.GLOBAL_CLIENT_KEY,
    v.CLASS_DATE AS VISIT_DATE,
    v.IS_CANCELLED, v.IS_MISSED,
    v.TYPE_GROUP_NAME,
    EARNED_REVENUE_ANALYTICS.NORMALIZE_CATEGORY(COALESCE(stm.SERVICE_TYPE, v.TYPE_GROUP_NAME, 'Other')) AS SERVICE_TYPE,  -- FIX: Normalize category names
    ROW_NUMBER() OVER (PARTITION BY v.UNIQUE_VISIT_REF_NO
                       ORDER BY NVL(v.IS_CANCELLED,1), NVL(v.IS_MISSED,1), v.CLASS_DATE, v.STUDIO_ID) AS rn
  FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_VISITS v
  LEFT JOIN SERVICE_TYPE_MAPPING stm ON v.TYPE_GROUP_NAME = stm.ORIGINAL_TYPE_GROUP_NAME
  LEFT JOIN CLIENT_XWALK cx ON cx.STUDIO_ID = v.STUDIO_ID AND cx.CLIENT_ID = v.CLIENT_ID
  WHERE v.CLASS_DATE IS NOT NULL
    AND (v.CLASSPASS_SOURCE = 0 OR v.CLASSPASS_SOURCE IS NULL)
    AND v.PAYMENT_REF_NO > 0
    AND v.PAYMENT_REF_NO IS NOT NULL
    -- FIX: Exclude Marin visits only if the package exists in Presidio (deduplication)
    AND NOT EXISTS (
      SELECT 1 
      FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS dup
      WHERE dup.PAYMENT_REF_NO = v.PAYMENT_REF_NO
        AND dup.CLIENT_ID = v.CLIENT_ID
        AND dup.STUDIO_NAME LIKE '%Presidio%'
        AND v.STUDIO_NAME LIKE '%Marin%'
        AND v.CLASS_DATE < '2025-04-24'
    )
)
SELECT * FROM base QUALIFY rn=1;

-- -----------------------------------------------------------------------------
-- 6) VISITS_LINKED — HARD then HARD_CROSS_STUDIO then SOFT_GLOBAL
--     + GLOBAL CAPACITY CAP (applies to ALL link types)
--     + EXCLUDE daily-pro-rata + Unlimited + immediate (e.g., Staff Class) from linking
--     + REGISTRY-AWARE: Frozen visits preserved, capacity adjusted
-- -----------------------------------------------------------------------------


CREATE OR REPLACE TABLE VISITS_LINKED AS
WITH

-- =========================================================================
-- REGISTRY: Pull frozen visits (these are LOCKED, never reassigned)
-- =========================================================================
frozen_visits AS (
  SELECT
    vlr.VISIT_ID       AS UNIQUE_VISIT_REF_NO,
    vlr.PAYMENT_KEY,
    vlr.PAYMENT_REF_NO,
    vlr.STUDIO_ID,
    vlr.STUDIO_NAME,
    vlr.LOCATION_ID,
    vlr.LOCATION_NAME,
    vlr.CLIENT_ID,
    vlr.GLOBAL_CLIENT_KEY,
    vlr.VISIT_DATE,
    0                   AS IS_CANCELLED,
    0                   AS IS_MISSED,
    ve.TYPE_GROUP_NAME,
    vlr.SERVICE_TYPE,
    vlr.PACKAGE_ID      AS UNIQUE_PACKAGE_ID_LNK,
    vlr.LINK_TYPE,
    vlr.LINK_RANK
  FROM VISIT_LINKING_REGISTRY vlr
  LEFT JOIN VISITS_ENRICHED ve ON ve.UNIQUE_VISIT_REF_NO = vlr.VISIT_ID
),

-- REGISTRY: Count frozen visits per package (reduces available capacity)
frozen_capacity_used AS (
  SELECT
    UNIQUE_PACKAGE_ID_LNK AS PACKAGE_ID,
    COUNT(*) AS FROZEN_VISIT_COUNT
  FROM frozen_visits
  GROUP BY UNIQUE_PACKAGE_ID_LNK
),

eligible_pkgs AS (
  SELECT
    bp.PACKAGE_ID,
    bp.UNIQUE_TRANSACTION_ID,
    bp.PAYMENT_REF_NO,
    bp.CLIENT_ID,
    bp.GLOBAL_CLIENT_KEY,
    bp.STUDIO_ID,
    bp.REVENUE_CATEGORY,
    bp.SALE_DATE,
    bp.PO_CAPACITY_COUNT,
    -- REGISTRY: Remaining capacity after frozen visits
    bp.PO_CAPACITY_COUNT - COALESCE(fcu.FROZEN_VISIT_COUNT, 0) AS REMAINING_CAPACITY
  FROM PRICING_PER_VISIT_UNIQ bp
  JOIN REVENUE_CATEGORY_RECOGNITION_TYPE rct
    ON rct.REVENUE_CATEGORY = EARNED_REVENUE_ANALYTICS.NORMALIZE_CATEGORY(bp.REVENUE_CATEGORY)
  LEFT JOIN frozen_capacity_used fcu ON fcu.PACKAGE_ID = bp.PACKAGE_ID
  WHERE bp.ITEM_TYPE = 'Pricing Option'
    AND COALESCE(bp.IS_DEPOSIT,0) = 0
    AND rct.RECOGNITION_TYPE = 'visits-based'
    AND COALESCE(bp.PO_CAPACITY_COUNT,0) > 0
    AND bp.PACKAGE_TYPE <> 'Unlimited'
    AND NOT REGEXP_LIKE(COALESCE(bp.PRODUCT_DESCRIPTION,''), '\\bbooks?\\b', 'i')
),

bp_ranked AS (
  SELECT
    ep.*,
    ROW_NUMBER() OVER (
      PARTITION BY ep.UNIQUE_TRANSACTION_ID
      ORDER BY ep.PO_CAPACITY_COUNT DESC, ep.PACKAGE_ID
    ) AS rn_bp
  FROM eligible_pkgs ep
  WHERE ep.REMAINING_CAPACITY > 0  -- REGISTRY: Skip fully-consumed packages
),

hard AS (
  SELECT
    v.UNIQUE_VISIT_REF_NO,
    v.PAYMENT_KEY,
    v.PAYMENT_REF_NO,
    v.STUDIO_ID,
    v.STUDIO_NAME,
    v.LOCATION_ID,
    v.LOCATION_NAME,
    v.CLIENT_ID,
    v.GLOBAL_CLIENT_KEY,
    v.VISIT_DATE,
    v.IS_CANCELLED,
    v.IS_MISSED,
    v.TYPE_GROUP_NAME,
    v.SERVICE_TYPE,
    b.PACKAGE_ID AS UNIQUE_PACKAGE_ID_LNK,
    'HARD' AS LINK_TYPE,
    0 AS LINK_RANK
  FROM VISITS_ENRICHED v
  JOIN bp_ranked b
    ON b.PAYMENT_REF_NO = v.PAYMENT_REF_NO  -- FIX: Match on PAYMENT_REF_NO + STUDIO_ID
   AND b.STUDIO_ID = v.STUDIO_ID            -- instead of composite key with CLIENT_ID
   AND b.rn_bp = 1                           -- so recipient visits link to buyer's package
  LEFT JOIN frozen_visits fv ON fv.UNIQUE_VISIT_REF_NO = v.UNIQUE_VISIT_REF_NO
  WHERE v.IS_CANCELLED = 0 AND v.IS_MISSED = 0
    AND fv.UNIQUE_VISIT_REF_NO IS NULL  -- REGISTRY: Skip frozen visits
),

hard_cross_studio AS (
  WITH candidates AS (
    SELECT
      v.UNIQUE_VISIT_REF_NO,
      v.PAYMENT_KEY,
      v.PAYMENT_REF_NO,
      v.STUDIO_ID,
      v.STUDIO_NAME,
      v.LOCATION_ID,
      v.LOCATION_NAME,
      v.CLIENT_ID,
      v.GLOBAL_CLIENT_KEY,
      v.VISIT_DATE,
      v.IS_CANCELLED,
      v.IS_MISSED,
      v.TYPE_GROUP_NAME,
      v.SERVICE_TYPE,
      ep.PACKAGE_ID AS UNIQUE_PACKAGE_ID_LNK,
      ep.REVENUE_CATEGORY,
      ep.SALE_DATE,
      ep.PO_CAPACITY_COUNT,
      CASE
        WHEN ep.REVENUE_CATEGORY = v.SERVICE_TYPE THEN 1
        WHEN EXISTS (
          SELECT 1
          FROM EARNED_REVENUE_ANALYTICS.CATEGORY_COMPATIBILITY_MAPPING ccm
          WHERE ccm.PACKAGE_CATEGORY = ep.REVENUE_CATEGORY
            AND ccm.COMPATIBLE_VISIT_TYPE = v.SERVICE_TYPE
            AND ccm.MATCH_PRIORITY = 2
        ) THEN 2
        ELSE 999
      END AS match_priority
    FROM VISITS_ENRICHED v
    JOIN eligible_pkgs ep
      ON ep.PAYMENT_REF_NO = v.PAYMENT_REF_NO           -- FIX: Use GLOBAL_CLIENT_KEY for
     AND ep.GLOBAL_CLIENT_KEY = v.GLOBAL_CLIENT_KEY      -- cross-studio matching (CLIENT_ID
     AND ep.STUDIO_ID != v.STUDIO_ID                     -- changes per studio). Exclude same-
    LEFT JOIN hard h                                     -- studio matches (handled by HARD).
      ON h.UNIQUE_VISIT_REF_NO = v.UNIQUE_VISIT_REF_NO
    LEFT JOIN frozen_visits fv ON fv.UNIQUE_VISIT_REF_NO = v.UNIQUE_VISIT_REF_NO
    WHERE h.UNIQUE_VISIT_REF_NO IS NULL
      AND fv.UNIQUE_VISIT_REF_NO IS NULL  -- REGISTRY: Skip frozen visits
      AND v.IS_CANCELLED = 0 AND v.IS_MISSED = 0
      AND ep.REMAINING_CAPACITY > 0  -- REGISTRY: Only packages with remaining capacity
      AND v.GLOBAL_CLIENT_KEY IS NOT NULL  -- Need email for cross-studio matching
  ),
  ranked AS (
    SELECT
      c.*,
      ROW_NUMBER() OVER (
        PARTITION BY c.UNIQUE_VISIT_REF_NO
        ORDER BY c.match_priority ASC,
                 c.PO_CAPACITY_COUNT DESC,
                 c.SALE_DATE DESC,
                 c.UNIQUE_PACKAGE_ID_LNK
      ) AS rn
    FROM candidates c
    WHERE c.match_priority < 999
  )
  SELECT
    UNIQUE_VISIT_REF_NO,
    PAYMENT_KEY,
    PAYMENT_REF_NO,
    STUDIO_ID,
    STUDIO_NAME,
    LOCATION_ID,
    LOCATION_NAME,
    CLIENT_ID,
    GLOBAL_CLIENT_KEY,
    VISIT_DATE,
    IS_CANCELLED,
    IS_MISSED,
    TYPE_GROUP_NAME,
    SERVICE_TYPE,
    UNIQUE_PACKAGE_ID_LNK,
    'HARD_CROSS_STUDIO' AS LINK_TYPE,
    0 AS LINK_RANK
  FROM ranked
  WHERE rn = 1
),

soft_candidates AS (
  SELECT
    v.UNIQUE_VISIT_REF_NO,
    v.PAYMENT_KEY,
    v.PAYMENT_REF_NO,
    v.STUDIO_ID,
    v.STUDIO_NAME,
    v.LOCATION_ID,
    v.LOCATION_NAME,
    v.CLIENT_ID,
    v.GLOBAL_CLIENT_KEY,
    v.VISIT_DATE,
    v.IS_CANCELLED,
    v.IS_MISSED,
    v.TYPE_GROUP_NAME,
    v.SERVICE_TYPE,
    ep.PACKAGE_ID AS CAND_PKG_ID,
    ep.STUDIO_ID  AS PKG_STUDIO_ID,
    ep.REVENUE_CATEGORY,
    ep.SALE_DATE,
    ep.PO_CAPACITY_COUNT,
    ep.REMAINING_CAPACITY,  -- REGISTRY: Use remaining capacity
    pe.START_DATE,
    pe.EXPIRATION_DATE,
    IFF(ep.STUDIO_ID = v.STUDIO_ID, 1, 0) AS is_same_studio,
    ABS(DATEDIFF(DAY, ep.SALE_DATE, v.VISIT_DATE)) AS sale_gap_days,
    CASE
      WHEN ep.REVENUE_CATEGORY = v.SERVICE_TYPE THEN 1
      WHEN EXISTS (
        SELECT 1
        FROM EARNED_REVENUE_ANALYTICS.CATEGORY_COMPATIBILITY_MAPPING ccm
        WHERE ccm.PACKAGE_CATEGORY = ep.REVENUE_CATEGORY
          AND ccm.COMPATIBLE_VISIT_TYPE = v.SERVICE_TYPE
          AND ccm.MATCH_PRIORITY = 2
      ) THEN 2
      ELSE 999
    END AS match_priority
  FROM VISITS_ENRICHED v
  JOIN eligible_pkgs ep
    ON ep.GLOBAL_CLIENT_KEY = v.GLOBAL_CLIENT_KEY
  JOIN PACKAGE_EXPIRATION pe
    ON pe.PACKAGE_ID = ep.PACKAGE_ID
   AND v.VISIT_DATE BETWEEN pe.START_DATE AND pe.EXPIRATION_DATE
  LEFT JOIN hard h
    ON h.UNIQUE_VISIT_REF_NO = v.UNIQUE_VISIT_REF_NO
  LEFT JOIN hard_cross_studio hcs
    ON hcs.UNIQUE_VISIT_REF_NO = v.UNIQUE_VISIT_REF_NO
  LEFT JOIN frozen_visits fv ON fv.UNIQUE_VISIT_REF_NO = v.UNIQUE_VISIT_REF_NO
  WHERE h.UNIQUE_VISIT_REF_NO IS NULL
    AND hcs.UNIQUE_VISIT_REF_NO IS NULL
    AND fv.UNIQUE_VISIT_REF_NO IS NULL  -- REGISTRY: Skip frozen visits
    AND v.IS_CANCELLED = 0
    AND v.IS_MISSED = 0
    AND match_priority < 999
    AND ep.REMAINING_CAPACITY > 0  -- REGISTRY: Only packages with remaining capacity
),

soft_scored AS (
  SELECT
    sc.*,
    ROW_NUMBER() OVER (
      PARTITION BY sc.UNIQUE_VISIT_REF_NO
      ORDER BY sc.match_priority ASC,
               sc.is_same_studio DESC,
               sc.EXPIRATION_DATE ASC,
               sc.sale_gap_days ASC,
               sc.CAND_PKG_ID
    ) AS visit_preference_rank,
    ROW_NUMBER() OVER (
      PARTITION BY sc.CAND_PKG_ID
      ORDER BY sc.VISIT_DATE ASC,
               sc.match_priority ASC,
               sc.is_same_studio DESC,
               sc.UNIQUE_VISIT_REF_NO
    ) AS package_visit_sequence
  FROM soft_candidates sc
),

soft_assigned AS (
  SELECT
    ss.*,
    ROW_NUMBER() OVER (
      PARTITION BY ss.UNIQUE_VISIT_REF_NO
      ORDER BY ss.visit_preference_rank
    ) AS final_rank
  FROM soft_scored ss
  WHERE ss.package_visit_sequence <= ss.REMAINING_CAPACITY  -- REGISTRY: Use remaining capacity
),

soft AS (
  SELECT
    sa.UNIQUE_VISIT_REF_NO,
    sa.PAYMENT_KEY,
    sa.PAYMENT_REF_NO,
    sa.STUDIO_ID,
    sa.STUDIO_NAME,
    sa.LOCATION_ID,
    sa.LOCATION_NAME,
    sa.CLIENT_ID,
    sa.GLOBAL_CLIENT_KEY,
    sa.VISIT_DATE,
    sa.IS_CANCELLED,
    sa.IS_MISSED,
    sa.TYPE_GROUP_NAME,
    sa.SERVICE_TYPE,
    sa.CAND_PKG_ID AS UNIQUE_PACKAGE_ID_LNK,
    'SOFT_GLOBAL' AS LINK_TYPE,
    sa.visit_preference_rank AS LINK_RANK
  FROM soft_assigned sa
  WHERE sa.final_rank = 1
),

unioned AS (
  SELECT * FROM frozen_visits       -- REGISTRY: Frozen visits first (locked)
  UNION ALL
  SELECT * FROM hard
  UNION ALL
  SELECT * FROM hard_cross_studio
  UNION ALL
  SELECT * FROM soft
),

-- GLOBAL CAPACITY CAP (applies to ALL link types including frozen)
capped AS (
  SELECT
    u.*,
    ep_raw.PO_CAPACITY_COUNT,
    ROW_NUMBER() OVER (
      PARTITION BY u.UNIQUE_PACKAGE_ID_LNK
      ORDER BY
        -- REGISTRY: Frozen visits always win the capacity race
        CASE WHEN EXISTS (
          SELECT 1 FROM VISIT_LINKING_REGISTRY r WHERE r.VISIT_ID = u.UNIQUE_VISIT_REF_NO
        ) THEN 0 ELSE 1 END,
        u.VISIT_DATE ASC,
        CASE u.LINK_TYPE WHEN 'HARD' THEN 0 WHEN 'HARD_CROSS_STUDIO' THEN 1 ELSE 2 END,
        u.LINK_RANK,
        u.UNIQUE_VISIT_REF_NO
    ) AS pkg_visit_rank
  FROM unioned u
  JOIN (
    SELECT PACKAGE_ID, PO_CAPACITY_COUNT
    FROM PRICING_PER_VISIT_UNIQ
    WHERE ITEM_TYPE = 'Pricing Option'
      AND COALESCE(IS_DEPOSIT,0) = 0
      AND COALESCE(PO_CAPACITY_COUNT,0) > 0
      AND PACKAGE_TYPE <> 'Unlimited'
  ) ep_raw ON ep_raw.PACKAGE_ID = u.UNIQUE_PACKAGE_ID_LNK
)

SELECT
  UNIQUE_VISIT_REF_NO,
  PAYMENT_KEY,
  PAYMENT_REF_NO,
  STUDIO_ID,
  STUDIO_NAME,
  LOCATION_ID,
  LOCATION_NAME,
  CLIENT_ID,
  GLOBAL_CLIENT_KEY,
  VISIT_DATE,
  IS_CANCELLED,
  IS_MISSED,
  TYPE_GROUP_NAME,
  SERVICE_TYPE,
  UNIQUE_PACKAGE_ID_LNK,
  LINK_TYPE,
  LINK_RANK
FROM capped
WHERE pkg_visit_rank <= PO_CAPACITY_COUNT

QUALIFY ROW_NUMBER() OVER (
  PARTITION BY UNIQUE_VISIT_REF_NO
  ORDER BY CASE LINK_TYPE WHEN 'HARD' THEN 0 WHEN 'HARD_CROSS_STUDIO' THEN 1 ELSE 2 END,
           LINK_RANK,
           UNIQUE_PACKAGE_ID_LNK
) = 1;

-- -----------------------------------------------------------------------------
-- 7) Daily pro-rata tables (CLAMPED TO CURRENT_DATE)
-- -----------------------------------------------------------------------------
/* FIX: clamp at CURRENT_DATE() so we don't recognize future revenue */
CREATE OR REPLACE TABLE LIVESTREAM_DAILY AS
WITH seq AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) - 1 AS DAY_OFFSET FROM TABLE(GENERATOR(ROWCOUNT => 730)))
SELECT
  bp.PACKAGE_ID, bp.STUDIO_ID, bp.STUDIO_NAME, bp.LOCATION_ID, bp.LOCATION_NAME,
  bp.CLIENT_ID, bp.GLOBAL_CLIENT_KEY, bp.PRODUCT_DESCRIPTION, bp.PACKAGE_TYPE, bp.ITEM_TYPE,
  bp.REVENUE_CATEGORY,  -- FIX: Add REVENUE_CATEGORY
  bp.SALE_DATE AS PURCHASE_DATE,
  pe.START_DATE, pe.EXPIRATION_DATE, pe.PACKAGE_DURATION_DAYS,
  DATEADD(DAY, s.DAY_OFFSET, pe.START_DATE) AS REVENUE_DATE,
  CASE WHEN pe.PACKAGE_DURATION_DAYS>0 THEN bp.NET_PACKAGE_PRICE/pe.PACKAGE_DURATION_DAYS ELSE 0 END AS NET_DAILY_REVENUE,
  CASE WHEN pe.PACKAGE_DURATION_DAYS>0 THEN bp.UNIT_PRICE      /pe.PACKAGE_DURATION_DAYS ELSE 0 END AS GROSS_DAILY_REVENUE
FROM PRICING_PER_VISIT_UNIQ bp
JOIN PACKAGE_EXPIRATION pe ON pe.PACKAGE_ID = bp.PACKAGE_ID
JOIN REVENUE_CATEGORY_RECOGNITION_TYPE rct
  ON rct.REVENUE_CATEGORY = EARNED_REVENUE_ANALYTICS.NORMALIZE_CATEGORY(bp.REVENUE_CATEGORY)
JOIN seq s ON DATEADD(DAY, s.DAY_OFFSET, pe.START_DATE) <= LEAST(pe.EXPIRATION_DATE, CURRENT_DATE())
WHERE bp.ITEM_TYPE='Pricing Option'
  AND rct.RECOGNITION_TYPE = 'daily-pro-rata'  -- FIX: Use recognition type instead of IS_LIVESTREAM flag
  AND COALESCE(bp.IS_DEPOSIT,0)=0;

CREATE OR REPLACE TABLE LIVESTREAM_RECOGNIZED AS
SELECT PACKAGE_ID,
       SUM(NET_DAILY_REVENUE)   AS TOTAL_NET_LIVESTREAM_RECOGNIZED,
       SUM(GROSS_DAILY_REVENUE) AS TOTAL_GROSS_LIVESTREAM_RECOGNIZED
FROM LIVESTREAM_DAILY
GROUP BY PACKAGE_ID;

-- FIX ISSUE #4: Improved unlimited package detection
CREATE OR REPLACE TABLE UNLIMITED_DAILY AS
WITH seq AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) - 1 AS DAY_OFFSET FROM TABLE(GENERATOR(ROWCOUNT => 730)))
SELECT
  bp.PACKAGE_ID, bp.STUDIO_ID, bp.STUDIO_NAME, bp.LOCATION_ID, bp.LOCATION_NAME,
  bp.CLIENT_ID, bp.GLOBAL_CLIENT_KEY, bp.PRODUCT_DESCRIPTION, bp.PACKAGE_TYPE, bp.ITEM_TYPE,
  bp.REVENUE_CATEGORY,  -- FIX: Add REVENUE_CATEGORY
  bp.SALE_DATE AS PURCHASE_DATE,
  pe.START_DATE, pe.EXPIRATION_DATE, pe.PACKAGE_DURATION_DAYS,
  DATEADD(DAY, s.DAY_OFFSET, pe.START_DATE) AS REVENUE_DATE,
  CASE WHEN pe.PACKAGE_DURATION_DAYS>0 THEN bp.NET_PACKAGE_PRICE/pe.PACKAGE_DURATION_DAYS ELSE 0 END AS NET_DAILY_REVENUE,
  CASE WHEN pe.PACKAGE_DURATION_DAYS>0 THEN bp.UNIT_PRICE      /pe.PACKAGE_DURATION_DAYS ELSE 0 END AS GROSS_DAILY_REVENUE
FROM PRICING_PER_VISIT_UNIQ bp
JOIN PACKAGE_EXPIRATION pe ON pe.PACKAGE_ID = bp.PACKAGE_ID
JOIN seq s ON DATEADD(DAY, s.DAY_OFFSET, pe.START_DATE) <= LEAST(pe.EXPIRATION_DATE, CURRENT_DATE())  -- FIX
WHERE bp.ITEM_TYPE='Pricing Option'
  AND bp.IS_UNLIMITED_LIKE = 1  -- FIX: Better unlimited detection
  AND COALESCE(bp.IS_LIVESTREAM,0)=0
  AND COALESCE(bp.IS_DEPOSIT,0)=0;

CREATE OR REPLACE TABLE UNLIMITED_RECOGNIZED AS
SELECT PACKAGE_ID,
       SUM(NET_DAILY_REVENUE)   AS TOTAL_NET_UNLIMITED_RECOGNIZED,
       SUM(GROSS_DAILY_REVENUE) AS TOTAL_GROSS_UNLIMITED_RECOGNIZED
FROM UNLIMITED_DAILY
GROUP BY PACKAGE_ID;

-- -----------------------------------------------------------------------------
-- 8) Usage totals (finite only)
-- -----------------------------------------------------------------------------

CREATE OR REPLACE TABLE USAGE_TOTALS AS
WITH used_once AS (
  SELECT DISTINCT 
    vl.UNIQUE_PACKAGE_ID_LNK AS PACKAGE_ID, 
    vl.UNIQUE_VISIT_REF_NO,
    vl.SERVICE_TYPE  -- FIX ISSUE #7: Capture service type from actual visits
  FROM VISITS_LINKED vl
  JOIN PRICING_PER_VISIT_UNIQ bp ON bp.PACKAGE_ID = vl.UNIQUE_PACKAGE_ID_LNK
  WHERE vl.IS_CANCELLED = 0 
    AND vl.IS_MISSED = 0
    AND COALESCE(bp.IS_LIVESTREAM,0) = 0
    AND (bp.ORIGINAL_PO_CAPACITY_COUNT > 0 OR bp.ORIGINAL_PO_CAPACITY_COUNT IS NULL)  -- Include NULL
    AND COALESCE(bp.IS_DEPOSIT,0) = 0
),
visit_counts AS (
  SELECT 
    PACKAGE_ID,
    COUNT(*) as total_visits
  FROM used_once
  GROUP BY PACKAGE_ID
)
SELECT
  u.PACKAGE_ID,
  -- FIX: Calculate used revenue dynamically for NULL capacity packages
  SUM(
    CASE 
      WHEN COALESCE(bp.NET_REVENUE_PER_VISIT,0) > 0 THEN bp.NET_REVENUE_PER_VISIT
      WHEN bp.ORIGINAL_PO_CAPACITY_COUNT IS NULL AND vc.total_visits > 0 
        THEN bp.NET_PACKAGE_PRICE / vc.total_visits
      ELSE 0
    END
  ) AS TOTAL_NET_USED,
  SUM(
    CASE 
      WHEN COALESCE(bp.GROSS_REVENUE_PER_VISIT,0) > 0 THEN bp.GROSS_REVENUE_PER_VISIT
      WHEN bp.ORIGINAL_PO_CAPACITY_COUNT IS NULL AND vc.total_visits > 0 
        THEN bp.UNIT_PRICE / vc.total_visits
      ELSE 0
    END
  ) AS TOTAL_GROSS_USED,
  COUNT(*) AS SESSIONS_USED_COUNT,
  ANY_VALUE(u.SERVICE_TYPE) AS PRIMARY_SERVICE_TYPE  -- FIX: Use service type from visits
FROM used_once u
JOIN PRICING_PER_VISIT_UNIQ bp ON bp.PACKAGE_ID = u.PACKAGE_ID
LEFT JOIN visit_counts vc ON vc.PACKAGE_ID = u.PACKAGE_ID
GROUP BY u.PACKAGE_ID;

-- -----------------------------------------------------------------------------
-- 9) DAILY EVENTS — canonical ledger (aligned schema, 32 columns)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE TABLE EARNED_REVENUE_ANALYTICS.DAILY_REVENUE_AND_SALES_DETAIL AS
WITH item_map AS (
  SELECT
    fsd.SALE_DATE,
    fsd.STUDIO_ID, fsd.STUDIO_NAME,
    fsd.LOCATION_ID, fsd.LOCATION_NAME,
    fsd.PRODUCT_ID, fsd.PRODUCT_DESCRIPTION,
    fsd.CATEGORY_ID, fsd.REVENUE_CATEGORY,
    fsd.ITEM_TYPE,
    COALESCE(fsd.QUANTITY,1) AS QUANTITY,

    /* NET = cash + redemptions (your canonical definition elsewhere) */
    (COALESCE(fsd.NET_CASH_ON_HAND,0) + COALESCE(fsd.ACCOUNT_AND_GIFT_REDEMPTION_AMOUNT,0)) AS NET_TOTAL_SALES,
    COALESCE(fsd.NET_CASH_ON_HAND,0) AS NET_CASH_ONLY,
    COALESCE(fsd.ACCOUNT_AND_GIFT_REDEMPTION_AMOUNT,0) AS REDEEMED_FROM_GC_OR_ACCOUNT,

    /* GROSS = gross unit price * qty (pre-discount) */
    (COALESCE(fsd.GROSS_UNIT_PRICE, fsd.UNIT_PRICE, 0) * COALESCE(fsd.QUANTITY,1)) AS GROSS_TOTAL_SALES,

    /* Discounts/tax (keep signs consistent with rest of model) */
    (COALESCE(fsd.DISCOUNT_AMT_LOCAL,0)) AS TOTAL_DISCOUNTS,
    COALESCE(fsd.ITEMTAX_LOCAL,0) AS TAX_LOCAL,

    fsd.IS_RETURN,
    CASE
      WHEN fsd.ITEM_TYPE = 'Retail Product' THEN 'RETAIL'
      WHEN fsd.ITEM_TYPE = 'Prepaid Giftcard' THEN 'GIFT_SALE'
      WHEN fsd.ITEM_TYPE = 'Account' THEN 'ACCOUNT_TOPUP'
      WHEN fsd.REVENUE_CATEGORY ILIKE '%fee%' OR fsd.PRODUCT_DESCRIPTION ILIKE '%fee%' THEN 'FEE'
      ELSE 'OTHER'
    END AS bucket
  FROM PLAYLIST_DATAMART.MINDBODY_REPORTING_ANALYTICS.MART_SALES_DETAILS fsd
  WHERE fsd.ITEM_TYPE NOT IN ('Pricing Option')
     OR fsd.ITEM_TYPE IS NULL
),

/* Finite (non-livestream, capacity > 0, non-deposit) packages */
/* FIX: Use ORIGINAL_PO_CAPACITY_COUNT and treat NULL as valid (will link visits) */
finite_packages AS (
  SELECT bp.*
  FROM PRICING_PER_VISIT_UNIQ bp
  JOIN REVENUE_CATEGORY_RECOGNITION_TYPE rct
    ON rct.REVENUE_CATEGORY = EARNED_REVENUE_ANALYTICS.NORMALIZE_CATEGORY(bp.REVENUE_CATEGORY)
  WHERE bp.ITEM_TYPE = 'Pricing Option'
    AND rct.RECOGNITION_TYPE = 'visits-based'  -- FIX: Only visits-based packages create usage events
    AND (bp.ORIGINAL_PO_CAPACITY_COUNT > 0 OR bp.ORIGINAL_PO_CAPACITY_COUNT IS NULL)
    AND bp.PACKAGE_TYPE != 'Unlimited'
    AND COALESCE(bp.IS_DEPOSIT,0) = 0
    AND NOT REGEXP_LIKE(COALESCE(bp.PRODUCT_DESCRIPTION,''), '\\bbooks?\\b', 'i')
),

/* Only link visits to finite packages */
visits_linked_clean AS (
  SELECT vl.*
  FROM VISITS_LINKED vl
  JOIN finite_packages fp
    ON fp.PACKAGE_ID = vl.UNIQUE_PACKAGE_ID_LNK
  WHERE vl.IS_CANCELLED = 0
    AND vl.IS_MISSED = 0
),

/* Purchases of pricing options (non-livestream); staff comps immediate; deposits excluded here */
purchase_pricing_option AS (
  SELECT
    DATE_TRUNC('day', bp.SALE_DATE)                 AS EVENT_DATE,
    'Purchase'                                      AS EVENT_TYPE,
    bp.STUDIO_ID, bp.STUDIO_NAME, bp.LOCATION_ID, bp.LOCATION_NAME,
    COALESCE(bp.REVENUE_CATEGORY, 'Pricing Option') AS SERVICE_TYPE,
    'Pricing Option'                                AS ITEM_TYPE,
    bp.REVENUE_CATEGORY,
    bp.SALE_DATE                                    AS PURCHASE_DATE,
    bp.IS_OLD_MIGHTY,
    bp.PACKAGE_ID                                   AS UNIQUE_TRANSACTION_ID,

    /* Recognition type override: description (“books”) first, then category mapping */
    CASE 
      WHEN COALESCE(
        IFF(REGEXP_LIKE(COALESCE(bp.PRODUCT_DESCRIPTION,''), '\\bbooks?\\b', 'i'), 'immediate', NULL),
        rct.RECOGNITION_TYPE,
        'visits-based'
      ) = 'immediate' THEN 0
      WHEN COALESCE(bp.IS_DEPOSIT,0)=0 THEN bp.DEFERRED_REVENUE 
      ELSE 0 
    END AS DEFERRED_REVENUE_CHANGE,

    CASE 
      WHEN COALESCE(
        IFF(REGEXP_LIKE(COALESCE(bp.PRODUCT_DESCRIPTION,''), '\\bbooks?\\b', 'i'), 'immediate', NULL),
        rct.RECOGNITION_TYPE,
        'visits-based'
      ) = 'immediate' THEN bp.UNIT_PRICE
      ELSE 0
    END AS GROSS_EARNED_REVENUE,

    CASE 
      WHEN COALESCE(
        IFF(REGEXP_LIKE(COALESCE(bp.PRODUCT_DESCRIPTION,''), '\\bbooks?\\b', 'i'), 'immediate', NULL),
        rct.RECOGNITION_TYPE,
        'visits-based'
      ) = 'immediate'
        THEN (bp.NET_CASH_ON_HAND + bp.ACCOUNT_AND_GIFT_REDEMPTION_AMOUNT)
      ELSE 0
    END AS NET_EARNED_REVENUE,

    0::NUMBER AS GROSS_BREAKAGE_REVENUE,
    0::NUMBER AS NET_BREAKAGE_REVENUE,
    bp.UNIT_PRICE AS GROSS_TOTAL_SALES,
    (bp.NET_CASH_ON_HAND + bp.ACCOUNT_AND_GIFT_REDEMPTION_AMOUNT) AS NET_TOTAL_SALES,
    bp.DISCOUNT_AMT_LOCAL AS TOTAL_DISCOUNTS,
    bp.UNIT_PRICE AS GROSS_SESSION_SALES,
    (bp.NET_CASH_ON_HAND + bp.ACCOUNT_AND_GIFT_REDEMPTION_AMOUNT) AS NET_SESSION_SALES,
    0::NUMBER AS GROSS_RETAIL_SALES,
    0::NUMBER AS NET_RETAIL_SALES,
    0::NUMBER AS GROSS_GIFTCARD_SALES,
    0::NUMBER AS NET_GIFTCARD_SALES,

    /* Sessions sold should be 0 for immediate “books” pricing options */
    CASE
      WHEN REGEXP_LIKE(COALESCE(bp.PRODUCT_DESCRIPTION,''), '\\bbooks?\\b', 'i') THEN 0
      ELSE COALESCE(bp.PO_CAPACITY_COUNT,0)
    END AS SESSIONS_SOLD,

    0::NUMBER AS RETAIL_ITEMS_SOLD,
    0::NUMBER AS SESSIONS_USED,
    0::NUMBER AS NUM_VISITS,
    CAST(NULL AS STRING) AS UNIQUE_VISIT_REF_NO,
    (0 - bp.ACCOUNT_AND_GIFT_REDEMPTION_AMOUNT) AS GIFT_LIABILITY_CHANGE,
    bp.IS_RETURN,
    0::NUMBER AS IS_IMPUTED

  FROM PRICING_PER_VISIT_UNIQ bp
  LEFT JOIN REVENUE_CATEGORY_RECOGNITION_TYPE rct
  ON rct.REVENUE_CATEGORY = EARNED_REVENUE_ANALYTICS.NORMALIZE_CATEGORY(bp.REVENUE_CATEGORY)
  WHERE bp.ITEM_TYPE = 'Pricing Option'
    AND COALESCE(bp.IS_DEPOSIT, 0) = 0
),

/* Retail / Fees / Giftcards / Account topups */
purchase_retail AS (
  SELECT
    DATE_TRUNC('day', m.SALE_DATE) AS EVENT_DATE,
    'Purchase' AS EVENT_TYPE,
    m.STUDIO_ID, m.STUDIO_NAME, m.LOCATION_ID, m.LOCATION_NAME,
    'Retail' AS SERVICE_TYPE,
    'Retail Product' AS ITEM_TYPE,
    CAST(NULL AS STRING) AS REVENUE_CATEGORY,
    m.SALE_DATE AS PURCHASE_DATE,
    0::NUMBER AS IS_OLD_MIGHTY,
    CAST(NULL AS STRING) AS UNIQUE_TRANSACTION_ID,
    0::NUMBER AS DEFERRED_REVENUE_CHANGE,

    m.GROSS_TOTAL_SALES AS GROSS_EARNED_REVENUE,
    m.NET_TOTAL_SALES   AS NET_EARNED_REVENUE,

    0::NUMBER AS GROSS_BREAKAGE_REVENUE,
    0::NUMBER AS NET_BREAKAGE_REVENUE,

    m.GROSS_TOTAL_SALES AS GROSS_TOTAL_SALES,
    m.NET_TOTAL_SALES   AS NET_TOTAL_SALES,

    m.TOTAL_DISCOUNTS   AS TOTAL_DISCOUNTS,

    0::NUMBER AS GROSS_SESSION_SALES,
    0::NUMBER AS NET_SESSION_SALES,

    m.GROSS_TOTAL_SALES AS GROSS_RETAIL_SALES,
    m.NET_TOTAL_SALES   AS NET_RETAIL_SALES,

    0::NUMBER AS GROSS_GIFTCARD_SALES,
    0::NUMBER AS NET_GIFTCARD_SALES,

    0::NUMBER AS SESSIONS_SOLD,
    m.QUANTITY AS RETAIL_ITEMS_SOLD,
    0::NUMBER AS SESSIONS_USED,
    0::NUMBER AS NUM_VISITS,
    CAST(NULL AS STRING) AS UNIQUE_VISIT_REF_NO,
    (0 - m.REDEEMED_FROM_GC_OR_ACCOUNT) AS GIFT_LIABILITY_CHANGE,
    m.IS_RETURN,
    0::NUMBER AS IS_IMPUTED
  FROM item_map m WHERE m.bucket = 'RETAIL'
),

purchase_fees AS (
  SELECT
    DATE_TRUNC('day', m.SALE_DATE) AS EVENT_DATE,
    'Purchase'                     AS EVENT_TYPE,
    m.STUDIO_ID, m.STUDIO_NAME, m.LOCATION_ID, m.LOCATION_NAME,
    'Fees'                         AS SERVICE_TYPE,
    'Other'                        AS ITEM_TYPE,
    m.REVENUE_CATEGORY             AS REVENUE_CATEGORY,
    m.SALE_DATE                    AS PURCHASE_DATE,
    0::NUMBER                      AS IS_OLD_MIGHTY,
    CAST(NULL AS STRING)           AS UNIQUE_TRANSACTION_ID,
    0::NUMBER                      AS DEFERRED_REVENUE_CHANGE,
    m.GROSS_TOTAL_SALES            AS GROSS_EARNED_REVENUE,
    m.NET_TOTAL_SALES              AS NET_EARNED_REVENUE,
    0::NUMBER                      AS GROSS_BREAKAGE_REVENUE,
    0::NUMBER                      AS NET_BREAKAGE_REVENUE,
    m.GROSS_TOTAL_SALES            AS GROSS_TOTAL_SALES,
    m.NET_TOTAL_SALES              AS NET_TOTAL_SALES,
    0::NUMBER                      AS TOTAL_DISCOUNTS,
    0::NUMBER                      AS GROSS_SESSION_SALES,
    0::NUMBER                      AS NET_SESSION_SALES,
    0::NUMBER                      AS GROSS_RETAIL_SALES,
    0::NUMBER                      AS NET_RETAIL_SALES,
    0::NUMBER                      AS GROSS_GIFTCARD_SALES,
    0::NUMBER                      AS NET_GIFTCARD_SALES,
    0::NUMBER                      AS SESSIONS_SOLD,
    0::NUMBER                      AS RETAIL_ITEMS_SOLD,
    0::NUMBER                      AS SESSIONS_USED,
    0::NUMBER                      AS NUM_VISITS,
    CAST(NULL AS STRING)           AS UNIQUE_VISIT_REF_NO,
    (0 - m.REDEEMED_FROM_GC_OR_ACCOUNT) AS GIFT_LIABILITY_CHANGE,
    m.IS_RETURN,
    0::NUMBER                      AS IS_IMPUTED
  FROM item_map m WHERE m.bucket = 'FEE'
),

purchase_giftcards AS (
  SELECT
    DATE_TRUNC('day', m.SALE_DATE) AS EVENT_DATE,
    'Purchase'                     AS EVENT_TYPE,
    m.STUDIO_ID, m.STUDIO_NAME, m.LOCATION_ID, m.LOCATION_NAME,
    'Gift Card'                    AS SERVICE_TYPE,
    'Prepaid Giftcard'             AS ITEM_TYPE,
    m.REVENUE_CATEGORY             AS REVENUE_CATEGORY,
    m.SALE_DATE                    AS PURCHASE_DATE,
    0::NUMBER                      AS IS_OLD_MIGHTY,
    CAST(NULL AS STRING)           AS UNIQUE_TRANSACTION_ID,
    0::NUMBER                      AS DEFERRED_REVENUE_CHANGE,
    0::NUMBER                      AS GROSS_EARNED_REVENUE,
    0::NUMBER                      AS NET_EARNED_REVENUE,
    0::NUMBER                      AS GROSS_BREAKAGE_REVENUE,
    0::NUMBER                      AS NET_BREAKAGE_REVENUE,
    m.NET_CASH_ONLY                AS GROSS_TOTAL_SALES,
    m.NET_CASH_ONLY                AS NET_TOTAL_SALES,
    0::NUMBER                      AS TOTAL_DISCOUNTS,
    0::NUMBER                      AS GROSS_SESSION_SALES,
    0::NUMBER                      AS NET_SESSION_SALES,
    0::NUMBER                      AS GROSS_RETAIL_SALES,
    0::NUMBER                      AS NET_RETAIL_SALES,
    m.NET_CASH_ONLY                AS GROSS_GIFTCARD_SALES,
    m.NET_CASH_ONLY                AS NET_GIFTCARD_SALES,
    0::NUMBER                      AS SESSIONS_SOLD,
    0::NUMBER                      AS RETAIL_ITEMS_SOLD,
    0::NUMBER                      AS SESSIONS_USED,
    0::NUMBER                      AS NUM_VISITS,
    CAST(NULL AS STRING)           AS UNIQUE_VISIT_REF_NO,
    m.NET_CASH_ONLY                AS GIFT_LIABILITY_CHANGE,
    m.IS_RETURN,
    0::NUMBER                      AS IS_IMPUTED
  FROM item_map m WHERE m.bucket = 'GIFT_SALE'
),

purchase_account_topups AS (
  SELECT
    DATE_TRUNC('day', m.SALE_DATE) AS EVENT_DATE,
    'Purchase'                     AS EVENT_TYPE,
    m.STUDIO_ID, m.STUDIO_NAME, m.LOCATION_ID, m.LOCATION_NAME,
    'Account Payment'              AS SERVICE_TYPE,
    'Account'                      AS ITEM_TYPE,
    m.REVENUE_CATEGORY             AS REVENUE_CATEGORY,
    m.SALE_DATE                    AS PURCHASE_DATE,
    0::NUMBER                      AS IS_OLD_MIGHTY,
    CAST(NULL AS STRING)           AS UNIQUE_TRANSACTION_ID,
    0::NUMBER                      AS DEFERRED_REVENUE_CHANGE,
    0::NUMBER                      AS GROSS_EARNED_REVENUE,
    0::NUMBER                      AS NET_EARNED_REVENUE,
    0::NUMBER                      AS GROSS_BREAKAGE_REVENUE,
    0::NUMBER                      AS NET_BREAKAGE_REVENUE,
    m.NET_CASH_ONLY                AS GROSS_TOTAL_SALES,
    m.NET_CASH_ONLY                AS NET_TOTAL_SALES,
    0::NUMBER                      AS TOTAL_DISCOUNTS,
    0::NUMBER                      AS GROSS_SESSION_SALES,
    0::NUMBER                      AS NET_SESSION_SALES,
    0::NUMBER                      AS GROSS_RETAIL_SALES,
    0::NUMBER                      AS NET_RETAIL_SALES,
    0::NUMBER                      AS GROSS_GIFTCARD_SALES,
    0::NUMBER                      AS NET_GIFTCARD_SALES,
    0::NUMBER                      AS SESSIONS_SOLD,
    0::NUMBER                      AS RETAIL_ITEMS_SOLD,
    0::NUMBER                      AS SESSIONS_USED,
    0::NUMBER                      AS NUM_VISITS,
    CAST(NULL AS STRING)           AS UNIQUE_VISIT_REF_NO,
    m.NET_CASH_ONLY                AS GIFT_LIABILITY_CHANGE,
    m.IS_RETURN,
    0::NUMBER                      AS IS_IMPUTED
  FROM item_map m WHERE m.bucket = 'ACCOUNT_TOPUP'
),

-- FIX ISSUE #6: Handle 'OTHER' bucket items (non-pricing-option miscellaneous items)
purchase_other AS (
  SELECT
    DATE_TRUNC('day', m.SALE_DATE) AS EVENT_DATE,
    'Purchase'                     AS EVENT_TYPE,
    m.STUDIO_ID, m.STUDIO_NAME, m.LOCATION_ID, m.LOCATION_NAME,
    'Other'                        AS SERVICE_TYPE,
    'Other'                        AS ITEM_TYPE,
    m.REVENUE_CATEGORY             AS REVENUE_CATEGORY,
    m.SALE_DATE                    AS PURCHASE_DATE,
    0::NUMBER                      AS IS_OLD_MIGHTY,
    CAST(NULL AS STRING)           AS UNIQUE_TRANSACTION_ID,
    0::NUMBER                      AS DEFERRED_REVENUE_CHANGE,
    m.NET_TOTAL_SALES              AS GROSS_EARNED_REVENUE,
    m.NET_TOTAL_SALES              AS NET_EARNED_REVENUE,
    0::NUMBER                      AS GROSS_BREAKAGE_REVENUE,
    0::NUMBER                      AS NET_BREAKAGE_REVENUE,
    m.NET_TOTAL_SALES              AS GROSS_TOTAL_SALES,
    m.NET_TOTAL_SALES              AS NET_TOTAL_SALES,
    0::NUMBER                      AS TOTAL_DISCOUNTS,
    0::NUMBER                      AS GROSS_SESSION_SALES,
    0::NUMBER                      AS NET_SESSION_SALES,
    0::NUMBER                      AS GROSS_RETAIL_SALES,
    0::NUMBER                      AS NET_RETAIL_SALES,
    0::NUMBER                      AS GROSS_GIFTCARD_SALES,
    0::NUMBER                      AS NET_GIFTCARD_SALES,
    0::NUMBER                      AS SESSIONS_SOLD,
    0::NUMBER                      AS RETAIL_ITEMS_SOLD,
    0::NUMBER                      AS SESSIONS_USED,
    0::NUMBER                      AS NUM_VISITS,
    CAST(NULL AS STRING)           AS UNIQUE_VISIT_REF_NO,
    (0 - m.REDEEMED_FROM_GC_OR_ACCOUNT) AS GIFT_LIABILITY_CHANGE,
    m.IS_RETURN,
    0::NUMBER                      AS IS_IMPUTED
  FROM item_map m WHERE m.bucket = 'OTHER'
),


/* Daily recognition events (clamped to today to avoid future over-recognition) */
livestream_daily_events AS (
  SELECT
    ld.REVENUE_DATE AS EVENT_DATE,
    'Livestream Daily' AS EVENT_TYPE,
    ld.STUDIO_ID, ld.STUDIO_NAME, ld.LOCATION_ID, ld.LOCATION_NAME,
    'Livestream' AS SERVICE_TYPE,
    'Pricing Option' AS ITEM_TYPE,
    ld.REVENUE_CATEGORY,  -- FIX: Use from LIVESTREAM_DAILY table
    ld.PURCHASE_DATE AS PURCHASE_DATE,
    0::NUMBER AS IS_OLD_MIGHTY,
    ld.PACKAGE_ID AS UNIQUE_TRANSACTION_ID,
    -1*ld.NET_DAILY_REVENUE AS DEFERRED_REVENUE_CHANGE,
    ld.GROSS_DAILY_REVENUE  AS GROSS_EARNED_REVENUE,
    ld.NET_DAILY_REVENUE    AS NET_EARNED_REVENUE,
    0::NUMBER AS GROSS_BREAKAGE_REVENUE,
    0::NUMBER AS NET_BREAKAGE_REVENUE,
    0::NUMBER AS GROSS_TOTAL_SALES,
    0::NUMBER AS NET_TOTAL_SALES,
    0::NUMBER AS TOTAL_DISCOUNTS,
    0::NUMBER AS GROSS_SESSION_SALES,
    0::NUMBER AS NET_SESSION_SALES,
    0::NUMBER AS GROSS_RETAIL_SALES,
    0::NUMBER AS NET_RETAIL_SALES,
    0::NUMBER AS GROSS_GIFTCARD_SALES,
    0::NUMBER AS NET_GIFTCARD_SALES,
    0::NUMBER AS SESSIONS_SOLD,
    0::NUMBER AS RETAIL_ITEMS_SOLD,
    0::NUMBER AS SESSIONS_USED,
    1::NUMBER AS NUM_VISITS,
    CAST(NULL AS STRING) AS UNIQUE_VISIT_REF_NO,
    0::NUMBER AS GIFT_LIABILITY_CHANGE,
    0::NUMBER AS IS_RETURN,
    0::NUMBER AS IS_IMPUTED
  FROM LIVESTREAM_DAILY ld
  WHERE ld.REVENUE_DATE <= CURRENT_DATE
),

unlimited_daily_events AS (
  SELECT
    udb.REVENUE_DATE AS EVENT_DATE,
    'Unlimited Daily' AS EVENT_TYPE,
    udb.STUDIO_ID, udb.STUDIO_NAME, udb.LOCATION_ID, udb.LOCATION_NAME,
    'Unlimited' AS SERVICE_TYPE,
    'Pricing Option' AS ITEM_TYPE,
    udb.REVENUE_CATEGORY,  -- FIX: Use from UNLIMITED_DAILY table
    udb.PURCHASE_DATE AS PURCHASE_DATE,
    0::NUMBER AS IS_OLD_MIGHTY,
    udb.PACKAGE_ID AS UNIQUE_TRANSACTION_ID,
    -1*udb.NET_DAILY_REVENUE AS DEFERRED_REVENUE_CHANGE,
    udb.GROSS_DAILY_REVENUE AS GROSS_EARNED_REVENUE,
    udb.NET_DAILY_REVENUE AS NET_EARNED_REVENUE,
    0::NUMBER AS GROSS_BREAKAGE_REVENUE,
    0::NUMBER AS NET_BREAKAGE_REVENUE,
    0::NUMBER AS GROSS_TOTAL_SALES,
    0::NUMBER AS NET_TOTAL_SALES,
    0::NUMBER AS TOTAL_DISCOUNTS,
    0::NUMBER AS GROSS_SESSION_SALES,
    0::NUMBER AS NET_SESSION_SALES,
    0::NUMBER AS GROSS_RETAIL_SALES,
    0::NUMBER AS NET_RETAIL_SALES,
    0::NUMBER AS GROSS_GIFTCARD_SALES,
    0::NUMBER AS NET_GIFTCARD_SALES,
    0::NUMBER AS SESSIONS_SOLD,
    0::NUMBER AS RETAIL_ITEMS_SOLD,
    0::NUMBER AS SESSIONS_USED,
    1::NUMBER AS NUM_VISITS,
    CAST(NULL AS STRING) AS UNIQUE_VISIT_REF_NO,
    0::NUMBER AS GIFT_LIABILITY_CHANGE,
    0::NUMBER AS IS_RETURN,
    0::NUMBER AS IS_IMPUTED
  FROM UNLIMITED_DAILY udb
  WHERE udb.REVENUE_DATE <= CURRENT_DATE
),

/* Usage recognition (finite only) */
/* FIX: For NULL capacity packages, calculate per-visit revenue dynamically */
usage_events AS (
  WITH used_once AS (
    SELECT DISTINCT UNIQUE_VISIT_REF_NO, UNIQUE_PACKAGE_ID_LNK AS PACKAGE_ID
    FROM visits_linked_clean
  ),
  -- Count total visits per package to calculate dynamic per-visit revenue for NULL capacity
  visit_counts AS (
    SELECT 
      PACKAGE_ID,
      COUNT(*) as total_visits
    FROM used_once
    GROUP BY PACKAGE_ID
  )
  SELECT
    ve.VISIT_DATE                       AS EVENT_DATE,
    'Usage'                             AS EVENT_TYPE,
    bp.STUDIO_ID, bp.STUDIO_NAME,
    bp.LOCATION_ID, bp.LOCATION_NAME,
    ve.SERVICE_TYPE,
    bp.ITEM_TYPE,
    bp.REVENUE_CATEGORY,  -- FIX: Use package's REVENUE_CATEGORY instead of NULL
    bp.SALE_DATE                        AS PURCHASE_DATE,
    bp.IS_OLD_MIGHTY,
    bp.PACKAGE_ID                       AS UNIQUE_TRANSACTION_ID,
    -- FIX: Calculate per-visit revenue dynamically for NULL capacity
    CASE 
      WHEN bp.NET_REVENUE_PER_VISIT > 0 THEN -bp.NET_REVENUE_PER_VISIT
      WHEN bp.ORIGINAL_PO_CAPACITY_COUNT IS NULL AND vc.total_visits > 0 
        THEN -bp.NET_PACKAGE_PRICE / vc.total_visits
      ELSE 0
    END AS DEFERRED_REVENUE_CHANGE,
    CASE 
      WHEN bp.GROSS_REVENUE_PER_VISIT > 0 THEN bp.GROSS_REVENUE_PER_VISIT
      WHEN bp.ORIGINAL_PO_CAPACITY_COUNT IS NULL AND vc.total_visits > 0 
        THEN bp.UNIT_PRICE / vc.total_visits
      ELSE 0
    END AS GROSS_EARNED_REVENUE,
    CASE 
      WHEN bp.NET_REVENUE_PER_VISIT > 0 THEN bp.NET_REVENUE_PER_VISIT
      WHEN bp.ORIGINAL_PO_CAPACITY_COUNT IS NULL AND vc.total_visits > 0 
        THEN bp.NET_PACKAGE_PRICE / vc.total_visits
      ELSE 0
    END AS NET_EARNED_REVENUE,
    0::NUMBER AS GROSS_BREAKAGE_REVENUE,
    0::NUMBER AS NET_BREAKAGE_REVENUE,
    0::NUMBER AS GROSS_TOTAL_SALES,
    0::NUMBER AS NET_TOTAL_SALES,
    0::NUMBER AS TOTAL_DISCOUNTS,
    0::NUMBER AS GROSS_SESSION_SALES,
    0::NUMBER AS NET_SESSION_SALES,
    0::NUMBER AS GROSS_RETAIL_SALES,
    0::NUMBER AS NET_RETAIL_SALES,
    0::NUMBER AS GROSS_GIFTCARD_SALES,
    0::NUMBER AS NET_GIFTCARD_SALES,
    0::NUMBER AS SESSIONS_SOLD,
    0::NUMBER AS RETAIL_ITEMS_SOLD,
    1::NUMBER AS SESSIONS_USED,
    1::NUMBER AS NUM_VISITS,
    u.UNIQUE_VISIT_REF_NO               AS UNIQUE_VISIT_REF_NO,
    0::NUMBER                           AS GIFT_LIABILITY_CHANGE,
    bp.IS_RETURN,
    0::NUMBER                           AS IS_IMPUTED
  FROM used_once u
  JOIN finite_packages bp ON bp.PACKAGE_ID = u.PACKAGE_ID
  JOIN VISITS_ENRICHED ve ON ve.UNIQUE_VISIT_REF_NO = u.UNIQUE_VISIT_REF_NO
  LEFT JOIN visit_counts vc ON vc.PACKAGE_ID = u.PACKAGE_ID
),

/* Expiration → Breakage (finite, non-livestream, non-deposit; only if residual > 0) */
expiration_events_agg AS (
  SELECT
    pe.EXPIRATION_DATE AS EVENT_DATE, 'Expiration' AS EVENT_TYPE,
    bp.STUDIO_ID, bp.STUDIO_NAME, bp.LOCATION_ID, bp.LOCATION_NAME,
    -- FIX ISSUE #7: Use PRIMARY_SERVICE_TYPE from usage, fallback to package metadata
    COALESCE(
      ut.PRIMARY_SERVICE_TYPE,
      bp.REVENUE_CATEGORY,
      CASE
        WHEN bp.PRODUCT_DESCRIPTION ILIKE '%machine%' OR bp.PRODUCT_DESCRIPTION ILIKE '%reformer%' THEN 'Machine'
        WHEN bp.PRODUCT_DESCRIPTION ILIKE '%private%' THEN 'Private'
        WHEN bp.PRODUCT_DESCRIPTION ILIKE '%teacher%training%' OR bp.PRODUCT_DESCRIPTION ILIKE '%TTT%' THEN 'Mighty Teacher Training'
        ELSE 'Unused Package'
      END
    ) AS SERVICE_TYPE,
    bp.ITEM_TYPE, 
    bp.REVENUE_CATEGORY,  -- FIX: Use package's REVENUE_CATEGORY instead of NULL
    bp.SALE_DATE AS PURCHASE_DATE, bp.IS_OLD_MIGHTY,
    bp.PACKAGE_ID AS UNIQUE_TRANSACTION_ID,
    -GREATEST(bp.DEFERRED_REVENUE - COALESCE(ut.TOTAL_NET_USED,0), 0) AS DEFERRED_REVENUE_CHANGE,
    0::NUMBER AS GROSS_EARNED_REVENUE,
    0::NUMBER AS NET_EARNED_REVENUE,
    GREATEST(bp.UNIT_PRICE - COALESCE(ut.TOTAL_GROSS_USED,0), 0) AS GROSS_BREAKAGE_REVENUE,
    GREATEST(bp.DEFERRED_REVENUE - COALESCE(ut.TOTAL_NET_USED,0), 0) AS NET_BREAKAGE_REVENUE,
    0::NUMBER AS GROSS_TOTAL_SALES, 0::NUMBER AS NET_TOTAL_SALES, 0::NUMBER AS TOTAL_DISCOUNTS,
    0::NUMBER AS GROSS_SESSION_SALES, 0::NUMBER AS NET_SESSION_SALES,
    0::NUMBER AS GROSS_RETAIL_SALES, 0::NUMBER AS NET_RETAIL_SALES,
    0::NUMBER AS GROSS_GIFTCARD_SALES, 0::NUMBER AS NET_GIFTCARD_SALES,
    0::NUMBER AS SESSIONS_SOLD, 0::NUMBER AS RETAIL_ITEMS_SOLD,
    0::NUMBER AS SESSIONS_USED, 0::NUMBER AS NUM_VISITS,
    CAST(NULL AS STRING) AS UNIQUE_VISIT_REF_NO,
    0::NUMBER AS GIFT_LIABILITY_CHANGE,
    bp.IS_RETURN,
    pe.IS_IMPUTED
  FROM PACKAGE_EXPIRATION pe
  JOIN finite_packages bp ON pe.PACKAGE_ID = bp.PACKAGE_ID
  LEFT JOIN USAGE_TOTALS ut ON ut.PACKAGE_ID = bp.PACKAGE_ID
  WHERE pe.EXPIRATION_DATE IS NOT NULL
    AND pe.EXPIRATION_DATE <= CURRENT_DATE
    AND (bp.DEFERRED_REVENUE - COALESCE(ut.TOTAL_NET_USED,0)) > 0
),

/* ClassPass */
classpass_events AS (
  SELECT
    r.START_DATE AS EVENT_DATE, 'ClassPass' AS EVENT_TYPE,
    CAST(NULL AS NUMBER) AS STUDIO_ID,
    EARNED_REVENUE_ANALYTICS.CANON_STUDIO(r.VENUE_FULL_NAME) AS STUDIO_NAME,
    CAST(NULL AS NUMBER) AS LOCATION_ID,
    CAST(NULL AS STRING) AS LOCATION_NAME,
    'ClassPass' AS SERVICE_TYPE, 'Pricing Option' AS ITEM_TYPE,
    CAST(NULL AS STRING) AS REVENUE_CATEGORY,
    r.START_DATE AS PURCHASE_DATE, 0::NUMBER AS IS_OLD_MIGHTY,
    CONCAT('CP_', TO_VARCHAR(r.RESERVATION_ID))::STRING AS UNIQUE_TRANSACTION_ID,
    0::NUMBER AS DEFERRED_REVENUE_CHANGE,
    r.RATE AS GROSS_EARNED_REVENUE,
    r.RATE AS NET_EARNED_REVENUE,
    0::NUMBER AS GROSS_BREAKAGE_REVENUE,
    0::NUMBER AS NET_BREAKAGE_REVENUE,
    r.RATE AS GROSS_TOTAL_SALES,
    r.RATE AS NET_TOTAL_SALES,
    0::NUMBER AS TOTAL_DISCOUNTS,
    0::NUMBER AS GROSS_SESSION_SALES,
    0::NUMBER AS NET_SESSION_SALES,
    0::NUMBER AS GROSS_RETAIL_SALES,
    0::NUMBER AS NET_RETAIL_SALES,
    0::NUMBER AS GROSS_GIFTCARD_SALES,
    0::NUMBER AS NET_GIFTCARD_SALES,
    0::NUMBER AS SESSIONS_SOLD,
    0::NUMBER AS RETAIL_ITEMS_SOLD,
    1::NUMBER AS SESSIONS_USED,
    1::NUMBER AS NUM_VISITS,
    CONCAT('CP_', TO_VARCHAR(r.RESERVATION_ID))::STRING AS UNIQUE_VISIT_REF_NO,
    0::NUMBER AS GIFT_LIABILITY_CHANGE,
    0::NUMBER AS IS_RETURN,
    0::NUMBER AS IS_IMPUTED
  FROM PLAYLIST_DATAMART.CLASSPASS_REPORTING_ANALYTICS.RESERVATIONS r
  WHERE r.START_DATE IS NOT NULL AND r.RATE > 0
)

SELECT
  EVENT_DATE, EVENT_TYPE, STUDIO_ID, STUDIO_NAME, LOCATION_ID, LOCATION_NAME,
  SERVICE_TYPE, ITEM_TYPE, REVENUE_CATEGORY, PURCHASE_DATE,
  MAX(IS_OLD_MIGHTY)                            AS IS_OLD_MIGHTY,
  SUM(DEFERRED_REVENUE_CHANGE)                  AS DEFERRED_REVENUE_CHANGE,
  SUM(GROSS_EARNED_REVENUE)                     AS GROSS_EARNED_REVENUE,
  SUM(NET_EARNED_REVENUE)                       AS NET_EARNED_REVENUE,
  SUM(GROSS_BREAKAGE_REVENUE)                   AS GROSS_BREAKAGE_REVENUE,
  SUM(NET_BREAKAGE_REVENUE)                     AS NET_BREAKAGE_REVENUE,
  SUM(GROSS_TOTAL_SALES)                        AS GROSS_TOTAL_SALES,
  SUM(NET_TOTAL_SALES)                          AS NET_TOTAL_SALES,
  SUM(TOTAL_DISCOUNTS)                          AS TOTAL_DISCOUNTS,
  SUM(GROSS_SESSION_SALES)                      AS GROSS_SESSION_SALES,
  SUM(NET_SESSION_SALES)                        AS NET_SESSION_SALES,
  SUM(GROSS_RETAIL_SALES)                       AS GROSS_RETAIL_SALES,
  SUM(NET_RETAIL_SALES)                         AS NET_RETAIL_SALES,
  SUM(GROSS_GIFTCARD_SALES)                     AS GROSS_GIFTCARD_SALES,
  SUM(NET_GIFTCARD_SALES)                       AS NET_GIFTCARD_SALES,
  SUM(SESSIONS_SOLD)                            AS SESSIONS_SOLD,
  SUM(RETAIL_ITEMS_SOLD)                        AS RETAIL_ITEMS_SOLD,
  SUM(SESSIONS_USED)                            AS SESSIONS_USED,
  SUM(NUM_VISITS)                               AS NUM_VISITS,
  COUNT(DISTINCT UNIQUE_VISIT_REF_NO)           AS DISTINCT_VISITS,
  SUM(GIFT_LIABILITY_CHANGE)                    AS GIFT_LIABILITY_CHANGE,
  MAX(IS_RETURN)                                AS IS_RETURN,
  MAX(IS_IMPUTED)                               AS IS_IMPUTED
FROM (
  SELECT * FROM purchase_pricing_option
  UNION ALL SELECT * FROM purchase_retail
  UNION ALL SELECT * FROM purchase_fees
  UNION ALL SELECT * FROM purchase_giftcards
  UNION ALL SELECT * FROM purchase_account_topups
  UNION ALL SELECT * FROM purchase_other  -- FIX: Include OTHER bucket
  UNION ALL SELECT * FROM livestream_daily_events
  UNION ALL SELECT * FROM unlimited_daily_events
  UNION ALL SELECT * FROM usage_events
  UNION ALL SELECT * FROM expiration_events_agg
  -- ClassPass excluded - tracked separately, not part of package revenue recognition
)
GROUP BY
  EVENT_DATE, EVENT_TYPE, STUDIO_ID, STUDIO_NAME, LOCATION_ID, LOCATION_NAME,
  SERVICE_TYPE, ITEM_TYPE, REVENUE_CATEGORY, PURCHASE_DATE
ORDER BY EVENT_DATE DESC, STUDIO_NAME, SERVICE_TYPE;

-- -----------------------------------------------------------------------------
-- 10) DAILY DEFERRED REVENUE BALANCE
-- -----------------------------------------------------------------------------
CREATE OR REPLACE TABLE DAILY_DEFERRED_REVENUE_BALANCE AS
SELECT
  EVENT_DATE,
  COALESCE(STUDIO_NAME,'Unknown') AS STUDIO_NAME,
  COALESCE(SERVICE_TYPE,'ALL') AS SERVICE_TYPE,
  SUM(DEFERRED_REVENUE_CHANGE) AS DAILY_DEFERRED_CHANGE,
  SUM(SUM(DEFERRED_REVENUE_CHANGE)) OVER (
    PARTITION BY COALESCE(STUDIO_NAME,'Unknown'), COALESCE(SERVICE_TYPE,'ALL')
    ORDER BY EVENT_DATE
  ) AS OUTSTANDING_DEFERRED_REVENUE
FROM DAILY_REVENUE_AND_SALES_DETAIL
WHERE DEFERRED_REVENUE_CHANGE <> 0
GROUP BY EVENT_DATE, COALESCE(STUDIO_NAME,'Unknown'), COALESCE(SERVICE_TYPE,'ALL')
ORDER BY EVENT_DATE, STUDIO_NAME, SERVICE_TYPE;

-- -----------------------------------------------------------------------------
-- 11) DIAGNOSTIC — Unmatched visits
-- -----------------------------------------------------------------------------
CREATE OR REPLACE TABLE EARNED_REVENUE_ANALYTICS.DIAGNOSTIC_UNMATCHED_VISITS_OPEN AS
WITH unmatched AS (
  SELECT v.*
  FROM VISITS_ENRICHED v
  LEFT JOIN VISITS_LINKED l ON l.UNIQUE_VISIT_REF_NO = v.UNIQUE_VISIT_REF_NO
  WHERE l.UNIQUE_VISIT_REF_NO IS NULL
)
SELECT *,
  CASE
    WHEN LOWER(TYPE_GROUP_NAME) LIKE '%cross%' OR LOWER(TYPE_GROUP_NAME) LIKE '%multi%' THEN 'Cross-region visit'
    WHEN IS_MISSED=1 OR IS_CANCELLED=1 THEN 'Missed/No-show or Cancelled'
    ELSE 'No matching sale found'
  END AS LIKELY_CAUSE
FROM unmatched;

-- -----------------------------------------------------------------------------
-- 12) VALIDATION (key checks)
-- -----------------------------------------------------------------------------
SELECT '===== VALIDATION =====' AS SECTION;

-- Livestream soft links (should be 0)
SELECT 'Livestream soft links' AS check_type, COUNT(*) AS count_value
FROM VISITS_LINKED vl
JOIN PRICING_PER_VISIT_UNIQ bp ON bp.PACKAGE_ID = vl.UNIQUE_PACKAGE_ID_LNK
WHERE bp.IS_LIVESTREAM=1 AND vl.LINK_TYPE='SOFT_GLOBAL';

-- Visits linked to livestream packages (should be 0)
SELECT 'Visits linked to livestream packages' AS check_type, COUNT(*) AS count_value
FROM VISITS_LINKED vl
JOIN PRICING_PER_VISIT_UNIQ bp ON bp.PACKAGE_ID = vl.UNIQUE_PACKAGE_ID_LNK
WHERE bp.IS_LIVESTREAM=1;

-- Revenue reconciliation (should be ~100% over long horizon)
WITH s AS (
  SELECT 
    SUM(CASE WHEN EVENT_TYPE='Purchase' AND ITEM_TYPE='Pricing Option' THEN GROSS_SESSION_SALES ELSE 0 END) AS total_session_sales,
    SUM(CASE WHEN EVENT_TYPE IN ('Usage','Livestream Daily','Unlimited Daily') THEN GROSS_EARNED_REVENUE ELSE 0 END) AS total_earned,
    SUM(GROSS_BREAKAGE_REVENUE) AS total_breakage
  FROM DAILY_REVENUE_AND_SALES_DETAIL
)
SELECT 'Revenue Balance' AS check_type,
       total_session_sales, total_earned, total_breakage,
       total_earned + total_breakage AS earned_plus_breakage,
       total_session_sales - (total_earned + total_breakage) AS difference,
       ROUND(100*(total_earned + total_breakage)/NULLIF(total_session_sales,0),2) AS recognition_pct
FROM s;

-- Package uniqueness
SELECT 'Package Uniqueness' AS check_type,
       COUNT(*) AS total_packages, COUNT(DISTINCT PACKAGE_ID) AS unique_packages,
       COUNT(*)-COUNT(DISTINCT PACKAGE_ID) AS duplicates
FROM PRICING_PER_VISIT
WHERE ITEM_TYPE='Pricing Option';

-- PACKAGE_EXPIRATION duplicates (should be 0)
SELECT 'Duplicate Package Expirations' AS check_type,
       COUNT(*)-COUNT(DISTINCT PACKAGE_ID) AS duplicates
FROM PACKAGE_EXPIRATION;

-- Capacity enforcement check (should be 0)
WITH package_usage AS (
  SELECT 
    bp.PACKAGE_ID,
    bp.PO_CAPACITY_COUNT,
    COUNT(DISTINCT vl.UNIQUE_VISIT_REF_NO) AS visits_linked
  FROM PRICING_PER_VISIT_UNIQ bp
  JOIN VISITS_LINKED vl ON vl.UNIQUE_PACKAGE_ID_LNK = bp.PACKAGE_ID
  WHERE bp.PO_CAPACITY_COUNT > 0
  GROUP BY 1, 2
)
SELECT 'Over-capacity packages' AS check_type,
       COUNT(*) AS count_value
FROM package_usage
WHERE visits_linked > PO_CAPACITY_COUNT;

-- Category duplicate check (should be 0)
SELECT 'Duplicate category mappings' AS check_type,
       COUNT(*) AS count_value
FROM (
  SELECT REVENUE_CATEGORY, COUNT(*) AS cnt
  FROM REVENUE_CATEGORY_RECOGNITION_TYPE
  GROUP BY REVENUE_CATEGORY
  HAVING COUNT(*) > 1
);

SELECT 'ALL DONE.' AS STATUS;





-- =============================================================================
-- POST-RUN CHECKS (Revenue Recognition / Expiration / Linking)
-- =============================================================================

SELECT '===== POST-RUN CHECKS =====' AS SECTION;

-- =============================================================================
-- POST-RUN VALIDATIONS (against EARNED_REVENUE_ANALYTICS.DAILY_REVENUE_AND_SALES_DETAIL)
-- =============================================================================


SELECT
  'Sessions-only recognition vs sessions-only sales' AS check_type,
  SUM(NET_SESSION_SALES) AS net_session_sales,
  SUM(CASE WHEN ITEM_TYPE='Pricing Option' THEN NET_EARNED_REVENUE ELSE 0 END) AS net_earned_sessions,
  SUM(CASE WHEN ITEM_TYPE='Pricing Option' THEN NET_BREAKAGE_REVENUE ELSE 0 END) AS net_breakage_sessions,
  SUM(CASE WHEN ITEM_TYPE='Pricing Option' THEN NET_EARNED_REVENUE + NET_BREAKAGE_REVENUE ELSE 0 END) AS earned_plus_breakage_sessions,
  SUM(CASE WHEN ITEM_TYPE='Pricing Option' THEN NET_EARNED_REVENUE + NET_BREAKAGE_REVENUE ELSE 0 END) - SUM(NET_SESSION_SALES) AS diff,
  100 * SUM(CASE WHEN ITEM_TYPE='Pricing Option' THEN NET_EARNED_REVENUE + NET_BREAKAGE_REVENUE ELSE 0 END) / NULLIF(SUM(NET_SESSION_SALES),0) AS pct
FROM EARNED_REVENUE_ANALYTICS.DAILY_REVENUE_AND_SALES_DETAIL;