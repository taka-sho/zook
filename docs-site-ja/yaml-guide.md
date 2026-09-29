# YAML入力仕様

[🇬🇧 English](/zook/yaml-guide/){ .md-button }

zook の入力 YAML は [`zook.schema.json`](https://github.com/taka-sho/zook/blob/main/docs/zook.schema.json)(JSON Schema Draft 2020-12)で厳密に定義されています。本ページはその要点をまとめたものです。完全な仕様は [`docs/yaml-spec.md`](https://github.com/taka-sho/zook/blob/main/docs/yaml-spec.md) を参照してください(`zook guide yaml` で仕様を、`zook schema` でスキーマを表示できます)。

YAML language server に対応したエディタ(VS Code の YAML 拡張など)では、1行目でスキーマを指定すると、入力中に図を検証できます。

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/taka-sho/zook/main/docs/zook.schema.json
```

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
| `background` | | 背景色 `#RRGGBB`。暗い色にすると、読みにくくなるラベル・枠・線は白に切り替わる |
| `overlapMargin` | | 重なり検知で各要素の周囲に追加するバッファ(論理単位、既定 0)。0 は文字通りの重なりのみ検知、大きくすると近接している要素・リンク経路も検知対象になる |
| `layout` | | 最上位要素の並べ方。`direction`(既定 `grid` / `horizontal` / `vertical`)、`columns`、`gap`(既定 64)。`columns` を省略した grid は、スライドに最も収まる列数を自動で選びます |
| `fit` | | `shrink`(既定): スライドに収まらない図は、文字も含めて一様に縮小して中央に配置します。収まる図はそのままです。`none`: レイアウトどおりに描き、スライドからはみ出したものを Warning にします |

論理座標系は `16:9` で 1280×720、`4:3` で 960×720。原点は左上、+x が右、+y が下です。

70% を下回る縮小は、文字も同じだけ小さくなるため Warning になります。読めないほど小さくする前に、図を分けるか `gap`/`padding` を詰めてください。

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

ラベル帯の大きさはラベルの文字列から測ります。`label` を省略した場合のレジストリ既定ラベル(例: 「VPC」「AWS Cloud」)も対象です。自動サイズのコンテナは長いラベルに合わせて(最大 260 単位まで)広がり、それでも収まらないラベルは折り返して全行分を確保します。`labelPosition: bottom-left` のときは、帯を上ではなく下に確保します。`style.labelFontSize` を大きくすると帯も比例して広がります。`borderColor`/`fillColor`/`borderWidth` は、個別のコンテナだけアイコンレジストリの既定スタイル([アイコン・レジストリ](icons.md)参照)から色・線幅を変えたい場合に指定します。

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

ラベルの大きさは文字列から測ります(日本語・中国語・韓国語の全角文字は、半角英字のおよそ2倍の幅として数えます)。長いラベルはノードのフットプリントを最大 150 単位まで広げ、それを超えると折り返します。`\n` で明示的に改行でき、自動レイアウトは全行分の領域を確保します。そのため、長いラベルや複数行のラベルは次の行に食い込まずに次の行を押し下げ、重なり検知も実際の文字列を基準に判定します。`labelPosition: right` では、アイコンの横にラベル幅分を確保します。`labelGap`/`labelFontSize` を大きくすると、確保する領域もそれに合わせて広がります。

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
- `width`/`height` 省略時:コンテナは子(と自身のラベル)に合わせて自動サイズ、ノードは `size`(指定があれば)、それも無ければ既定アイコンサイズ。プレーン図形ノードは、最も長い単語が途中で折れないよう横に(既定幅の2倍まで)広がり、折り返した文字列が収まるよう縦に伸びます。折り返しは図形の文字領域の中で行い、ひし形の場合は中央の半分だけが文字領域です。
- ノードの `size` は `width`/`height` を同時に設定するショートハンドです。軸ごとに `width`/`height` を明示すればそちらが優先され、`size` はその軸で無視されます。

## 自動レイアウト(`layout`)

`x`/`y` を持たない子に適用されます。

| フィールド | 既定 | 説明 |
|---|---|---|
| `direction` | `grid` | `horizontal` / `vertical` / `grid` |
| `columns` | 自動 | grid の列数 |
| `gap` | 24 | 子どうしの間隔 |
| `padding` | 32 | コンテナ内側の余白 |

- `grid`: 各列はその列でいちばん幅の広い要素に、各行はいちばん背の高い要素に合わせます(最大の要素に合わせた均一なセルにはしません)。
- ノードだけが並ぶ行・列では、アイコンの中心を1本の線にそろえます。そのため、大きさの違うアイコン同士をつなぐリンクもまっすぐになります。コンテナを含む行・列は、先頭(上端・左端)にそろえます。
- 自動配置の子が明示座標の兄弟と重なる場合は、その兄弟を避けるよう下に押し出します(単純な押し出しなので、解消しきれない重なりは引き続き Warning になります。[既知の制約](limitations.md)参照)。

## links(接続線)

```yaml
links:
  - from: web
    to: db
    label: "3306"       # 任意
    labelFontSize: 8      # ラベル文字サイズ(pt、既定8)。label が無ければ無効
    color: "#E7157B"      # 任意。線と矢じりの色(既定はグレー)
    line: dashed          # solid(既定) / dashed / dotted
    width: 2              # 線の太さ(pt、既定1.25)。矢じりも比例して大きくなる
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
    - 両方省略した場合は自動選択です。横方向と縦方向の経路のうち、ほかの要素を横切る数が少ない方を選びます。同数の場合は、単純な位置関係(dx/dyの大小)だけでなく、ラベル回避のオフセットまで含めた実際の経路長を比較し、支配的な軸の経路が明らかに(20%以上)長くなる場合のみ逆の軸に切り替えます。単なる僅差では切り替わらないため、直感に反する不安定な選択を避けています。
    - 両端を**同じ辺**(`top`/`top`、`right`/`right` など)にすると、U字の経路になります。両端から外側へ出て、外側の要素を回り込んで戻る形なので、間にある要素を避けて通したいときに使えます。
- `waypoints` で経路が通る中間点を明示できます。指定した点を順に通る直線折れ線として描画され(`style` の自動取り回しは無効)、障害物の迂回や任意のL字経路に使えます。両端は各中間点の向いている辺に自動接続されます(`fromSide`/`toSide` があればそちらが優先)。中間点を明示するため、`fromSide`/`toSide` の軸一致ルールは `waypoints` 併用時には適用されません。座標はキャンバス絶対座標です(要素の `x`/`y` はローカル座標ですが、リンクはどのコンテナにも属さないため絶対座標で指定します)。
- ノードの `labelPosition: below`/`above` でラベルが付いている場合、そのラベルと同じ辺(below→下方向、above→上方向)から出るリンクは、ラベルを避けてその外側に接続されます。左右方向の接続はラベル位置の影響を受けません。
- 要素から自分自身へのリンク(リトライのループなど)は、その要素の角を回るループとして描きます(`fromSide`/`toSide` で隣り合う2辺を指定しない限り、右辺から上辺へ)。コンテナと、その中の要素を結ぶリンクは、その要素から枠の最も近い点へまっすぐ引きます。同じ2要素を結ぶリンクが複数ある場合は、並べて描きます。
- リンクの `label` は文字列から大きさを測り(120 単位を超えると折り返します)、描かれる経路の中間点に置きます。ただし、そこに置くとリンクの端(隣り合うアイコン間の短い矢印など)や両端のアイコンを隠してしまう場合は、線のすぐ横(必要ならアイコンの外側)の最も近い空き位置に移し、矢じりとアイコンが見えるようにします。

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
