#!/usr/bin/env bash
# Lambda コード更新: ./deploy.sh
set -euo pipefail
cd "$(dirname "$0")"

REGION="${AWS_REGION:-ap-northeast-1}"
FUNC="mbti-industry-api"

zip -j /tmp/mbti-function.zip lambda_function.py >/dev/null
aws lambda update-function-code \
  --function-name "$FUNC" \
  --zip-file fileb:///tmp/mbti-function.zip \
  --region "$REGION" \
  --query "LastUpdateStatus" --output text
echo "deployed: $FUNC"
