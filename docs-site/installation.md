# インストール

## 必要環境

- Python 3.10 以上
- (推奨)アイコンのラスタライズ品質を確認したい場合は LibreOffice などの pptx ビューア

## セットアップ

リポジトリを clone し、仮想環境を作成してインストールします。

```bash
git clone https://github.com/taka-sho/archtecture-diagram-generator.git
cd archtecture-diagram-generator

python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

`archdiagram` コマンドが使えるようになります。

```bash
.venv/bin/archdiagram --help
```

```text
Usage: archdiagram [OPTIONS] COMMAND [ARGS]...

  archdiagram: generate PowerPoint architecture diagrams from a YAML
  definition.

Options:
  --help  Show this message and exit.

Commands:
  build          Generate a .pptx from INPUT_PATH.
  export-drawio  Export INPUT_PATH as a .drawio file for manual editing...
  icons          Inspect the icon/group registry.
  preview        Render a quick PNG preview of INPUT_PATH (no...
  sync           Sync position/size changes made in an edited DRAWIO_PATH...
  validate       Check INPUT_PATH for Fatal/Warning issues without...
```

各サブコマンドの詳細は[使い方](usage.md)を参照してください。

## 動作確認

同梱のサンプル YAML(`docs/example.yaml`)から pptx を生成できることを確認してください。

```bash
.venv/bin/archdiagram build docs/example.yaml -o example.pptx
```

`Wrote example.pptx` と表示され、終了コード `0` であれば成功です。

## テストの実行

```bash
.venv/bin/pytest tests/ -v
```
