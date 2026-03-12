-- =============================================================================
-- HARD-CODED MEDIAN VALUES - FROZEN PERMANENTLY
-- =============================================================================
-- Based on data extracted on 2026-02-09
-- These values will NEVER change - this is the permanent baseline
-- =============================================================================

USE ROLE SYSADMIN;
USE WAREHOUSE COMPUTE_WH;
USE DATABASE MIGHTY_PILATES_ANALYTICS;
USE SCHEMA EARNED_REVENUE_ANALYTICS;

-- =============================================================================
-- TABLE 1: Product-Specific Medians (Products with ≥3 TRUE expirations)
-- =============================================================================

CREATE OR REPLACE TABLE CATEGORY_MEDIAN_BY_PRODUCT_DESCRIPTION_FROZEN AS
SELECT * FROM (VALUES
  -- Product-Specific Medians (from EXTRACT 1)
  ('Mighty Monthly Pass', 'Machine', 32, 14593),
  ('Founding Members MMP', 'Machine', 32, 2468),
  ('Mighty Monthly 12 Pass', 'Machine', 32, 1174),
  ('Student Mighty Monthly Pass', 'Student Mighty Monthly Pass', 32, 808),
  ('Mighty Monthly 8 Pass', 'Machine', 32, 668),
  ('Mini Mighty Monthly Pass', 'Machine', 32, 470),
  ('Ocean Park Founder''s 50 Mighty Monthly Pass', 'Machine', 32, 428),
  ('Mighty Monthly 15 Classes', 'Machine', 32, 280),
  ('Mighty Monthly 15 Pass', 'Machine', 32, 272),
  ('Russian Hill Founders MMP', 'Machine', 32, 253),
  ('Student Mighty Monthly Pass', 'Machine', 32, 190),
  ('Danville Founder''s 50 Mighty Monthly Pass', 'Machine', 32, 141),
  ('Pre-Opening Russian Hill MMP', 'Machine', 32, 136),
  ('Marin Founders MMP', 'Machine', 32, 102),
  ('Mighty Monthly Membership - Unlimited Livestream Classes', 'Livestream', 366, 93),
  ('Mini Mighty Monthly (5 classes)', 'Machine', 32, 92),
  ('MMP 20', 'Machine', 32, 88),
  ('Mighty Monthly 8 Privates Pass', 'Private', 32, 85),
  ('Mighty Monthly 20 Pass', 'Machine', 32, 58),
  ('Danville Founder''s 50 Mighty Monthly - First Month', 'Machine', 32, 47),
  ('Mighty Monthly 20 Pass', 'Machine', 32, 41),
  ('8 classes', 'Machine', 32, 36),
  ('Danville Founder''s 50 Mighty Monthly Pass', 'Machine', 32, 17),
  ('Danville Mini Mighty Monthly Pass', 'Machine', 32, 16),
  ('8 Machine Classes', 'Machine', 61.5, 4)
) AS t(PRODUCT_DESCRIPTION, REVENUE_CATEGORY, MEDIAN_DURATION_DAYS, SAMPLE_SIZE);

SELECT 'Product-specific medians loaded' AS status, COUNT(*) AS median_count 
FROM CATEGORY_MEDIAN_BY_PRODUCT_DESCRIPTION_FROZEN;

-- =============================================================================
-- TABLE 2: Revenue Category Fallback Medians
-- =============================================================================

CREATE OR REPLACE TABLE CATEGORY_MEDIAN_FALLBACK_FROZEN AS
SELECT * FROM (VALUES
  -- Calculated from TRUE expirations (from EXTRACT 2)
  ('Machine', 32, 21574, 'Calculated from TRUE expirations'),
  ('Student Mighty Monthly Pass', 32, 808, 'Calculated from TRUE expirations'),
  ('Livestream', 366, 93, 'Calculated from TRUE expirations'),
  ('Private', 180, 87, 'OVERRIDE: Conservative 180 days to prevent premature breakage'),
  
  -- Defaults for categories with NO TRUE expirations (from EXTRACT 3 + your assignments)
  ('Gympass Revenue', 32, 0, 'DEFAULT: No TRUE expirations'),
  ('Dynamic Pricing', 32, 0, 'DEFAULT: No TRUE expirations'),
  ('Semi-Private', 180, 0, 'DEFAULT: No TRUE expirations'),
  ('Private Rental', 180, 0, 'DEFAULT: No TRUE expirations - all privates 180'),
  ('Rental', 32, 0, 'DEFAULT: No TRUE expirations'),
  ('Online Classes', 32, 0, 'DEFAULT: No TRUE expirations'),
  ('New Client Special', 32, 0, 'DEFAULT: No TRUE expirations'),
  ('Mat Pilates - At Home', 32, 0, 'DEFAULT: No TRUE expirations'),
  ('At Pilates - At Home', 32, 0, 'DEFAULT: No TRUE expirations'),
  ('Workshop', 32, 0, 'DEFAULT: No TRUE expirations'),
  ('Mighty Teacher Training', 366, 0, 'DEFAULT: No TRUE expirations'),
  ('Staff Class', 32, 0, 'DEFAULT: No TRUE expirations'),
  ('Master Instructor Privates', 180, 0, 'DEFAULT: No TRUE expirations'),
  ('Trio', 180, 0, 'DEFAULT: No TRUE expirations'),
  ('Pilates Instructor Certification', 366, 0, 'DEFAULT: No TRUE expirations'),
  ('Pilates Pods', 32, 0, 'DEFAULT: No TRUE expirations'),
  ('Apprentice Sessions', 32, 0, 'DEFAULT: No TRUE expirations'),
  ('Apprentice Duet', 32, 0, 'DEFAULT: No TRUE expirations'),
  ('Online Privates', 180, 0, 'DEFAULT: No TRUE expirations'),
  ('Master Private Pilates', 180, 0, 'DEFAULT: No TRUE expirations'),
  ('Livestream Series', 32, 0, 'DEFAULT: No TRUE expirations'),
  ('Outdoor Mat Pilates', 32, 0, 'DEFAULT: No TRUE expirations'),
  ('Advanced Tower Workshop', 32, 0, 'DEFAULT: No TRUE expirations'),
  ('10 - Day Health Challenge', 32, 0, 'DEFAULT: No TRUE expirations'),
  ('Private Events', 180, 0, 'DEFAULT: No TRUE expirations - all privates 180'),
  ('Apprentice Private Pilates', 180, 0, 'DEFAULT: No TRUE expirations'),
  ('Balance Workshop', 32, 0, 'DEFAULT: No TRUE expirations'),
  
  -- Default for NULL/empty categories
  ('UNKNOWN', 180, 0, 'DEFAULT: For NULL/empty revenue categories')
) AS t(REVENUE_CATEGORY, MEDIAN_DURATION_DAYS, SAMPLE_SIZE, SOURCE);

SELECT 'Fallback medians loaded' AS status, COUNT(*) AS median_count 
FROM CATEGORY_MEDIAN_FALLBACK_FROZEN;

-- =============================================================================
-- VERIFICATION: Check coverage
-- =============================================================================

CREATE OR REPLACE TEMP TABLE package_median_strategy AS
SELECT 
  pv.PACKAGE_ID,
  pv.PRODUCT_DESCRIPTION,
  pv.REVENUE_CATEGORY,
  pe.IS_IMPUTED,
  CASE 
    WHEN pe.IS_IMPUTED = 0 THEN 'TRUE (no median needed)'
    WHEN cmd.PRODUCT_DESCRIPTION IS NOT NULL THEN 'Product-specific median'
    WHEN cmf.REVENUE_CATEGORY IS NOT NULL THEN 'Fallback: Revenue category median'
    WHEN COALESCE(pv.REVENUE_CATEGORY, 'UNKNOWN') = 'UNKNOWN' THEN 'Fallback: UNKNOWN default'
    ELSE 'ERROR: No median available!'
  END AS median_strategy,
  CASE
    WHEN pe.IS_IMPUTED = 0 THEN NULL
    WHEN cmd.PRODUCT_DESCRIPTION IS NOT NULL THEN cmd.MEDIAN_DURATION_DAYS
    WHEN cmf.REVENUE_CATEGORY IS NOT NULL THEN cmf.MEDIAN_DURATION_DAYS
    ELSE NULL
  END AS median_days_to_use
FROM PRICING_PER_VISIT_UNIQ pv
JOIN PACKAGE_EXPIRATION pe ON pe.PACKAGE_ID = pv.PACKAGE_ID
LEFT JOIN CATEGORY_MEDIAN_BY_PRODUCT_DESCRIPTION_FROZEN cmd 
  ON cmd.PRODUCT_DESCRIPTION = pv.PRODUCT_DESCRIPTION
LEFT JOIN CATEGORY_MEDIAN_FALLBACK_FROZEN cmf 
  ON cmf.REVENUE_CATEGORY = COALESCE(pv.REVENUE_CATEGORY, 'UNKNOWN')
WHERE pv.ITEM_TYPE = 'Pricing Option';

SELECT 
  '=== MEDIAN COVERAGE VERIFICATION ===' AS section,
  median_strategy,
  COUNT(*) AS package_count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct_of_total,
  CASE 
    WHEN median_strategy LIKE 'ERROR%' THEN '❌ PROBLEM!'
    ELSE '✅ OK'
  END AS status
FROM package_median_strategy
GROUP BY median_strategy
ORDER BY package_count DESC;

-- Show summary by median duration
SELECT 
  '=== MEDIAN DURATION DISTRIBUTION ===' AS section,
  median_days_to_use AS median_duration,
  COUNT(*) AS packages,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
FROM package_median_strategy
WHERE median_days_to_use IS NOT NULL
GROUP BY median_days_to_use
ORDER BY packages DESC;

-- =============================================================================
-- FINAL MESSAGE
-- =============================================================================

SELECT '
=============================================================================
HARD-CODED MEDIANS LOADED SUCCESSFULLY
=============================================================================

What was created:
1. CATEGORY_MEDIAN_BY_PRODUCT_DESCRIPTION_FROZEN (25 product-specific medians)
2. CATEGORY_MEDIAN_FALLBACK_FROZEN (33 fallback medians)

Coverage should show:
- 0% ERROR (all packages have medians)
- ~13% TRUE expirations (no median needed)
- ~2-3% Product-specific median
- ~84% Fallback median

These values are now FROZEN and will never change.

Next steps:
1. Verify coverage shows 0% ERROR
2. Review median duration distribution
3. If all looks good, proceed with registry implementation

' AS message;