-- =============================================================================
-- VISIT LINKING REGISTRY — Freeze visit-to-package assignments for closed months
-- =============================================================================
-- Purpose: Prevent revenue drift in closed months by freezing visit-to-package
-- assignments. Same pattern as the Package Expiration Registry.
--
-- How it works:
-- 1. After month-end close, run the FREEZE section to lock assignments
-- 2. The main model checks the registry FIRST — frozen visits keep their assignment
-- 3. Only unfrozen visits (current/open months) compete in soft-linking
-- 4. Breakage uses frozen usage totals for closed-month packages
--
-- IMPORTANT: Run this AFTER running the main Revenue Recognition Model,
-- once you've verified the month's numbers are correct.
--
-- NOTE: Uses CREATE OR REPLACE (not INSERT) due to reader account restrictions.
-- Each freeze rebuilds the registry, preserving previously frozen months via UNION.
-- =============================================================================

USE ROLE SYSADMIN;
USE WAREHOUSE COMPUTE_WH;
USE DATABASE MIGHTY_PILATES_ANALYTICS;
USE SCHEMA EARNED_REVENUE_ANALYTICS;

-- =============================================================================
-- Set the month you want to freeze. Change this date each month.
-- Example: To freeze January 2026, set to '2026-01-31'
-- =============================================================================

SET FREEZE_MONTH_END = '2026-01-31';

-- =============================================================================
-- Preview what will be frozen
-- =============================================================================

SELECT
    'PREVIEW: Visits to freeze' AS action,
    COUNT(*) AS visit_count,
    COUNT(DISTINCT vl.UNIQUE_PACKAGE_ID_LNK) AS packages_affected,
    MIN(vl.VISIT_DATE) AS earliest_visit,
    MAX(vl.VISIT_DATE) AS latest_visit
FROM VISITS_LINKED vl
WHERE vl.VISIT_DATE <= $FREEZE_MONTH_END;

-- =============================================================================
-- Rebuild registry: previously frozen months + new month
-- =============================================================================

CREATE OR REPLACE TABLE VISIT_LINKING_REGISTRY AS

-- Preserve all previously frozen visits (from months BEFORE this freeze)
SELECT
    VISIT_ID,
    PACKAGE_ID,
    LINK_TYPE,
    LINK_RANK,
    VISIT_DATE,
    SERVICE_TYPE,
    STUDIO_ID,
    STUDIO_NAME,
    LOCATION_ID,
    LOCATION_NAME,
    CLIENT_ID,
    GLOBAL_CLIENT_KEY,
    PAYMENT_KEY,
    PAYMENT_REF_NO,
    FROZEN_THROUGH_DATE,
    FROZEN_AT
FROM VISIT_LINKING_REGISTRY
WHERE FROZEN_THROUGH_DATE < $FREEZE_MONTH_END

UNION ALL

-- Add new visits from the month being frozen (exclude any already frozen)
SELECT
    vl.UNIQUE_VISIT_REF_NO      AS VISIT_ID,
    vl.UNIQUE_PACKAGE_ID_LNK   AS PACKAGE_ID,
    vl.LINK_TYPE,
    vl.LINK_RANK,
    vl.VISIT_DATE,
    vl.SERVICE_TYPE,
    vl.STUDIO_ID,
    vl.STUDIO_NAME,
    vl.LOCATION_ID,
    vl.LOCATION_NAME,
    vl.CLIENT_ID,
    vl.GLOBAL_CLIENT_KEY,
    vl.PAYMENT_KEY,
    vl.PAYMENT_REF_NO,
    $FREEZE_MONTH_END           AS FROZEN_THROUGH_DATE,
    CURRENT_TIMESTAMP()         AS FROZEN_AT
FROM VISITS_LINKED vl
WHERE vl.VISIT_DATE <= $FREEZE_MONTH_END
  AND vl.UNIQUE_VISIT_REF_NO NOT IN (
    SELECT VISIT_ID FROM VISIT_LINKING_REGISTRY
    WHERE FROZEN_THROUGH_DATE < $FREEZE_MONTH_END
  );

-- =============================================================================
-- Verification
-- =============================================================================

SELECT
    'Freeze complete' AS status,
    COUNT(*) AS total_frozen_visits,
    COUNT(DISTINCT FROZEN_THROUGH_DATE) AS months_frozen
FROM VISIT_LINKING_REGISTRY;

-- Show frozen months summary
SELECT
    FROZEN_THROUGH_DATE,
    COUNT(*) AS frozen_visits,
    COUNT(DISTINCT PACKAGE_ID) AS frozen_packages,
    MIN(VISIT_DATE) AS earliest_visit,
    MAX(VISIT_DATE) AS latest_visit,
    MIN(FROZEN_AT) AS frozen_at
FROM VISIT_LINKING_REGISTRY
GROUP BY FROZEN_THROUGH_DATE
ORDER BY FROZEN_THROUGH_DATE;

-- Show link type distribution for frozen visits
SELECT
    FROZEN_THROUGH_DATE,
    LINK_TYPE,
    COUNT(*) AS visit_count
FROM VISIT_LINKING_REGISTRY
GROUP BY FROZEN_THROUGH_DATE, LINK_TYPE
ORDER BY FROZEN_THROUGH_DATE, LINK_TYPE;
