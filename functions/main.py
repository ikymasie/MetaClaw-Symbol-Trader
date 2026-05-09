"""
TradeClaw — Cloud Functions Entry Point
=========================================
Defines all scheduled Cloud Functions (2nd gen) as HTTP-triggered endpoints.

GCP Cloud Scheduler calls these via HTTP on the configured schedule.
Each function uses the `functions-framework` decorator pattern.

Deploy:
    gcloud functions deploy <function-name> \
        --gen2 \
        --runtime python311 \
        --region us-central1 \
        --trigger-http \
        --source functions/ \
        --entry-point <entry-point> \
        --env-vars-file functions/.env.yaml \
        --timeout 540s \
        --memory 256Mi
"""

import json
import logging
import traceback

import functions_framework
from flask import Request

logger = logging.getLogger("tradeclaw.functions")
logging.basicConfig(level=logging.INFO)


@functions_framework.http
def recommendation_scorer(request: Request):
    """
    Scheduled function: Agent Recommendation Scorer
    Schedule: Every 4 hours on trading days  →  0 */4 * * 1-5

    Scores unscored agent recommendations against actual forward
    returns from market bars. Closes the Darwinian evolution feedback loop.
    """
    try:
        import asyncio
        from recommendation_scorer import run_scorer

        report = asyncio.run(run_scorer())
        return json.dumps(report, default=str), 200, {"Content-Type": "application/json"}

    except Exception as e:
        logger.error(f"Scorer failed: {e}\n{traceback.format_exc()}")
        return json.dumps({"error": str(e)}), 500, {"Content-Type": "application/json"}
