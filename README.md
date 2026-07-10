# MBTI × 志望業界 傾向診断

MBTIタイプを選ぶと「同じタイプの人がどの業界を志望しているか」の分布がグラフで見られるWebアプリ。
訪問者は自分のMBTI+志望業界を投稿でき、投稿はDynamoDBに蓄積されて集計に反映される。

```
ブラウザ (Vercel: index.html)
  ├─ GET  {FUNCTION_URL}/stats?type=INTJ        → タイプ別の業界分布
  └─ POST {FUNCTION_URL}/vote {type, industry}  → 1票投稿
        Lambda (Python 3.12) ─ DynamoDB: mbti-industry-votes
```

すべてAWSの常時無料枠内(Lambda 月100万req / DynamoDB プロビジョンド25RCU・WCU)+ Vercel無料プランで運用できる。

## セットアップ手順

### 0. 前提

- aws CLI に認証情報が設定済みであること: `aws sts get-caller-identity` で確認
- 未設定なら IAM ユーザーのアクセスキーで `aws configure`(または AWS CloudShell 上で実行)
- `seed.py` の実行には boto3 が必要: `pip install boto3`(`--dry-run` は不要)

### 1. バックエンド構築(1回だけ)

```bash
cd backend
./setup.sh          # テーブル + IAMロール + Lambda + Function URL を作成
```

最後に表示される **Function URL** を控える。

### 2. シードデータ投入(1回だけ)

```bash
python seed.py --dry-run   # 分布を確認(書き込まない)
python seed.py             # 16タイプ×12業界=192件を書き込み(1分弱かかる)
```

シード票は `seed` 属性、実投稿は `votes` 属性に分けて保存されるため、後からシードだけ削除・縮小できる。

### 3. フロントエンド設定

`index.html` の先頭付近にある `API_URL` に Function URL を設定(**末尾スラッシュなし**):

```js
const API_URL = "https://xxxxxxxx.lambda-url.ap-northeast-1.on.aws";
```

`API_URL` が空のままだとデモモード(擬似データ+「デモデータ」バッジ)で動く。

### 4. 動作確認

```bash
curl "{FUNCTION_URL}/stats?type=INTJ"
curl -X POST "{FUNCTION_URL}/vote" -H "content-type: application/json" \
  -d '{"type":"INTJ","industry":"it"}'
curl "{FUNCTION_URL}/stats?type=INTJ"   # itが1票増えていればOK
```

ブラウザで `index.html` を開き、タイプ切替→グラフ表示、業界選択→投稿、リロード→投稿済み表示を確認。

### 5. Vercel デプロイ

```bash
npx vercel deploy --prod   # mbti-career/ ディレクトリで実行(初回はログイン)
```

またはGitHub連携でリポジトリをインポート。静的1枚なのでビルド設定は不要(Framework Preset: Other)。

独自ドメイン: Vercelダッシュボード → プロジェクト → Settings → Domains にドメインを追加し、
表示されるDNSレコード(CNAMEまたはA)をドメイン側に設定するだけ。HTTPSは自動。

### 6. CORS を絞る(公開後推奨)

`setup.sh` は開発しやすいよう `AllowOrigins="*"` で作る。公開URLが決まったら絞る:

```bash
aws lambda update-function-url-config \
  --function-name mbti-industry-api \
  --cors '{"AllowOrigins":["https://<your-app>.vercel.app","https://<your-domain>"],"AllowMethods":["GET","POST"],"AllowHeaders":["content-type"]}' \
  --region ap-northeast-1
```

## コード更新

- Lambda: `backend/deploy.sh`
- フロント: `npx vercel deploy --prod`

## 運用メモ・既知の制限

- **重複投稿**: localStorage による1人1回制御のみ(シークレットウィンドウで回避可能)。趣味アプリとして許容。必要になったらIPベースのソフトスロットル等を検討
- **DynamoDBは必ずプロビジョンドモード**: オンデマンドに変えると無料枠外(微額だが課金される)
- **VercelのプレビューURLからはAPIが叩けない**(CORSを絞った場合)。本番URLで確認する
- シード削除: `seed` 属性を0にする(または項目ごと削除して `votes` のみ残す)
- 傾向データは投稿+シードにもとづく参考コンテンツであり、適職を保証するものではない(フッターに明記済み)
