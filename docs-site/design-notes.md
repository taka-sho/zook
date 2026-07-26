# 内部設計メモ

archdiagram の PowerPoint 生成部分([python-pptx](https://python-pptx.readthedocs.io/)を使用)は、実装前にプロトタイプで検証したいくつかの技術的決定に基づいています。詳細は [`docs/detailed-design-pptx.md`](https://github.com/taka-sho/archtecture-diagram-generator/blob/main/docs/detailed-design-pptx.md) にありますが、要点は以下の通りです。

## 座標系

論理単位で記述し、内部で EMU(English Metric Unit)に変換します。

| aspectRatio | 論理サイズ | 実寸 |
|---|---|---|
| `16:9` | 1280 × 720 | 13.333in × 7.5in |
| `4:3` | 960 × 720 | 10in × 7.5in |

**1 論理単位 = 9525 EMU = 96dpi 換算で 1px** という単純な変換式が、どちらのアスペクト比でも成り立ちます。

## 階層グループ化

VPC → AZ → サービスのような入れ子構造は、`add_group_shape()` による PowerPoint 上の入れ子グループとして表現されます。python-pptx はグループへの子要素追加のたびに `chOff`/`chExt`(グループの子座標系オフセット・範囲)を子要素の外接矩形に合わせて自動再計算するため、独自のヘルパー実装は不要でした。

## コネクタの接続点インデックス

矩形図形(アイコン画像・コンテナ枠)同士を `begin_connect()`/`end_connect()` で接続する際の接続点インデックスは、以下の通り確定しています。

```
idx 0 = 上辺中央
idx 1 = 左辺中央
idx 2 = 下辺中央
idx 3 = 右辺中央
```

これは python-pptx 自身の実装(`_move_begin_to_cxn`/`_move_end_to_cxn`)が接続点の実座標をこのマッピングで直接計算しているためで、レンダラー依存ではなくライブラリ仕様として確定的です。archdiagram は接続元・接続先の相対位置(左右・上下どちらが支配的か)から、自動的に適切な辺を選びます。

## コネクタラベル {: #connector-labels }

OOXML スキーマ上、コネクタ要素(`p:cxnSp`)は `txBody`(テキスト本体)を持てません。そのため、リンクの `label` は**コネクタの中点に配置する独立したテキストボックス**として描画されます。図形を移動してもラベル自体はコネクタには追従しません(後編集前提の設計方針と整合)。

## アイコンのラスタライズ解像度 {: #icon-raster-resolution }

SVG アイコンを PNG 化する際は、**表示ピクセル数の4倍**の解像度でラスタライズします。1倍(96dpi 相当)ではPowerPoint/LibreOffice上での拡大描画時ににじみが視認できましたが、2倍以降でほぼ解消し、3倍・4倍との違いは目視で判別できない水準でした。アイコン程度の画像サイズであれば4倍でもファイルサイズは軽微(数十KB程度)です。

## 軽量PNGプレビューとの見た目の一貫性

`archdiagram preview` は python-pptx を使わず、同じレイアウト計算結果(`Box` 木・接続点計算)を Pillow で直接描画する第二のレンダラーです。枠線色・塗り・破線・ラベル位置・隅アイコンといったコンテナの見た目は `resolve_container_style()` という共有関数で1箇所にまとめて解決しており、pptx用レンダラーとPNGプレビューが見た目のロジックで食い違わないようにしています。

## マルチクラウドの解決

要素の `provider`(`aws`/`gcp`/`azure`/任意のカスタム値)ごとに別々のレジストリを保持し、`MultiRegistry` が振り分けます。アイコンは各プロバイダのレジストリにしかない前提ですが、コンテナの `groups`(vpc/az/subnet など)は該当プロバイダに定義がなければ AWS レジストリへフォールバックします。これは、クラウド間で共通する構造概念(VPCやAZなど)を GCP/Azure のレジストリで毎回再定義しなくて済むようにするための設計判断です。

## 検証方法

これらの決定は、`prototype/build_prototype.py` で実際に pptx を生成し、LibreOffice headless(`soffice --convert-to pdf` → `pdftoppm`)で画像化して目視確認しています。再現手順は [`prototype/README.md`](https://github.com/taka-sho/archtecture-diagram-generator/blob/main/prototype/README.md) を参照してください。
