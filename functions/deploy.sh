#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  TradeClaw — Cloud Functions Deploy Script
#  Usage: ./deploy.sh [scorer|all]
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

PROJECT_ID='tradeclaw-fleet'
REGION="us-central1"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SOURCE_DIR}/.env.yaml"

RUNTIME="python311"
TIMEOUT="540s"
MEMORY="256Mi"

echo "═══ TradeClaw Cloud Functions Deploy ═══"
echo "  Project:  ${PROJECT_ID}"
echo "  Region:   ${REGION}"
echo "  Source:   ${SOURCE_DIR}"
echo ""

deploy_scorer() {
    echo "► Deploying: recommendation-scorer"
    gcloud functions deploy recommendation-scorer \
        --gen2 \
        --runtime "${RUNTIME}" \
        --region "${REGION}" \
        --trigger-http \
        --allow-unauthenticated \
        --source "${SOURCE_DIR}" \
        --entry-point recommendation_scorer \
        --env-vars-file "${ENV_FILE}" \
        --timeout "${TIMEOUT}" \
        --memory "${MEMORY}" \
        --max-instances 1

    echo ""
    echo "► Creating Cloud Scheduler job for scorer (every 4 hours on trading days)"
    SCORER_URL=$(gcloud functions describe recommendation-scorer --gen2 --region "${REGION}" --format='value(serviceConfig.uri)')
    gcloud scheduler jobs create http tradeclaw-scorer \
        --location "${REGION}" \
        --schedule "0 */4 * * 1-5" \
        --uri "${SCORER_URL}" \
        --http-method POST \
        --oidc-service-account-email "${PROJECT_ID}@appspot.gserviceaccount.com" \
        --time-zone "UTC" \
        --description "TradeClaw: Score agent recommendations every 4 hours on trading days" \
        --attempt-deadline "${TIMEOUT}" \
        2>/dev/null || \
    gcloud scheduler jobs update http tradeclaw-scorer \
        --location "${REGION}" \
        --schedule "0 */4 * * 1-5" \
        --uri "${SCORER_URL}" \
        --http-method POST \
        --oidc-service-account-email "${PROJECT_ID}@appspot.gserviceaccount.com"

    echo "  ✓ Scorer deployed and scheduled"
}

case "${1:-all}" in
    scorer|all) deploy_scorer ;;
    *)
        echo "Usage: $0 [scorer|all]"
        exit 1
        ;;
esac

echo ""
echo "═══ Deploy Complete ═══"
