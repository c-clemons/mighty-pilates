"""
MTT geographic reallocation policy.

Cat directive 2026-06-16: Mighty Teacher Training revenue follows session
location, not sale location.

  Marin (Bay Area sessions)    <- Berkeley, Lafayette, Russian Hill, Presidio Heights, Danville
  Westwood (LA sessions)       <- Culver City, Santa Monica, Ocean Park
  Santa Barbara                <- (own — sessions at Santa Barbara)

Applied to the LIVE Saasant and GL export paths. The frozen-read paths are
pure replays of whatever was originally emitted — they do NOT re-apply this
remap, so historical months (Feb-May 2026, closed before this policy) replay
exactly as posted to QuickBooks at the time.

For those prior months, a separate manual reclass JE was sent to Crew on
2026-06-16 (see scripts/mtt_reclass_2026.py + outputs/MTT_Reclass_*.xlsx).
"""

# Source studio -> destination studio (where the MTT session takes place)
MTT_STUDIO_REMAP = {
    "Mighty Pilates Berkeley":         "Mighty Pilates Marin",
    "Mighty Pilates Lafayette":        "Mighty Pilates Marin",
    "Mighty Pilates Russian Hill":     "Mighty Pilates Marin",
    "Mighty Pilates Presidio Heights": "Mighty Pilates Marin",
    "Mighty Pilates Danville":         "Mighty Pilates Marin",
    "Mighty Pilates Culver City":      "Mighty Pilates Westwood",
    "Mighty Pilates Santa Monica":     "Mighty Pilates Westwood",
    "Mighty Pilates Ocean Park":       "Mighty Pilates Westwood",
    # Identity entries — explicit so unmapped studios are obvious
    "Mighty Pilates Marin":            "Mighty Pilates Marin",
    "Mighty Pilates Westwood":         "Mighty Pilates Westwood",
    "Mighty Pilates Santa Barbara":    "Mighty Pilates Santa Barbara",
}

# GL codes affected by the remap (MTT earned revenue + MTT breakage)
MTT_GL_CODES = {"401004", "403002"}

# String matching against the BUCKET_NORM column in the live ledger path
MTT_BUCKET_NORM = "MIGHTY TEACHER TRAINING"


def remap_studio_by_bucket(df, studio_col: str = "STUDIO_NAME",
                          bucket_col: str = "BUCKET_NORM"):
    """
    Remap STUDIO_NAME on a copy of df for rows whose bucket is MTT.
    Used in the live (un-frozen) ledger path.

    Returns a new DataFrame.
    """
    out = df.copy()
    if bucket_col not in out.columns:
        return out
    is_mtt = out[bucket_col].astype(str).str.upper().str.strip() == MTT_BUCKET_NORM
    if not is_mtt.any():
        return out
    out.loc[is_mtt, studio_col] = (
        out.loc[is_mtt, studio_col]
           .map(MTT_STUDIO_REMAP)
           .fillna(out.loc[is_mtt, studio_col])
    )
    return out
