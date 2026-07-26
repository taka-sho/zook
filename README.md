# archdiagram

YAML で書いたアーキテクチャ構成から PowerPoint(.pptx)を生成するCLIツール。

利用方法・機能をまとめたドキュメントサイト: **https://taka-sho.github.io/archtecture-diagram-generator/**(ソースは `docs-site/`、[Zensical](https://zensical.org/) でビルドし GitHub Pages に公開)。

設計・仕様は `docs/README-index.md` を参照(要件定義・YAML入力仕様・JSON Schema・アイコンレジストリ仕様・pptx詳細設計の一式)。本ディレクトリはその実装。

## セットアップ

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## 使い方

`build`(生成)/`validate`(検証のみ)/`icons list`(登録済みアイコン一覧)/`preview`(軽量PNG)/`export-drawio`(draw.io書き出し)/`sync`(draw.ioの変更をYAMLに反映)の6サブコマンド。

```bash
.venv/bin/archdiagram build docs/example.yaml -o out.pptx
.venv/bin/archdiagram validate docs/example.yaml --strict --format json
.venv/bin/archdiagram icons list --provider gcp
.venv/bin/archdiagram preview docs/example.yaml -o out.png
.venv/bin/archdiagram export-drawio docs/example.yaml -o out.drawio
.venv/bin/archdiagram sync docs/example.yaml out.drawio -o updated.yaml

# 独自アイコン/枠スタイルで組み込みレジストリを上書きする場合
.venv/bin/archdiagram build diagram.yaml -o out.pptx --registry my-registry.yaml
```

- スキーマ違反・id重複・リンク参照先不在などの構造破綻は Fatal(標準エラー出力 + 非ゼロ終了)。
- 未知の`type`・キャンバス範囲外の座標・要素/ラベルの重なりなどは Warning(標準エラー出力に出して継続。`--strict` で非ゼロ終了に変更可能)。
- `--format json`/`github` で機械可読出力(CI連携向け)。

## 構成

```
src/archdiagram/
  cli.py        CLIエントリポイント(build/validate/icons/preview/export-drawio/sync)
  validate.py   JSON Schema検証 + 意味検証(id重複/リンク参照/fromSide-toSideの軸整合)
  model.py      パース後のデータモデル
  registry.py   アイコン/枠スタイルのレジストリ解決(MultiRegistry、provider別・エイリアス・上書き対応)
  layout.py     自動レイアウト(grid/horizontal/vertical、明示座標との混在、重複回避・検知、接続辺の自動選択)
  render.py     python-pptx によるスライド生成(階層グループ・コネクタ・ラベル)
  preview.py    Pillow による軽量PNGプレビュー(LibreOffice/PowerPoint不要)
  drawio.py     draw.io(mxGraph XML)へのエクスポート・同期(継続的な構成図管理向け)
  schemas/      arch-diagram.schema.json / icon-registry.schema.json(docs/の写し)
  data/icons/{aws,gcp,azure}/  組み込みレジストリ + プレースホルダーアイコンPNG
```

## アイコンについて

`src/archdiagram/data/icons/{aws,gcp,azure}/` のPNGは各社公式アイコンではなく、`scripts/generate_placeholder_icons.py` で生成した自作プレースホルダー(カテゴリ別配色+略称)。

実際の公式アイコンに差し替える場合は、各 `registry.<provider>.yaml` の `file` パスに合わせて画像を配置するだけでよい(コード変更不要)。ラスタライズ解像度は表示pxの4倍が目安(`docs/detailed-design-pptx.md` §8.6)。

## テスト

```bash
.venv/bin/pytest tests/ -v
```

## 既知の制約(v1)

- 自動レイアウトは、自動配置の要素が明示座標の兄弟要素と重なる場合のみ自動でずらす(単純な「真下に押し出す」処理)。それ以外の重なりはWarningとして検出されるのみで自動修正はされないため、生成後の手編集を前提とする(`docs/yaml-spec.md` §6)。
- AWS/GCP/Azureの組み込みレジストリはTier-1語彙(AWS26・GCP19・Azure18サービス)のみ。それ以外は `--registry` でのユーザー拡張を想定。
- リンクの接続辺(`fromSide`/`toSide`)は水平ペア・垂直ペアの組み合わせのみ対応。軸をまたぐ組み合わせはFatalエラー(`docs/detailed-design-pptx.md` §8.15)。
- `archdiagram export-drawio` の公式シェイプ対応はAWSのみ。GCP/Azureは現状プレースホルダーPNGの埋め込みにフォールバック(`docs-site/drawio-sync.md`)。

詳細な制約一覧は[ドキュメントサイトの既知の制約ページ](https://taka-sho.github.io/archtecture-diagram-generator/limitations/)を参照。

## ドキュメントサイト(docs-site/)

利用者向けドキュメントは [Zensical](https://zensical.org/) で `docs-site/` から生成し、`main` への push で GitHub Actions(`.github/workflows/docs.yml`)が GitHub Pages に自動デプロイします。

```bash
.venv/bin/pip install zensical
.venv/bin/zensical serve      # http://localhost:8000 でプレビュー
.venv/bin/zensical build --clean  # site/ に静的サイトを生成(コミット対象外)
```

## CI

- `.github/workflows/tests.yml` — push/PR で `pytest` を実行
- `.github/workflows/docs.yml` — `main` への push で docs-site を GitHub Pages へデプロイ
- `.github/workflows/drawio-sync.yml` — `.drawio` ファイルの push をトリガーに `archdiagram sync` を実行し、差分があれば更新後のYAMLをPRとして自動作成(詳細は `docs-site/drawio-sync.md`)
