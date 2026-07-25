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
Usage: archdiagram [OPTIONS] INPUT_PATH

Options:
  -o, --output FILE  Output .pptx path.  [required]
  --registry FILE    Optional icon registry YAML layered on top of the built-
                      in AWS registry (same keys override).
  --help              Show this message and exit.
```

## 動作確認

同梱のサンプル YAML(`docs/example.yaml`)から pptx を生成できることを確認してください。

```bash
.venv/bin/archdiagram docs/example.yaml -o example.pptx
```

`Wrote example.pptx` と表示され、終了コード `0` であれば成功です。

## テストの実行

```bash
.venv/bin/pytest tests/ -v
```
