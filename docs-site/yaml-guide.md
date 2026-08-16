# YAML入力仕様

zook の入力 YAML は [`zook.schema.json`](https://github.com/taka-sho/zook/blob/main/docs/zook.schema.json)(JSON Schema Draft 2020-12)で厳密に定義されています。本ページはその要点をまとめたものです。完全な仕様は [`docs/yaml-spec.md`](https://github.com/taka-sho/zook/blob/main/docs/yaml-spec.md) を参照してください。

## トップレベル構造

```yaml
version: "1.0"        # 必須。固定値
canvas: {...}          # 必須。スライド設定
elements: [...]        # 必須。コンテナ/ノードの配列
links: [...]            # 任意。接続線。省略すれば線なしの図
```

## canvas

| フィールド | 必須 | 説明 |
|---|---|---|
| `aspectRatio` | ○ | `"16:9"` または `"4:3"` |
| `padding` | | スライド端と最上位要素の余白(既定 40) |
| `background` | | 背景色 `#RRGGBB` |
| `overlapMargin` | | 重なり検知で各要素の周囲に追加するバッファ(論理単位、既定 0)。0 は文字通りの重なりのみ検知、大きくすると近接している要素・リンク経路も検知対象になる |

論理座標系は `16:9` で 1280×720、`4:3` で 960×720。原点は左上、+x が右、+y が下です。

## 要素(`elements` / `children`)

`kind` で2種類に判別されます。

### container(枠:VPC / AZ / subnet など)

```yaml
- kind: container
  id: vpc-main          # 図全体で一意
  type: vpc               # 自由文字列。cloud/vpc/az/subnet/region/account/group など
  provider: aws            # 既定 generic
  label: "Production VPC"
  style:
    labelFontSize: 10       # 枠自身のラベル文字サイズ(pt、既定10)
    borderColor: "#8C4FFF"   # 任意。省略時はアイコンレジストリのgroups.<type>の既定色
    fillColor: "#F5F0FF"      # 任意。省略時は塗りなし(レジストリ側の既定に従う)
    borderWidth: 2             # 任意。省略時は既定1
  layout:                  # 子の自動配置ルール(下記参照)
    direction: horizontal
    gap: 48
  children: [...]           # 入れ子(再帰)
```

`style.labelFontSize` を大きくすると、自動レイアウトがそのラベル用に確保する上下スペースも比例して広がります。`borderColor`/`fillColor`/`borderWidth` は、個別のコンテナだけアイコンレジストリの既定スタイル([アイコン・レジストリ](icons.md)参照)から色・線幅を変えたい場合に指定します。

### node(アイコン:EC2 / Lambda / RDS / S3 など)

```yaml
- kind: node
  id: web
  type: EC2                # アイコン解決キー。詳細は「アイコン・レジストリ」参照
  label: "WebServer"
  size: 64                  # アイコンの幅・高さを同時に指定するショートハンド(論理単位)
  style:
    labelPosition: below    # below(既定) / above / right / none
    labelGap: 4              # アイコンとラベルの間隔(論理単位、既定4)
    labelFontSize: 9          # ラベル文字サイズ(pt、既定9)
```

`labelGap` を大きくすると、狭いレイアウトでラベル同士やリンクのラベルとの重なりを避けやすくなります(重なりは[既知の制約](limitations.md)にある通り警告されますが、自動では回避されません)。`labelFontSize` を大きくすると、自動レイアウトがラベル用に確保するフットプリント(高さ)も比例して広がります。

### node(プレーン図形:アイコンの代わりに図形+内部ラベル)

```yaml
- kind: node
  id: step1
  type: step1               # shape指定時は実質未使用(何でもよい)
  label: "処理A"
  style:
    shape: rounded            # rect / rounded / diamond / circle
    fillColor: "#D4E6FF"
    borderColor: "#2255AA"
```

`style.shape` を指定すると、アイコンではなく図形(四角/角丸/ひし形/円)を描き、その内部にラベルを中央揃えで表示します。[Mermaidフローチャートのインポート](mermaid-import.md)が内部的に使っている機能ですが、手書きのYAMLでも使えます。`labelPosition`/`labelGap` はこのモードでは効果がありません(ラベルは常に図形中央)。

## 座標とサイズ

- `x`/`y` を指定 → 親コンテナ内での絶対配置(左上原点からの相対座標)。**両方セットで指定**(片方だけはスキーマエラー)。
- `x`/`y` を省略 → 親の `layout` に従って自動配置。
- 同一コンテナ内で座標指定の子と自動配置の子は混在可能。
- `width`/`height` 省略時:コンテナは子に合わせて自動サイズ、ノードは `size`(指定があれば)、それも無ければ既定アイコンサイズ。
- ノードの `size` は `width`/`height` を同時に設定するショートハンドです。軸ごとに `width`/`height` を明示すればそちらが優先され、`size` はその軸で無視されます。

## 自動レイアウト(`layout`)

`x`/`y` を持たない子に適用されます。

| フィールド | 既定 | 説明 |
|---|---|---|
| `direction` | `grid` | `horizontal` / `vertical` / `grid` |
| `columns` | 自動 | grid の列数 |
| `gap` | 24 | 子どうしの間隔 |
| `padding` | 32 | コンテナ内側の余白 |

!!! note "v1の制約"
    自動配置は既に座標指定された子を避けずに詰める第一版仕様です。重なりが生じた場合は zook が Warning として検出しますが、自動では回避しません。PowerPoint 上で手直ししてください(詳細は[既知の制約](limitations.md))。

## links(接続線)

```yaml
links:
  - from: web
    to: db
    label: "3306"       # 任意
    labelFontSize: 8      # ラベル文字サイズ(pt、既定8)。label が無ければ無効
    arrow: end            # end(既定) / both / none
    style: straight        # straight(既定) / elbow / curved
    fromSide: bottom       # 任意。接続辺を明示指定(top/bottom/left/right)
    toSide: top             # 任意。省略時は自動選択
    waypoints:              # 任意。経路が通る中間点(キャンバス絶対座標)
      - {x: 470, y: 150}
      - {x: 470, y: 360}
```

- `from`/`to` はノードでもコンテナでも参照可能。存在しない `id` を参照すると Fatal エラーになります。
- `links` を丸ごと省略すれば「線なし、エリア内に配置するだけ」の図になります。
- `style` は `straight`/`elbow`/`curved` を明示的に選べます。`style` を省略(既定 `straight`)した場合でも、接続点同士が水平・垂直どちらでもない(斜め)ときは自動的に `elbow`(直角の折れ線)で描画されます。斜めの直線は AWS 構成図の直交ルーティングの慣習に合わないためです。`elbow`/`curved` を明示指定すればこの自動変換は行われません。
- `fromSide`/`toSide` で接続する辺を指定できます。
    - 両方指定する場合、軸(`top`/`bottom`は垂直、`left`/`right`は水平)が矛盾する組み合わせ(例: `fromSide: bottom` + `toSide: left`)は Fatal エラーになります。
    - 片方だけ指定した場合、その軸を維持したままもう片方は自動選択されます。
    - 両方省略した場合は自動選択です。単純な位置関係(dx/dyの大小)だけでなく、ラベル回避のオフセットまで含めた実際の経路長を比較し、支配的な軸の経路が明らかに(20%以上)長くなる場合のみ逆の軸に切り替えます。単なる僅差では切り替わらないため、直感に反する不安定な選択を避けています。
- `waypoints` で経路が通る中間点を明示できます。指定した点を順に通る直線折れ線として描画され(`style` の自動取り回しは無効)、障害物の迂回や任意のL字経路に使えます。両端は各中間点の向いている辺に自動接続されます(`fromSide`/`toSide` があればそちらが優先)。中間点を明示するため、`fromSide`/`toSide` の軸一致ルールは `waypoints` 併用時には適用されません。座標はキャンバス絶対座標です(要素の `x`/`y` はローカル座標ですが、リンクはどのコンテナにも属さないため絶対座標で指定します)。
- ノードの `labelPosition: below`/`above` でラベルが付いている場合、そのラベルと同じ辺(below→下方向、above→上方向)から出るリンクは、ラベルを避けてその外側に接続されます。左右方向の接続はラベル位置の影響を受けません。

## 完全な例

```yaml
version: "1.0"

canvas:
  aspectRatio: "16:9"
  padding: 40

elements:
  - kind: container
    id: vpc-main
    type: vpc
    provider: aws
    label: "Production VPC"
    layout:
      direction: horizontal
      gap: 48
      padding: 40
    children:
      - kind: container
        id: az-a
        type: az
        label: "ap-northeast-1a"
        layout:
          direction: vertical
          gap: 32
        children:
          - kind: node
            id: web-a
            type: EC2
            label: "WebServer A"
          - kind: node
            id: db-a
            type: RDS
            label: "Primary DB"

      - kind: container
        id: az-c
        type: az
        label: "ap-northeast-1c"
        layout:
          direction: vertical
          gap: 32
        children:
          - kind: node
            id: web-c
            type: EC2
            label: "WebServer C"
          - kind: node
            id: fn-c
            type: Lambda
            label: "Batch Worker"

  # Node placed outside the VPC with an absolute position
  - kind: node
    id: bucket
    type: S3
    label: "Asset Bucket"
    x: 1080
    y: 300
    width: 96
    height: 96

links:
  - from: web-a
    to: db-a
    label: "3306"
  - from: web-c
    to: fn-c
    arrow: end
    style: elbow
  - from: web-c
    to: bucket
    arrow: none
```

このサンプルは [`docs/example.yaml`](https://github.com/taka-sho/zook/blob/main/docs/example.yaml) としてリポジトリに同梱されており、JSON Schema 検証済みです。
