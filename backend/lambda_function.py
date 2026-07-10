import base64
import json
import os

import boto3
from boto3.dynamodb.conditions import Key

REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
TABLE_NAME = os.environ.get("TABLE_NAME", "mbti-industry-votes")

TYPE_CODES = {a + b + c + d for a in "EI" for b in "SN" for c in "TF" for d in "JP"}
INDUSTRY_IDS = {
    "it", "web", "consul", "finance", "maker", "trading",
    "media", "medical", "public", "edu", "estate", "retail",
}

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def _get_stats(mbti):
    resp = table.query(KeyConditionExpression=Key("mbti").eq(mbti))
    items = [
        {
            "industry": item["industry"],
            "count": int(item.get("seed", 0)) + int(item.get("votes", 0)),
        }
        for item in resp.get("Items", [])
    ]
    items.sort(key=lambda x: x["count"], reverse=True)
    total = sum(i["count"] for i in items)
    return _response(200, {"type": mbti, "total": total, "items": items})


def _post_vote(raw_body, is_base64):
    if is_base64:
        try:
            raw_body = base64.b64decode(raw_body).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return _response(400, {"error": "invalid body"})
    try:
        body = json.loads(raw_body or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "invalid json"})

    mbti = str(body.get("type", "")).upper()
    industry = str(body.get("industry", ""))
    if mbti not in TYPE_CODES or industry not in INDUSTRY_IDS:
        return _response(400, {"error": "invalid type or industry"})

    table.update_item(
        Key={"mbti": mbti, "industry": industry},
        UpdateExpression="ADD votes :one",
        ExpressionAttributeValues={":one": 1},
    )
    return _response(200, {"ok": True})


def lambda_handler(event, context):
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "")
    path = event.get("rawPath", "")

    if method == "GET" and path == "/stats":
        qs = event.get("queryStringParameters") or {}
        mbti = (qs.get("type") or "").upper()
        if mbti not in TYPE_CODES:
            return _response(400, {"error": "invalid type"})
        return _get_stats(mbti)

    if method == "POST" and path == "/vote":
        return _post_vote(event.get("body"), event.get("isBase64Encoded", False))

    return _response(404, {"error": "not found"})
