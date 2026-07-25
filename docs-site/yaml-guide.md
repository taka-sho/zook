# YAML入力仕様

archdiagram の入力 YAML は [`arch-diagram.schema.json`](https://github.com/taka-sho/archtecture-diagram-generator/blob/main/docs/arch-diagram.schema.json)(JSON Schema Draft 2020-12)で厳密に定義されています。本ページはその要点をまとめたものです。完全な仕様は [`docs/yaml-spec.md`](https://github.com/taka-sho/archtecture-diagram-generator/blob/main/docs/yaml-spec.md) を参照してください。

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

論理座標系は `16:9` で 1280×720、`4:3` で 960×720。原点は左上、+x が右、+y が下です。

## 要素(`elements` / `children`)

`kind` で2種類に判別されます。

### container(枠:VPC / AZ / subnet など)

```yaml
- kind: container
  id: vpc-main          # 図全体で一意
  type: vpc               # 自由文字列。vpc/az/subnet/region/account/group など
  provider: aws            # 既定 generic
  label: "Production VPC"
  layout:                  # 子の自動配置ルール(下記参照)
    direction: horizontal
    gap: 48
  children: [...]           # 入れ子(再帰)
```

### node(アイコン:EC2 / Lambda / RDS / S3 など)

```yaml
- kind: node
  id: web
  type: EC2                # アイコン解決キー。詳細は「アイコン・レジストリ」参照
  label: "WebServer"
  style:
    labelPosition: below    # below(既定) / above / right / none
```

## 座標とサイズ

- `x`/`y` を指定 → 親コンテナ内での絶対配置(左上原点からの相対座標)。**両方セットで指定**(片方だけはスキーマエラー)。
- `x`/`y` を省略 → 親の `layout` に従って自動配置。
- 同一コンテナ内で座標指定の子と自動配置の子は混在可能。
- `width`/`height` 省略時:コンテナは子に合わせて自動サイズ、ノードは既定アイコンサイズ。

## 自動レイアウト(`layout`)

`x`/`y` を持たない子に適用されます。

| フィールド | 既定 | 説明 |
|---|---|---|
| `direction` | `grid` | `horizontal` / `vertical` / `grid` |
| `columns` | 自動 | grid の列数 |
| `gap` | 24 | 子どうしの間隔 |
| `padding` | 32 | コンテナ内側の余白 |

!!! note "v1の制約"
    自動配置は既に座標指定された子を避けずに詰める第一版仕様です。重なりが生じた場合は PowerPoint 上で手直ししてください(詳細は[既知の制約](limitations.md))。

## links(接続線)

```yaml
links:
  - from: web
    to: db
    label: "3306"       # 任意
    arrow: end            # end(既定) / both / none
    style: straight        # straight(既定) / elbow / curved
```

- `from`/`to` はノードでもコンテナでも参照可能。存在しない `id` を参照すると Fatal エラーになります。
- `links` を丸ごと省略すれば「線なし、エリア内に配置するだけ」の図になります。

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

このサンプルは [`docs/example.yaml`](https://github.com/taka-sho/archtecture-diagram-generator/blob/main/docs/example.yaml) としてリポジトリに同梱されており、JSON Schema 検証済みです。
