# 申し送り事項 検証プロトタイプ

`docs/detailed-design-pptx.md` §8.6 で確定した3項目を検証するために作成した最小プロトタイプ。
結論は `docs/detailed-design-pptx.md` §8.2〜8.4 / §8.6 / §8.7 と `docs/README-index.md` §4 に反映済み。
本ディレクトリのコードはその検証用であり、実装本体(CLI等)ではない。

## 検証した3項目

1. コネクタの接続点インデックス(`begin_connect`/`end_connect` の `cxn_pt_idx`)の割り当て順
2. コネクタラベルを `p:cxnSp` への `txBody` 直接注入で追従させられるか
3. アイコン SVG → PNG のラスタライズに適した解像度

`icon_placeholder.svg` は AWS 公式アイコンではなく、ラスタライズ品質検証専用の自作プレースホルダ(オレンジ角丸四角+細線+テキスト)。実アイコンの調達・配置は別途 `docs/icon-registry-and-vocabulary.md` §8 の申し送り通り、実装フェーズの作業として残っている。

## 再現手順

```bash
# リポジトリルートで
python3 -m venv .venv
.venv/bin/pip install python-pptx cairosvg

.venv/bin/python prototype/build_prototype.py
# -> prototype/prototype_output.pptx が生成される

# 目視確認(LibreOffice headless があれば)
brew install --cask libreoffice
/Applications/LibreOffice.app/Contents/MacOS/soffice --headless --convert-to pdf \
  --outdir /tmp/render prototype/prototype_output.pptx
pdftoppm -png -r 200 /tmp/render/prototype_output.pdf /tmp/render/slide
# /tmp/render/slide-1.png : 階層グループ化 + コネクタ + 接続点idx凡例
# /tmp/render/slide-2.png : アイコンDPI比較(1x/2x/3x/4x)
```

## 結論サマリ

| 項目 | 結論 |
|---|---|
| 接続点インデックス | `0=上 / 1=左 / 2=下 / 3=右`(python-pptxソースの `_move_begin_to_cxn`/`_move_end_to_cxn` に基づき確定的。凡例レンダリングでも目視確認済み) |
| コネクタラベル | `p:cxnSp` はOOXMLスキーマ上 `txBody` 不可(LibreOffice oox ソースのコメントで確認)。中点テキストボックス方式に確定 |
| アイコンPNG解像度 | 表示px数の4倍でラスタライズ(1x=96dpi相当はにじみが視認できた。2x以降で解消、3x/4xとの差は僅少) |
| グループ化 (chOff/chExt) | python-pptx の `recalculate_extents()` が自動で1:1マッピングするため独自ヘルパー不要と判明 |
| コンテナラベル位置(副次的発見) | デフォルトは縦中央寄せ。`labelPosition: top-left` 通りにするには `text_frame.vertical_anchor = MSO_ANCHOR.TOP` の明示指定が必要 |
