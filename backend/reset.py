"""全データ削除スクリプト。シード票も実投稿もすべて消す。

消したあとは空の状態から実投稿だけが貯まる。初期分布を戻したいときは
`python seed.py` を再実行すればよい(シードのみ復元、実投稿は戻らない)。

実行: python reset.py        # 件数の確認だけ(削除しない)
      python reset.py --yes  # 実際に削除
"""
import argparse
import os

REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
TABLE_NAME = os.environ.get("TABLE_NAME", "mbti-industry-votes")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="実際に削除する")
    args = parser.parse_args()

    import boto3
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)

    keys = []
    kwargs = {"ProjectionExpression": "mbti, industry"}
    while True:
        resp = table.scan(**kwargs)
        keys.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    print(f"{TABLE_NAME}: {len(keys)} 件")
    if not args.yes:
        print("(削除するには --yes を付けて再実行)")
        return

    with table.batch_writer() as batch:
        for k in keys:
            batch.delete_item(Key={"mbti": k["mbti"], "industry": k["industry"]})
    print(f"{len(keys)} 件を削除しました")


if __name__ == "__main__":
    main()
