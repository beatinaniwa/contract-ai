# 契約書作成アシスタント（CSV出力 / Python + Streamlit）— Starter (uv 版)

このリポジトリは、**Astral uv** をフル活用した構成です。`pyproject.toml` に依存を定義し、
`uv lock` / `uv sync` / `uv run` で再現性の高い環境を素早く構築できます。

---

## セットアップ（初回）

```bash
# (任意) uv で Python 3.13 を導入
uv python install 3.13

# 依存を同期（dev ツールも入れる場合は --extra dev を付与）
uv sync --python 3.13 --extra dev
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

起動後、左側の「サンプル読込」→「抽出する」→ 右側のフォームで不足を補完 → **「CSV出力」**。
生成後に **「CSVをダウンロード」** ボタンが表示されます（`outputs/` にも保存）。

## Gemini 設定

抽出処理は Google Gemini 2.5 Pro (`gemini-2.5-pro`) を利用します。Python SDK は
`google-genai` を採用しているため、`uv sync` 済みの環境で利用してください。API キーは
プロジェクト内の設定ファイルで管理します。

1. `.streamlit/secrets.example.toml` を `.streamlit/secrets.toml` にコピーします。
2. `gemini_api_key` に発行したキーを設定します。

```toml
# .streamlit/secrets.toml
gemini_api_key = "your-secret"
```

`.streamlit/secrets.toml` は `.gitignore` 済みです。必要に応じて `STREAMLIT_SECRETS_PATH` 環境変数で読み込むファイルパスを上書きできます。
Secrets ファイルが存在しない、もしくはキーが空の場合は、従来どおりの簡易正規表現による抽出に自動でフォールバックします。

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
- `.streamlit/secrets.example.toml` … Gemini API キー設定のサンプル
- `app/mappings/csv_mapping.yaml` … CSV のヘッダ並びとマッピング定義（UTF-8 BOM）
- `app/services/csv_writer.py` … CSV 1行出力ロジック
- `app/templates/request_form_template.xlsx` … 旧 Excel テンプレート（レガシー）
- `app/mappings/excel_mapping.yaml` … 旧 Excel 向けマッピング（レガシー）
- `app/services/excel_writer.py` … 旧 Excel 差し込み処理（レガシー）
- `app/services/extractor.py` … Gemini 2.5 Pro 抽出 + 正規表現フォールバック
- `app/models/schemas.py` … `ContractForm` の pydantic モデル
- `outputs/` … 生成ファイル・監査ログの保存先

---

## 注意（MVP）
- Gemini API キー設定時は LLM 抽出、未設定時は正規表現による簡易抽出で動作します。
- Streamlit の日付項目は未入力ができないため、既定値を日付（今日）にしています。
