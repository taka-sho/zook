# draw.io連携(継続的な構成図管理)

[🇬🇧 English](/zook/drawio-sync/){ .md-button }

zookで生成した構成図を[draw.io](https://www.diagrams.net/)で手直しし、その位置・サイズの変更をYAMLに機械的に反映できます。ワンショットで生成して終わりではなく、構成図を継続的に更新・管理していく運用を想定した機能です。

## できること・できないこと

- **できる**:draw.io上で要素の位置・サイズを変更したものを、YAMLの`x`/`y`/`width`/`height`として反映する。リンクに追加(または削除)した折れ点を、そのリンクの`waypoints`として反映する
- **できない**:ノード・コンテナ・リンクの追加/削除、別のコンテナへの要素の移動、色やスタイル・ラベルの変更を反映する。これらは引き続きYAML側で行ってください。sync はこうした編集を黙って無視せず、それぞれ Warning として報告します

追加・削除・色変更を反映しないのは制約ではなく設計判断です。YAMLを唯一の真実源として保ち続けるための境界線として、位置・サイズの同期だけに機能を絞っています。

## 基本フロー

```bash
# 1. ベースの構成図をdraw.io形式で書き出す
zook export-drawio diagram.yaml -o diagram.drawio

# 2. draw.io で開いて位置・サイズを調整し、保存する

# 3. 変更をYAMLに反映する
zook sync diagram.yaml diagram.drawio -o diagram.yaml
```

`export-drawio` は、各要素をどこに配置したかを .drawio ファイルの非表示のセルに記録します。`sync` はこの記録と draw.io のファイルを比べるので、**draw.io で実際に編集したものだけ**を明示座標(`x`/`y`/`width`/`height`)として書き戻し、触っていない要素は自動配置のまま維持されます。比較の基準がエクスポート時点なので、YAML を変更する*前*にエクスポートした .drawio を sync しても、すべての要素が古い位置に固定されることはありません。sync は「エクスポート後に YAML が変わった」と警告したうえで、draw.io での編集だけを書き戻します(記録のない、古い zook でエクスポートした .drawio では、YAML の現在のレイアウトを基準にします)。

自動配置の要素を1つ動かすと、その要素はコンテナの自動配置から外れるため、兄弟要素が詰め直されてしまいます。そこで sync は、編集を書き込んだあとに YAML をもう一度レイアウトし、.drawio で見えていた位置からずれた要素も固定して、両者が一致するまで繰り返します。何も動かしていなければ YAML は書き換えません。書き換える場合も、ファイルのコメント・キー順序・インデントの書き方は保持します。

```bash
$ zook sync diagram.yaml diagram.drawio -o diagram.yaml
Warning: element 'old-node' not found in 'diagram.drawio' - was it deleted in draw.io? structural changes aren't synced; edit the YAML directly if intentional
Wrote diagram.yaml
```

- 既知の要素がdraw.io側で見つからない(削除された可能性がある)→ Warning。YAMLは変更されません
- draw.io側にYAMLにない図形やリンクが追加されている → Warning。無視されます
- 要素を別のコンテナへドラッグした、要素やリンクのラベルを書き換えた、リンクのつなぎ先を変えた → Warning。反映しません
- draw.io が `<object>`/`<UserObject>` で包んだ図形(リンクやツールチップを付けると包まれます)も、ほかの図形と同じように sync します
- 複数ページの .drawio では、zook が書き出したページ(`id="zook"`)を sync します。見つからない場合は先頭ページを使い、Warning を出します

いずれもFatalではなく継続可能なWarningです(zookの[エラーハンドリング](usage.md#error-handling)方針と同じ)。

## アイコンの見た目

`export-drawio`は、AWSの主要サービス・コンテナについてはdraw.io公式のAWS4シェイプライブラリを使って書き出します(draw.io上で見慣れた公式の見た目になります)。対応する公式シェイプが無いもの(GCP/Azureの全種別、AWSの一部アクターアイコン等)は、zook自身のPNGアイコンをそのまま埋め込みます。

## Git連携での自動化(推奨運用)

self-hosted draw.io にはGitHub/GitLab連携機能があり、リポジトリ上の`.drawio`ファイルを直接開いて編集・保存(コミット)できます。この保存をトリガーに、`.github/workflows/drawio-sync.yml`が自動的に`zook sync`を実行し、更新されたYAMLをPull Requestとして自動作成します。

```mermaid
sequenceDiagram
    participant U as 利用者
    participant D as draw.io (self-hosted)
    participant G as Git(GitHub/GitLab)
    participant CI as CI

    U->>D: diagram.drawio を開いて位置調整
    D->>G: 保存(コミット)
    G->>CI: push トリガー
    CI->>CI: zook sync 実行
    CI->>G: 差分があればPRを自動作成
```

- 対応関係は**同名ファイル規約**(`diagram.yaml` ⇔ `diagram.drawio`、同ディレクトリ)です
- `sync`実行結果に差分が無ければ(例:色だけ変更した等、同期対象外の変更のみだった場合)PRは作成されません
- 直接コミットではなくPRを作成する方式なので、保護ブランチのポリシーとも衝突せず、マージ前にレビューを挟めます
- push で追加・変更されたすべての `.drawio` を sync します(複数コミットの push も含みます。空白や日本語を含むファイル名も扱えます)。削除された `.drawio` は対象外です。sync に失敗したファイルはアノテーションで報告し、ほかのファイルの PR を作ったあとで実行を失敗扱いにします

### 自分のリポジトリでワークフローを使う

1. [`.github/workflows/drawio-sync.yml`](https://github.com/taka-sho/zook/blob/main/.github/workflows/drawio-sync.yml) を、自分のリポジトリの `.github/workflows/` にコピーします。
2. その中の `pip install -e .`(zook のリポジトリ自身から zook を入れる手順)を `pip install zook` に置き換えます。PyPI に公開されるまでは `pip install git+https://github.com/taka-sho/zook` を使ってください。
3. リポジトリの **Settings → Actions → General → Workflow permissions** で **Read and write permissions** を選び、**Allow GitHub Actions to create and approve pull requests** にチェックを入れます。これがないと PR の作成に失敗します。
4. 各図の `.yaml` は、同じ名前の `.drawio` と同じ場所に置きます。

## なぜdraw.ioなのか

PowerPointを手直し用のエディタとして使う案も検討しましたが、以下の理由でdraw.ioを採用しています。

- pptxのグループ(コンテナ)は`chOff`/`chExt`という子座標系のオフセット・スケールを持ち、PowerPoint上でグループをリサイズすると子要素の座標が暗黙にスケーリングされる。draw.ioのコンテナ(`container=1`)はリサイズしても子要素の座標がスケールされない、より単純なモデル
- draw.ioのファイル形式(mxGraph XML)はテキストなのでgit diffが取れる。継続的な管理・レビューと相性が良い
- セルフホストできるため、構成図(機密性のある情報になりうる)を社外のクラウドサービスに預けずに完結できる
- AWS/GCP/Azureの公式アイコンライブラリが標準搭載されている
