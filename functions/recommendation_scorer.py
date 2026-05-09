"""
TradeClaw — Agent Recommendation Scorer (Scheduled Cloud Function)
====================================================================
Schedule: Every 4 hours on trading days  (0 */4 * * 1-5)

This function:
  1. Finds all unscored agent_recommendations older than 24 hours
  2. Fetches the 1-day and 5-day forward returns from market_bars
  3. Scores each recommendation (correct direction → positive score)
  4. Updates the recommendation doc with the outcome
  5. Persists scoring metrics for observability
"""

import logging
from datetime import datetime, timezone, timedelta
import asyncio
import numpy as np

import asyncpg

from shared import get_db_pool, utc_now_iso

logger = logging.getLogger("tradeclaw.scorer")

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

# Minimum age before we try to score (wait for forward returns to exist)
MIN_AGE_HOURS = 24

# Forward return windows to compute (in hours)
FORWARD_WINDOWS = {
    "1d": 24,   # 1-day forward return
    "5d": 120,  # 5-day forward return (~5 trading days)
}

# Batch size for processing
SCORING_BATCH_SIZE = 100


# ─────────────────────────────────────────────
# SCORING LOGIC
# ─────────────────────────────────────────────

async def compute_forward_returns(
    conn: asyncpg.Connection,
    symbol: str,
    signal_time: datetime,
    signal_price: float,
) -> dict:
    """
    Compute forward returns for a given symbol at a specific signal time.
    """
    if not signal_price or signal_price <= 0:
        return {}

    results = {}

    for label, hours in FORWARD_WINDOWS.items():
        try:
            target_dt = signal_time + timedelta(hours=hours)

            # Find the closest bar to the target time (within a 2-hour window)
            window_start = target_dt - timedelta(hours=1)
            window_end = target_dt + timedelta(hours=1)

            query = """
                SELECT "close"
                FROM market_bars
                WHERE symbol = $1 AND timeframe = '1h'
                  AND timestamp >= $2 AND timestamp <= $3
                ORDER BY timestamp ASC
                LIMIT 1
            """
            
            row = await conn.fetchrow(query, symbol, window_start, window_end)

            if row:
                forward_price = row["close"]
                if forward_price and forward_price > 0:
                    fwd_return = (forward_price - signal_price) / signal_price
                    results[f"return_{label}"] = round(fwd_return, 6)
                    results[f"price_{label}"] = round(forward_price, 5)
            else:
                logger.debug(
                    f"No bar found for {symbol} near {target_dt.isoformat()} "
                    f"— market may have been closed"
                )

        except Exception as e:
            logger.warning(f"Error computing {label} return for {symbol}: {e}")

    return results


def score_recommendation(recommendation: dict, forward_returns: dict) -> dict:
    """
    Score a single agent recommendation based on forward returns.
    """
    signal = recommendation.get("direction", "").upper()
    if signal not in ("BUY", "SELL", "LONG", "SHORT"):
        return {"scored": True, "score_reason": "non_directional_signal"}

    is_long = signal in ("BUY", "LONG")

    scores = {}
    for window_label in FORWARD_WINDOWS:
        ret_key = f"return_{window_label}"
        if ret_key not in forward_returns:
            continue

        fwd_return = forward_returns[ret_key]

        # Direction match: positive return for long, negative for short
        direction_correct = (is_long and fwd_return > 0) or (not is_long and fwd_return < 0)
        signed_return = fwd_return if is_long else -fwd_return

        scores[f"direction_correct_{window_label}"] = direction_correct
        scores[f"signed_return_{window_label}"] = round(signed_return, 6)

    # Composite score: average of signed returns (if any)
    signed_returns = [
        v for k, v in scores.items() if k.startswith("signed_return_")
    ]
    composite = float(np.mean(signed_returns)) if signed_returns else 0.0

    return {
        "scored": True,
        "composite_score": round(composite, 6),
        **forward_returns,
        **scores,
    }


# ─────────────────────────────────────────────
# MAIN SCORING LOOP
# ─────────────────────────────────────────────

async def run_scorer() -> dict:
    """
    Scan all bots' agent_recommendations, score unscored ones with forward returns.
    Returns a summary report.
    """
    pool = await get_db_pool()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MIN_AGE_HOURS)

    report = {
        "timestamp": utc_now_iso(),
        "bots_scanned": 0,
        "recommendations_found": 0,
        "recommendations_scored": 0,
        "recommendations_skipped": 0,
        "errors": 0,
        "per_bot": {},
    }

    logger.info("═══ Agent Recommendation Scorer — Starting ═══")

    try:
        async with pool.acquire() as conn:
            # 1. Get bots
            bots = await conn.fetch("SELECT bot_id FROM bots")
            report["bots_scanned"] = len(bots)

            for bot in bots:
                bot_id = bot["bot_id"]
                bot_scored = 0
                bot_skipped = 0

                # 2. Get unscored recommendations older than cutoff
                recs = await conn.fetch(
                    """
                    SELECT * FROM agent_recommendations 
                    WHERE bot_id = $1 AND scored = FALSE AND timestamp < $2
                    LIMIT $3
                    """,
                    bot_id, cutoff, SCORING_BATCH_SIZE
                )
                
                report["recommendations_found"] += len(recs)

                for rec in recs:
                    try:
                        rec_dict = dict(rec)
                        symbol = rec_dict.get("symbol", "")
                        signal_time = rec_dict.get("timestamp")
                        signal_price = rec_dict.get("signal_price", 0.0)
                        rec_id = rec_dict.get("id")

                        if not symbol or not signal_time or not signal_price:
                            bot_skipped += 1
                            # Mark as scored to avoid re-processing
                            await conn.execute(
                                "UPDATE agent_recommendations SET scored = TRUE WHERE id = $1",
                                rec_id
                            )
                            continue

                        # Compute forward returns from market bars
                        forward_returns = await compute_forward_returns(
                            conn, symbol, signal_time, signal_price
                        )

                        if not forward_returns:
                            # No bars available yet — leave unscored for next run
                            bot_skipped += 1
                            continue

                        # Score the recommendation
                        outcome = score_recommendation(rec_dict, forward_returns)

                        # Update the PostgreSQL document
                        await conn.execute(
                            """
                            UPDATE agent_recommendations 
                            SET scored = $1, 
                                forward_return_1d = $2, 
                                forward_return_5d = $3
                            WHERE id = $4
                            """,
                            outcome.get("scored", True),
                            outcome.get("return_1d"),
                            outcome.get("return_5d"),
                            rec_id
                        )
                        bot_scored += 1

                    except Exception as e:
                        logger.error(f"Error scoring {bot_id}/{rec['id']}: {e}")
                        report["errors"] += 1

                report["recommendations_scored"] += bot_scored
                report["recommendations_skipped"] += bot_skipped

                if bot_scored > 0 or bot_skipped > 0:
                    report["per_bot"][bot_id] = {
                        "scored": bot_scored,
                        "skipped": bot_skipped,
                    }
                    logger.info(
                        f"[Scorer] {bot_id}: scored={bot_scored}, skipped={bot_skipped}"
                    )

            # Persist the report to system_metrics
            try:
                import json
                await conn.execute(
                    """
                    INSERT INTO system_metrics (metric_name, value, metadata, timestamp)
                    VALUES ('recommendation_scorer', $1, $2, NOW())
                    """,
                    float(report["recommendations_scored"]),
                    json.dumps(report)
                )
            except Exception as e:
                logger.warning(f"[Scorer] Could not save scoring report: {e}")

    except Exception as e:
        logger.error(f"[Scorer] Fatal error: {e}")
        report["errors"] += 1

    logger.info(f"═══ Agent Recommendation Scorer — Complete ═══\\n{report}")
    return report

