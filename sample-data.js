// ============================================================
// サンプルデータ(各MBTIタイプに初期の擬似投票を上乗せするためのもの)。
//
// まだ実投稿が少なく、投票ゼロのタイプがあってもグラフが成立するように、
// 全16タイプへ「もっともらしい業界分布」のサンプル票をフロント側で加える。
// 分布は backend/seed.py・デモモードと同じ softmax ロジックで生成する。
//
// ▼ 実投稿(API側)とはっきり区別される ▼
//   - サンプル票はこのファイル(SAMPLE_MATRIX 相当)だけに存在し、
//     DynamoDB(実投稿)には一切書き込まれない。
//   - フロントでは実投稿の行列にこのサンプルを「別レイヤーで合算」するだけ。
//   - 画面には「サンプル込み」バッジと内訳(実投稿◯票+サンプル◯票)を表示する。
//
// ▼ 将来サンプルを完全に消したいとき(実投稿には影響しない) ▼
//   方法A: 下の SAMPLE_DATA_ENABLED を false にして再デプロイ
//   方法B: このファイルを削除し、index.html の
//          <script src="./sample-data.js"></script> の行も消して再デプロイ
// ============================================================

const SAMPLE_DATA_ENABLED = true;

// 各タイプに上乗せするサンプル票の目安(1人 = 1業界1票の想定)。
// 値を変えるとサンプルの「厚み」が変わる。0 にすると実質サンプル無し。
const SAMPLE_VOTES_PER_TYPE = 8;

const SAMPLE_TEMPERATURE = 15; // seed.py / demoMatrixItems と同じ温度

// data.js の AXES / INDUSTRIES / TYPE_CODES を使い、タイプごとに
// softmax 比で SAMPLE_VOTES_PER_TYPE 票を配分する(最大剰余法で合計を厳密化)。
// 返り値は /matrix と同じ形式: [{ type, industry, count }, ...]
function sampleMatrixItems() {
  if (!SAMPLE_DATA_ENABLED || SAMPLE_VOTES_PER_TYPE <= 0) return [];
  const items = [];
  for (const code of TYPE_CODES) {
    const scores = INDUSTRIES.map((ind) => {
      let s = 50;
      AXES.forEach((a, i) => {
        const v = code[i] === a.pos ? 1 : -1;
        s += v * (ind.w[a.key] || 0) * 10;
      });
      return { id: ind.id, s };
    });
    const maxS = Math.max(...scores.map((x) => x.s));
    const exps = scores.map((x) => ({ id: x.id, e: Math.exp((x.s - maxS) / SAMPLE_TEMPERATURE) }));
    const denom = exps.reduce((acc, x) => acc + x.e, 0);
    const quotas = exps.map((x) => ({ id: x.id, q: SAMPLE_VOTES_PER_TYPE * x.e / denom }));
    const counts = quotas.map((x) => ({ id: x.id, n: Math.floor(x.q) }));
    let remain = SAMPLE_VOTES_PER_TYPE - counts.reduce((a, x) => a + x.n, 0);
    quotas
      .map((x, i) => ({ i, frac: x.q - Math.floor(x.q) }))
      .sort((a, b) => b.frac - a.frac)
      .slice(0, remain)
      .forEach((x) => { counts[x.i].n += 1; });
    for (const c of counts) {
      if (c.n > 0) items.push({ type: code, industry: c.id, count: c.n });
    }
  }
  return items;
}
