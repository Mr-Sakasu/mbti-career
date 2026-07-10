"""シードデータ投入スクリプト(ローカルで1回実行)。

v1の軸ウェイトモデルを「もっともらしい初期分布」の生成にのみ再利用し、
タイプごとに合計約30票をsoftmaxで12業界に配分してseed属性に書き込む。
実投稿(votes)とは属性を分けているため、後からシードだけ削除・縮小できる。

実行: python seed.py [--dry-run]
"""
import argparse
import math
import os

REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
TABLE_NAME = os.environ.get("TABLE_NAME", "mbti-industry-votes")

SEED_TOTAL_PER_TYPE = 30
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


def seed_counts(code):
    scores = {ind: old_score(code, w) for ind, w in INDUSTRY_WEIGHTS.items()}
    max_s = max(scores.values())
    exps = {ind: math.exp((s - max_s) / TEMPERATURE) for ind, s in scores.items()}
    denom = sum(exps.values())
    # 各業界最低1票、残りをsoftmax比で配分
    counts = {ind: 1 for ind in INDUSTRY_WEIGHTS}
    remain = SEED_TOTAL_PER_TYPE - len(counts)
    for ind, e in exps.items():
        counts[ind] += round(remain * e / denom)
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="書き込まずに分布を表示")
    args = parser.parse_args()

    all_items = []
    for code in TYPE_CODES:
        counts = seed_counts(code)
        for ind, n in counts.items():
            all_items.append({"mbti": code, "industry": ind, "seed": n, "votes": 0})
        top = sorted(counts.items(), key=lambda x: -x[1])[:3]
        print(f"{code}: total={sum(counts.values())} top3={top}")

    if args.dry_run:
        print(f"\n(dry-run) {len(all_items)} 件は書き込みませんでした")
        return

    import boto3
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    # put_itemだと既存のvotes(実投稿)を消してしまうため、seed属性だけをSETする
    for i, item in enumerate(all_items, 1):
        table.update_item(
            Key={"mbti": item["mbti"], "industry": item["industry"]},
            UpdateExpression="SET seed = :n",
            ExpressionAttributeValues={":n": item["seed"]},
        )
        if i % 24 == 0:
            print(f"  {i}/{len(all_items)} 件書き込み済み…")
    print(f"\n{len(all_items)} 件を {TABLE_NAME} に書き込みました(votes属性は温存)")
    print("注意: プロビジョンド5WCUのため1分弱かかることがあります")


if __name__ == "__main__":
    main()
