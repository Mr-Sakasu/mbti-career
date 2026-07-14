"""デモデータ投入スクリプト(ローカルで1回実行)。

全16タイプに「6人程度が1業界ずつ投票した」規模のデモ票を入れる。
配分はv1の軸ウェイトモデル(softmax)で、タイプごとにもっともらしい業界へ寄せる。

デモ票は `seed` 属性、実投稿は `votes` 属性に分けて保存しているため、
デモ票だけを後から一括削除できる: `python reset.py --seed-only --yes`

実行: python seed.py [--dry-run]
"""
import argparse
import math
import os

REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
TABLE_NAME = os.environ.get("TABLE_NAME", "mbti-industry-votes")

DEMO_VOTES_PER_TYPE = 6  # 「6人程度」相当。1人=1業界1票の想定
TEMPERATURE = 15.0

AXES = ["EI", "SN", "TF", "JP"]
POS_LETTERS = "ESTJ"  # 各軸の「正」側(ウェイト正が好む極)

# v1 index.html の INDUSTRIES と同じ軸ウェイト(正: E/S/T/J寄り、負: I/N/F/P寄り)
INDUSTRY_WEIGHTS = {
    "it":      {"EI": -0.5, "SN": -1.0, "TF": 1.5, "JP": 0.5},
    "web":     {"EI": 0.5, "SN": -1.5, "TF": 0.0, "JP": -1.5},
    "consul":  {"EI": 1.0, "SN": -1.0, "TF": 1.5, "JP": 0.5},
    "finance": {"EI": 0.5, "SN": 1.0, "TF": 1.0, "JP": 1.5},
    "maker":   {"EI": -0.5, "SN": 1.0, "TF": 0.5, "JP": 1.0},
    "trading": {"EI": 2.0, "SN": 0.0, "TF": 0.5, "JP": -0.5},
    "media":   {"EI": 1.0, "SN": -1.5, "TF": -0.5, "JP": -1.0},
    "medical": {"EI": 0.0, "SN": 1.0, "TF": -1.5, "JP": 0.5},
    "public":  {"EI": -0.5, "SN": 1.5, "TF": 0.0, "JP": 2.0},
    "edu":     {"EI": 1.0, "SN": 0.0, "TF": -1.5, "JP": 0.5},
    "estate":  {"EI": 1.0, "SN": 1.0, "TF": 0.5, "JP": 0.5},
    "retail":  {"EI": 1.0, "SN": 0.5, "TF": -1.0, "JP": -0.5},
}

TYPE_CODES = [a + b + c + d for a in "EI" for b in "SN" for c in "TF" for d in "JP"]


def old_score(code, weights):
    score = 50.0
    for i, axis in enumerate(AXES):
        v = 1 if code[i] == POS_LETTERS[i] else -1
        score += v * weights.get(axis, 0.0) * 10
    return score


def demo_counts(code):
    """softmax比で DEMO_VOTES_PER_TYPE 票を配分(最大剰余法で合計を厳密に合わせる)。"""
    scores = {ind: old_score(code, w) for ind, w in INDUSTRY_WEIGHTS.items()}
    max_s = max(scores.values())
    exps = {ind: math.exp((s - max_s) / TEMPERATURE) for ind, s in scores.items()}
    denom = sum(exps.values())
    quotas = {ind: DEMO_VOTES_PER_TYPE * e / denom for ind, e in exps.items()}
    counts = {ind: int(q) for ind, q in quotas.items()}
    remain = DEMO_VOTES_PER_TYPE - sum(counts.values())
    for ind, _ in sorted(quotas.items(), key=lambda x: x[1] - int(x[1]), reverse=True)[:remain]:
        counts[ind] += 1
    return {ind: n for ind, n in counts.items() if n > 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="書き込まずに分布を表示")
    args = parser.parse_args()

    all_items = []
    for code in TYPE_CODES:
        counts = demo_counts(code)
        for ind, n in counts.items():
            all_items.append({"mbti": code, "industry": ind, "seed": n})
        dist = sorted(counts.items(), key=lambda x: -x[1])
        print(f"{code}: total={sum(counts.values())} {dist}")

    if args.dry_run:
        print(f"\n(dry-run) {len(all_items)} 件は書き込みませんでした")
        return

    import boto3
    from botocore.exceptions import ClientError

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)

    # put_itemだと既存のvotes(実投稿)を消してしまうため、seed属性だけをSETする
    seeded = {(it["mbti"], it["industry"]) for it in all_items}
    for i, item in enumerate(all_items, 1):
        table.update_item(
            Key={"mbti": item["mbti"], "industry": item["industry"]},
            UpdateExpression="SET seed = :n",
            ExpressionAttributeValues={":n": item["seed"]},
        )
        if i % 24 == 0:
            print(f"  {i}/{len(all_items)} 件書き込み済み…")

    # 今回配分が0になったセルに古いseedが残っていれば消す(既存項目のみ、実投稿は温存)
    cleaned = 0
    kwargs = {"ProjectionExpression": "mbti, industry, seed"}
    while True:
        resp = table.scan(**kwargs)
        for it in resp.get("Items", []):
            if "seed" in it and (it["mbti"], it["industry"]) not in seeded:
                try:
                    table.update_item(
                        Key={"mbti": it["mbti"], "industry": it["industry"]},
                        UpdateExpression="REMOVE seed",
                        ConditionExpression="attribute_exists(seed)",
                    )
                    cleaned += 1
                except ClientError as e:
                    if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                        raise
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    print(f"\nデモ票 {len(all_items)} 件を {TABLE_NAME} に書き込みました(votes属性=実投稿は温存)")
    if cleaned:
        print(f"古いデモ票 {cleaned} 件を掃除しました")
    print("デモ票だけを消すには: python reset.py --seed-only --yes")


if __name__ == "__main__":
    main()
