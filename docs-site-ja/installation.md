# インストール

[🇬🇧 English](/zook/installation/){ .md-button }

## 必要環境

- Python 3.10 以上
- (推奨)アイコンのラスタライズ品質を確認したい場合は LibreOffice などの pptx ビューア

## コマンドとしてインストールする

zook は PyPI には未公開です。pipx か uv を使い、GitHub から直接インストールしてください(専用の環境に入ります)。

```bash
pipx install git+https://github.com/taka-sho/zook.git
# または
uv tool install git+https://github.com/taka-sho/zook.git
```

AI エージェント向けの手順、YAML の全仕様、参考パターン、JSON Schema はすべてパッケージに含まれているので、リポジトリを clone する必要はありません。

```bash
zook guide                    # 手順を1ステップずつ表示(英語)
zook patterns list            # 参考アーキテクチャの一覧
zook init diagram.yaml --pattern serverless-api
zook validate diagram.yaml && zook build diagram.yaml -o diagram.pptx
```

## 開発用のセットアップ

リポジトリを clone し、仮想環境を作成してインストールします。

```bash
git clone https://github.com/taka-sho/zook.git
cd zook

python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

`zook` コマンドが使えるようになります。

```bash
.venv/bin/zook --help
```

```text
Usage: zook [OPTIONS] COMMAND [ARGS]...

  zook: generate PowerPoint architecture diagrams from a YAML definition.

Options:
  --version  Show the version and exit.
  --help     Show this message and exit.

Commands:
  build          Generate a .pptx from INPUT_PATH.
  diff           Show the structural difference between two diagrams...
  doctor         Auto-resolve overlaps and link-routing collisions in...
  export-drawio  Export INPUT_PATH as a .drawio file for manual editing...
  from-mermaid   Convert a Mermaid flowchart (INPUT_PATH, e.g.
  guide          Print a bundled guide.
  icons          Inspect the icon/group registry.
  init           Write a starter diagram to OUTPUT_PATH (default...
  patterns       The bundled reference architectures - start from the...
  preview        Render a quick PNG preview of INPUT_PATH (no...
  schema         Print the JSON Schema a diagram YAML is validated...
  sync           Sync position/size changes made in an edited DRAWIO_PATH...
  validate       Check INPUT_PATH for Fatal/Warning issues without...

  New to zook, or an AI agent writing a diagram? Start with `zook guide`.
```

各サブコマンドの詳細は[使い方](usage.md)を参照してください。

## 動作確認

同梱のサンプル YAML(`docs/example.yaml`)から pptx を生成できることを確認してください。

```bash
.venv/bin/zook build docs/example.yaml -o example.pptx
```

`Wrote example.pptx` と表示され、終了コード `0` であれば成功です。

## テストの実行

```bash
.venv/bin/pytest tests/ -v
```
