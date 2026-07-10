#!/usr/bin/env bash
# 一次セットアップ: DynamoDBテーブル + IAMロール + Lambda + Function URL を作成する。
# 再実行可能(作成済みのリソースはスキップする)。
# 前提: aws CLI に認証情報が設定済みであること(aws sts get-caller-identity で確認)。
set -euo pipefail
cd "$(dirname "$0")"

REGION="${AWS_REGION:-ap-northeast-1}"
TABLE="mbti-industry-votes"
FUNC="mbti-industry-api"
ROLE="mbti-industry-api-role"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "== account: $ACCOUNT_ID / region: $REGION =="

echo "== 1/5 DynamoDB テーブル作成(プロビジョンド 5RCU/5WCU = 常時無料枠内) =="
if aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" >/dev/null 2>&1; then
  echo "   (作成済みのためスキップ)"
else
  aws dynamodb create-table \
    --table-name "$TABLE" \
    --attribute-definitions AttributeName=mbti,AttributeType=S AttributeName=industry,AttributeType=S \
    --key-schema AttributeName=mbti,KeyType=HASH AttributeName=industry,KeyType=RANGE \
    --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
    --region "$REGION" >/dev/null
  aws dynamodb wait table-exists --table-name "$TABLE" --region "$REGION"
fi

echo "== 1.5/5 GSI (by-industry) 作成: 業界→MBTI分布の逆引き用 =="
GSI_COUNT=$(aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" \
  --query "length(Table.GlobalSecondaryIndexes[?IndexName=='by-industry'] || \`[]\`)" --output text)
if [ "$GSI_COUNT" != "0" ]; then
  echo "   (作成済みのためスキップ)"
else
  aws dynamodb update-table \
    --table-name "$TABLE" \
    --attribute-definitions AttributeName=industry,AttributeType=S AttributeName=mbti,AttributeType=S \
    --global-secondary-index-updates '[{"Create":{"IndexName":"by-industry","KeySchema":[{"AttributeName":"industry","KeyType":"HASH"},{"AttributeName":"mbti","KeyType":"RANGE"}],"Projection":{"ProjectionType":"ALL"},"ProvisionedThroughput":{"ReadCapacityUnits":5,"WriteCapacityUnits":5}}}]' \
    --region "$REGION" >/dev/null
  echo "   (バックフィル完了まで数分かかることがあります)"
fi

echo "== 2/5 IAM ロール作成 =="
if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  echo "   (作成済みのためスキップ)"
else
  cat > /tmp/mbti-trust.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
  aws iam create-role --role-name "$ROLE" \
    --assume-role-policy-document file:///tmp/mbti-trust.json >/dev/null
  aws iam attach-role-policy --role-name "$ROLE" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

  cat > /tmp/mbti-dynamo-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:Query", "dynamodb:UpdateItem"],
      "Resource": [
        "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE}",
        "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE}/index/*"
      ]
    }
  ]
}
EOF
  aws iam put-role-policy --role-name "$ROLE" \
    --policy-name dynamo-access --policy-document file:///tmp/mbti-dynamo-policy.json

  echo "   (ロール伝播待ち 10秒)"
  sleep 10
fi

echo "== 3/5 Lambda 関数作成 =="
if aws lambda get-function --function-name "$FUNC" --region "$REGION" >/dev/null 2>&1; then
  echo "   (作成済みのためスキップ。コード更新は ./deploy.sh)"
else
  zip -j /tmp/mbti-function.zip lambda_function.py >/dev/null
  aws lambda create-function \
    --function-name "$FUNC" \
    --runtime python3.12 \
    --handler lambda_function.lambda_handler \
    --zip-file fileb:///tmp/mbti-function.zip \
    --role "arn:aws:iam::${ACCOUNT_ID}:role/${ROLE}" \
    --environment "Variables={TABLE_NAME=${TABLE}}" \
    --timeout 10 \
    --region "$REGION" >/dev/null
fi

echo "== 4/5 Function URL 作成(CORSは開発用にまず全許可。公開後にREADMEの手順で絞る) =="
if aws lambda get-function-url-config --function-name "$FUNC" --region "$REGION" >/dev/null 2>&1; then
  echo "   (作成済みのためスキップ)"
else
  aws lambda create-function-url-config \
    --function-name "$FUNC" \
    --auth-type NONE \
    --cors '{"AllowOrigins":["*"],"AllowMethods":["GET","POST"],"AllowHeaders":["content-type"]}' \
    --region "$REGION" >/dev/null
fi
# 2025年10月以降のFunction URLは InvokeFunctionUrl と InvokeFunction の両方の許可が必要
aws lambda add-permission \
  --function-name "$FUNC" \
  --statement-id FunctionURLAllowPublicAccess \
  --action lambda:InvokeFunctionUrl \
  --principal "*" \
  --function-url-auth-type NONE \
  --region "$REGION" >/dev/null 2>&1 || echo "   (InvokeFunctionUrl 権限は設定済み)"
aws lambda add-permission \
  --function-name "$FUNC" \
  --statement-id FunctionURLInvokeAllowPublicAccess \
  --action lambda:InvokeFunction \
  --principal "*" \
  --invoked-via-function-url \
  --region "$REGION" >/dev/null 2>&1 || echo "   (InvokeFunction 権限は設定済み)"

echo "== 5/5 完了 =="
URL=$(aws lambda get-function-url-config --function-name "$FUNC" --region "$REGION" --query FunctionUrl --output text)
echo ""
echo "Function URL: $URL"
echo "次にやること:"
echo "  1. python seed.py                  # シードデータ投入"
echo "  2. index.html の API_URL に上記URLを設定(末尾スラッシュは除く)"
echo "  3. curl \"${URL}stats?type=INTJ\"   # 動作確認"
