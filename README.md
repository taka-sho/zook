# ZOOK

zook は、YAML で書いたインフラ構成から PowerPoint(.pptx)のアーキテクチャ図を生成する CLI ツールです。draw.io で整えた見た目の変更を YAML に書き戻しながら図を育てていく運用を主眼に置いています。

利用方法・機能をまとめたドキュメントサイト: **https://taka-sho.github.io/zook/**(ソースは `docs-site/`、[Zensical](https://zensical.org/) でビルドし GitHub Pages に公開)。設計・仕様一式は `docs/README-index.md` を参照してください。

生成AIがこのツールを使って構成図を作る場合は [`AGENTS.md`](./AGENTS.md) に黄金の道(パターン選定→アイコン語彙確認→検証→生成)をまとめています。Mermaidの`flowchart`記法で書いた図がすでにある場合は、`zook from-mermaid` で YAML に変換してから同じ流れに載せられます([Mermaidフローチャートのインポート](https://taka-sho.github.io/zook/mermaid-import/))。

## 基本の流れ: ベースを作り、draw.io で整え、YAML に戻す

zook でのアーキテクチャ図づくりは、次の4ステップを繰り返す形で進みます。図を直すたびにこの流れへ戻ってくる運用を想定しています。

1. **YAML からベースの構成図を作る**。VPC・AZ・サービスといった構成要素を YAML で記述し、`build` で PowerPoint を生成します。座標を指定しなければ自動でレイアウトされるので、最初は構造を書くことだけに集中できます。

   ```bash
   zook build diagram.yaml -o diagram.pptx
   ```

2. **見た目を draw.io で整える**。自動レイアウトのままでは間隔や配置が意図通りにならないことがあります。`export-drawio` で draw.io 形式に書き出し、要素の位置・サイズを実際に動かしながら調整します。

   ```bash
   zook export-drawio diagram.yaml -o diagram.drawio
   ```

3. **draw.io での調整を YAML に書き戻す**。動かしていない要素は自動配置のまま維持され、実際に動かした要素だけ座標が YAML に加わります。ノードの追加・削除や色の変更は同期の対象外です。PowerPoint ではなく draw.io を経由するのは、draw.io のコンテナ図形はリサイズしても子要素の座標が変わらず、座標変換なしにそのまま YAML へ書き戻せるためです(PowerPoint のグループ図形は子要素の座標を独自スケールで保持しており、変換の読み戻しが煩雑になります)。

   ```bash
   zook sync diagram.yaml diagram.drawio -o diagram.yaml
   ```

4. **整えた YAML から PowerPoint を出力し直す**。draw.io での配置を保ったまま PowerPoint が生成されます。構成そのものを変えたくなったら 1 に戻って YAML を編集し、また同じ4ステップを回します。

   ```bash
   zook build diagram.yaml -o diagram.pptx
   ```

このループは CI に載せて自動化することもできます。draw.io 側で `.drawio` ファイルを保存すると、CI が `sync` を実行して更新後の YAML を Pull Request として自動作成する仕組みも用意しています(`.github/workflows/drawio-sync.yml`)。詳しい運用は[ドキュメントサイトの draw.io連携ページ](https://taka-sho.github.io/zook/drawio-sync/)にまとめています。

## セットアップ

```bash
git clone https://github.com/taka-sho/zook.git
cd zook

python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

同梱のサンプルから生成できることを確認してください。`Wrote example.pptx` と表示され、終了コード `0` なら成功です。

```bash
.venv/bin/zook build docs/example.yaml -o example.pptx
```

## サブコマンド一覧

| コマンド | 役割 |
|---|---|
| `build` | YAML から PowerPoint(.pptx)を生成する |
| `validate` | レンダリングせずにスキーマ・重なりなどを検証する |
| `doctor` | 要素の重なり(座標調整)とリンク経路の衝突(接続辺の割り当て)を自動解消する |
| `icons list` | 登録済みのアイコン・コンテナ種別を一覧表示する |
| `preview` | PowerPoint を使わずに軽量 PNG でプレビューする |
| `export-drawio` | draw.io で編集できる形式に書き出す |
| `sync` | draw.io での位置・サイズの変更を YAML に反映する |
| `from-mermaid` | Mermaid の `flowchart`/`graph` 記法を YAML に変換する |

`--registry` オプション(全サブコマンド共通)を使うと、組み込みの AWS/GCP/Azure アイコンレジストリの上に、独自のアイコンや枠スタイルを重ねられます。

```bash
.venv/bin/zook build diagram.yaml -o out.pptx --registry my-registry.yaml
```

各コマンドの詳しいオプションは[使い方ページ](https://taka-sho.github.io/zook/usage/)を参照してください。

## エラー処理の考え方

zook は CI/CD での利用を想定し、構造の破綻と描画上の軽微な問題を区別します。スキーマ違反・id 重複・リンク参照先の不在といった構造的な誤りは Fatal として即座にエラー終了しますが、未知のアイコン種別や要素同士の重なりといった描画上の問題は Warning として出力しつつ生成を続けます(`--strict` を付けると Warning も非ゼロ終了に切り替わります)。`--format json`/`github` にも対応しており、CI のゲートへそのまま組み込めます。

## アイコンについて

同梱の PNG は各社の公式アイコンではなく、`scripts/generate_placeholder_icons.py` で生成した自作のプレースホルダーです(カテゴリ別の配色とサービス名の略称)。ライセンス上の理由から、AWS/GCP/Azure の公式アイコンはリポジトリに含めていません。実際の公式アイコンに差し替える場合は、各 `registry.<provider>.yaml` の `file` パスに合わせて画像を配置するだけで済み、コードの変更は不要です。

`export-drawio` は AWS のアイコン・コンテナに限り、draw.io 公式の AWS4 シェイプライブラリで書き出します。GCP/Azure は対応表がまだ無く、このツール自身のプレースホルダー PNG が埋め込まれます。

## テスト

```bash
.venv/bin/pytest tests/ -v
```

## 既知の制約(v1)

- 自動レイアウトが解消する重なりは、自動配置の要素が明示座標の兄弟要素と重なるケースに限られます(単純な「真下に押し出す」処理)。それ以外の重なりは Warning として検出されるのみで自動修正はされず、生成後の手編集を前提としています。
- 組み込みのアイコンレジストリは Tier-1 語彙(AWS26・GCP19・Azure18 サービス)のみで、それ以外は `--registry` によるユーザー拡張を想定しています。
- リンクの接続辺(`fromSide`/`toSide`)は水平ペア・垂直ペアの組み合わせのみ対応しており、軸をまたぐ指定は Fatal エラーになります。

詳しい制約一覧は[ドキュメントサイトの既知の制約ページ](https://taka-sho.github.io/zook/limitations/)にまとめています。

## ドキュメントサイトと CI

利用者向けドキュメントは [Zensical](https://zensical.org/) で `docs-site/` から生成し、`main` への push で GitHub Actions が GitHub Pages へ自動デプロイします。

```bash
.venv/bin/pip install zensical
.venv/bin/zensical serve          # http://localhost:8000 でプレビュー
.venv/bin/zensical build --clean  # site/ に静的サイトを生成(コミット対象外)
```

- `.github/workflows/tests.yml` — push/PR で `pytest` を実行
- `.github/workflows/docs.yml` — `main` への push で docs-site を GitHub Pages へデプロイ
- `.github/workflows/drawio-sync.yml` — `.drawio` ファイルの push をトリガーに `sync` を実行し、差分があれば更新後の YAML を PR として自動作成

## 構成

```
src/zook/
  cli.py        CLIエントリポイント(build/validate/doctor/icons/preview/export-drawio/sync/from-mermaid)
  validate.py   JSON Schema検証 + 意味検証(id重複/リンク参照/fromSide-toSideの軸整合)
  doctor.py     重なり(座標調整)とリンク経路衝突(接続辺の割り当て)の自動解消(doctor向け)
  model.py      パース後のデータモデル
  registry.py   アイコン/枠スタイルのレジストリ解決(MultiRegistry、provider別・エイリアス・上書き対応)
  layout.py     自動レイアウト(grid/horizontal/vertical、明示座標との混在、重複回避・検知、接続辺の自動選択)
  render.py     python-pptx によるスライド生成(階層グループ・コネクタ・ラベル)
  preview.py    Pillow による軽量PNGプレビュー(LibreOffice/PowerPoint不要)
  drawio.py     draw.io(mxGraph XML)へのエクスポート・同期(継続的な構成図管理向け)
  mermaid_flowchart.py  Mermaidの`flowchart`/`graph`記法のパーサ(from-mermaid向け)
  schemas/      zook.schema.json / icon-registry.schema.json(docs/の写し)
  data/icons/{aws,gcp,azure}/  組み込みレジストリ + プレースホルダーアイコンPNG
```
