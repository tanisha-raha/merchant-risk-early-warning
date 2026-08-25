"""Guards the row-level time split (DECISIONS.md D10): a continuing seller
can have rows in both train and test, which is only safe if nothing in the
feature matrix lets the model recognise *which* seller a row belongs to.
That requires two things, both checked here rather than just asserted:

1. No column literally identifies the seller.
2. No column is close to constant across a seller's own history -- a
   feature that's fixed per seller would function as a fingerprint just as
   effectively as an ID column, even without ever containing seller_id.

Reference numbers from the real feature table (checked during development,
`>=8` weeks of tenure so the rolling windows have had room to move):
`category` is constant for 80.6% of sellers (expected -- sellers rarely
shift category), the sparsest trend/acceleration columns top out around
33.5% (driven by shared zero-fill on shared missingness, see D11 -- not
identity), and every level column and `order_volume_*`/`tenure_weeks` sit
under 10%, most near 0%. The thresholds below sit comfortably above those
observed values with headroom, not tuned to just barely pass.
"""

from __future__ import annotations

from features import FEATURE_COLUMNS, build_features_from_raw

MAX_CONSTANT_SHARE = {
    "category": 0.90,  # legitimately slow-moving, not a fingerprint concern
}
DEFAULT_MAX_CONSTANT_SHARE = 0.60  # observed max elsewhere is ~33.5%
MIN_TENURE_WEEKS_FOR_CHECK = 8  # long enough for a 4-week rolling window to have moved


def test_no_seller_id_or_seller_key_in_feature_columns():
    assert "seller_id" not in FEATURE_COLUMNS
    assert "week" not in FEATURE_COLUMNS
    assert not any("seller_id" in col or col == "id" for col in FEATURE_COLUMNS)


def test_no_feature_is_a_seller_fingerprint(raw):
    features = build_features_from_raw(raw)
    multi_week = features.groupby("seller_id").filter(lambda g: len(g) >= MIN_TENURE_WEEKS_FOR_CHECK)
    assert multi_week["seller_id"].nunique() > 100, "sanity check: too few sellers to test meaningfully"

    offenders = []
    for col in FEATURE_COLUMNS:
        nunique = multi_week.groupby("seller_id")[col].nunique(dropna=False)
        const_share = (nunique <= 1).mean()
        limit = MAX_CONSTANT_SHARE.get(col, DEFAULT_MAX_CONSTANT_SHARE)
        if const_share > limit:
            offenders.append((col, const_share, limit))

    assert not offenders, (
        "feature(s) constant across a seller's full history often enough to act as a "
        f"seller fingerprint, which would break the row-level split's premise (DECISIONS.md D10): "
        f"{offenders}"
    )
