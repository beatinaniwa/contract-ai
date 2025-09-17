# 契約書作成アシスタント（Excel出力 / Python + Streamlit）— Starter (uv 版)

このリポジトリは、**Astral uv** をフル活用した構成です。`pyproject.toml` に依存を定義し、
`uv lock` / `uv sync` / `uv run` で再現性の高い環境を素早く構築できます。

---

## セットアップ（初回）

```bash
# (任意) uv で Python 3.12 を導入
uv python install 3.12

# 依存を同期（dev ツールも入れる場合は --extra dev を付与）
uv sync --python 3.12 --extra dev
```

> `uv sync` は `uv.lock` が無い場合にロックを生成して解決します。既に `uv.lock` がある場合は
> そのロックに従ってインストールします。依存を更新したら `uv lock --upgrade` を実行してください。


### pre-commit のセットアップ

```bash
uv run pre-commit install
uv run pre-commit run --all-files  # 初回は全ファイルを検査
```

## 起動

```bash
# Streamlit を uv 経由で実行（.venv を自動利用）
uv run streamlit run app/streamlit_app.py
```

起動後、左側の「サンプル読込」→「抽出する」→ 右側のフォームで不足を補完 → **「Excel生成」**。
生成後に **「Excelをダウンロード」** ボタンが表示されます（`outputs/` にも保存）。

---

## 依存の追加・更新

```bash
# 例: 依存追加
uv add "requests>=2"

# 例: dev 依存追加（ruff を開発ツールとして）
uv add --extra dev "ruff>=0.4"

# 依存を最新へ更新
uv lock --upgrade
uv sync
```

---

## 主なファイル

- `pyproject.toml` … 依存定義（本番/開発は extras で分離）
- `app/templates/request_form_template.xlsx` … 名前付きセルの Excel テンプレート
- `app/mappings/excel_mapping.yaml` … フィールド→名前付きセルの対応表
- `app/services/excel_writer.py` … 差し込み処理（openpyxl）
- `app/services/extractor.py` … 抽出モック（後で LLM/RAG に差し替え）
- `app/models/schemas.py` … `ContractForm` の pydantic モデル
- `outputs/` … 生成ファイル・監査ログの保存先

---

## 注意（MVP）
- 抽出は簡易版（正規表現）。本番では LLM の Structured Output とスキーマ検証を追加してください。
- Streamlit の日付項目は未入力ができないため、既定値を日付（今日）にしています。

