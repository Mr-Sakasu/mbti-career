"""データ削除スクリプト。

デフォルトは全削除(デモ票+実投稿)。--seed-only を付けるとデモ票(seed属性)
だけを消し、実投稿(votes属性)は温存する。デモ票を入れ直すには `python seed.py`。

実行: python reset.py                    # 件数の確認だけ(削除しない)
      python reset.py --yes              # 全削除
      python reset.py --seed-only --yes  # デモ票のみ削除(実投稿は残す)
"""
import argparse
import os

REGION = os.environ.get("AWS_REGION", "ap-northeast-1")
TABLE_NAME = os.environ.get("TABLE_NAME", "mbti-industry-votes")


def scan_all(table, projection):
    items = []
    kwargs = {"ProjectionExpression": projection}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items


def reset_all(table, items, do_delete):
    print(f"{TABLE_NAME}: {len(items)} 件(デモ票+実投稿すべて)")
    if not do_delete:
        print("(削除するには --yes を付けて再実行)")
        return
    with table.batch_writer() as batch:
        for it in items:
            batch.delete_item(Key={"mbti": it["mbti"], "industry": it["industry"]})
    print(f"{len(items)} 件を削除しました")


def reset_seed_only(table, items, do_delete):
    from botocore.exceptions import ClientError

    seeded = [it for it in items if int(it.get("seed", 0)) > 0]
    with_votes = [it for it in seeded if int(it.get("votes", 0)) > 0]
    empty = [it for it in seeded if int(it.get("votes", 0)) == 0]
    print(f"{TABLE_NAME}: デモ票あり {len(seeded)} 件"
          f"(実投稿と同居 {len(with_votes)} 件 / デモ票のみ {len(empty)} 件)")
    if not do_delete:
        print("(削除するには --yes を付けて再実行)")
        return

    # 実投稿と同居しているセルは seed 属性だけ外す
    for it in with_votes:
        table.update_item(
            Key={"mbti": it["mbti"], "industry": it["industry"]},
            UpdateExpression="REMOVE seed",
        )
    # デモ票しかないセルは項目ごと削除(直前に実投稿が入っていたら削除せずseedだけ外す)
    for it in empty:
        try:
            table.delete_item(
                Key={"mbti": it["mbti"], "industry": it["industry"]},
                ConditionExpression="attribute_not_exists(votes) OR votes = :zero",
                ExpressionAttributeValues={":zero": 0},
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            table.update_item(
                Key={"mbti": it["mbti"], "industry": it["industry"]},
                UpdateExpression="REMOVE seed",
            )
    print(f"デモ票 {len(seeded)} 件を削除しました(実投稿は温存)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="実際に削除する")
    parser.add_argument("--seed-only", action="store_true",
                        help="デモ票(seed属性)だけを消す。実投稿(votes)は残す")
    args = parser.parse_args()

    import boto3
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    items = scan_all(table, "mbti, industry, seed, votes")

    if args.seed_only:
        reset_seed_only(table, items, args.yes)
    else:
        reset_all(table, items, args.yes)


if __name__ == "__main__":
    main()
