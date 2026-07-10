import base64
import json
import os

import boto3
from boto3.dynamodb.conditions import Key

REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
TABLE_NAME = os.environ.get("TABLE_NAME", "mbti-industry-votes")
INDEX_NAME = os.environ.get("INDEX_NAME", "by-industry")

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


def _count(item):
    return int(item.get("seed", 0)) + int(item.get("votes", 0))


def _get_stats(mbti):
    resp = table.query(KeyConditionExpression=Key("mbti").eq(mbti))
    items = [
        {"industry": item["industry"], "count": _count(item)}
        for item in resp.get("Items", [])
    ]
    items.sort(key=lambda x: x["count"], reverse=True)
    total = sum(i["count"] for i in items)
    return _response(200, {"type": mbti, "total": total, "items": items})


def _get_industry(industry):
    resp = table.query(
        IndexName=INDEX_NAME,
        KeyConditionExpression=Key("industry").eq(industry),
    )
    items = [
        {"type": item["mbti"], "count": _count(item)}
        for item in resp.get("Items", [])
    ]
    items.sort(key=lambda x: x["count"], reverse=True)
    total = sum(i["count"] for i in items)
    return _response(200, {"industry": industry, "total": total, "items": items})


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
    industries = body.get("industries")
    if industries is None and body.get("industry"):
        industries = [body.get("industry")]  # 旧クライアント互換
    if not isinstance(industries, list):
        return _response(400, {"error": "industries must be a list"})
    industries = [str(i) for i in industries]

    if (
        mbti not in TYPE_CODES
        or not industries
        or len(industries) != len(set(industries))
        or any(i not in INDUSTRY_IDS for i in industries)
    ):
        return _response(400, {"error": "invalid type or industries"})

    for industry in industries:
        table.update_item(
            Key={"mbti": mbti, "industry": industry},
            UpdateExpression="ADD votes :one",
            ExpressionAttributeValues={":one": 1},
        )
    return _response(200, {"ok": True, "voted": len(industries)})


def lambda_handler(event, context):
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "")
    path = event.get("rawPath", "")
    qs = event.get("queryStringParameters") or {}

    if method == "GET" and path == "/stats":
        mbti = (qs.get("type") or "").upper()
        if mbti not in TYPE_CODES:
            return _response(400, {"error": "invalid type"})
        return _get_stats(mbti)

    if method == "GET" and path == "/industry":
        industry = qs.get("id") or ""
        if industry not in INDUSTRY_IDS:
            return _response(400, {"error": "invalid industry"})
        return _get_industry(industry)

    if method == "POST" and path == "/vote":
        return _post_vote(event.get("body"), event.get("isBase64Encoded", False))

    return _response(404, {"error": "not found"})
