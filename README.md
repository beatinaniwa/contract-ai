# 契約書作成アシスタント（テキスト出力 / Python + Streamlit）— uv スターター

契約申請用の入力補助ツールです。打ち合わせメモや資料から Gemini 2.5 Pro がフォーム項目を抽出し、
回答の抜けを指摘・追質問しながら最終的にプレーンテキストとしてエクスポートします。Gemini を使えない
環境では内蔵の正規表現ロジックに自動フォールバックします。

主な特徴:
- `txt / md / pdf / pptx` ファイルの読み込みとテキスト抽出（`pypdf` / `python-pptx` 利用）
- Gemini 2.5 Pro での初回抽出 + 最大2ラウンドの追加入力サイクル
- 基本認証（任意）に対応し、共有環境でも安全に運用可能
- 抽出結果を Streamlit UI からコピー / ダウンロード可能なテキスト形式で出力
- Astral **uv** による再現性の高い Python 3.13 開発環境

---

## セットアップ（初回）

1. （任意）`uv python install 3.13`
2. 依存の同期
   ```bash
   uv sync --python 3.13 --extra dev
   ```
   `uv.lock` が既にある場合はロックに従ってインストールします。依存を更新したいときは
   `uv lock --upgrade` → `uv sync` を実行してください。
3. `.streamlit/secrets.example.toml` を `.streamlit/secrets.toml` にコピーします（空の値でも可）。

### 開発補助ツール

```bash
uv run pre-commit install
uv run pre-commit run --all-files  # 初回は全ファイルを検査
```

## 起動

```bash
uv run streamlit run app/streamlit_app.py
```

### アプリ内の基本的な流れ
1. 「資料をアップロード」から `txt/md/pdf/pptx` を読み込むか、テキスト欄に直接貼り付けます。
2. 「AIでフォームを自動入力」を押すと Gemini が抽出を試みます（Gemini 利用不可時は自動で
   正規表現抽出に切り替わります）。
3. 足りない項目がある場合は最大2ラウンドの追加入力質問が表示され、回答をフォームへ反映できます。
4. 必須項目が揃ったら「テキスト出力」を押すと、整形済みテキストが表示・ダウンロードできます。
   `outputs/contract_YYYYMMDD_HHMMSS.txt` にも保存されます。

## Gemini 設定

抽出処理は Google Gemini 2.5 Pro (`gemini-2.5-pro`) を前提にしています。Python SDK として
`google-genai` を利用しており、API キーは Streamlit secrets で管理します。

```bash
cp .streamlit/secrets.example.toml .streamlit/secrets.toml
```

```toml
# .streamlit/secrets.toml
gemini_api_key = "YOUR_GEMINI_API_KEY"
```

- Secrets ファイルを置かない場合はアプリ起動時にエラーになります。
- `gemini_api_key` を空のままにすると、Gemini の代わりに正規表現による簡易抽出が使われます。
- モデル名を変更したい場合は OS 環境変数 `GEMINI_MODEL` を設定してください（既定は
  `gemini-2.5-pro`）。
- Secrets の配置場所は `STREAMLIT_SECRETS_PATH` で上書きできます。

### Basic 認証（任意）

社内公開時などに Basic 認証を有効化できます。`secrets.toml` に以下を追記してください。

```toml
basic_auth_username = "your-username"
# 平文パスワードまたはハッシュのいずれかを設定（両方セットした場合はハッシュが優先）
basic_auth_password = "your-password"
# basic_auth_password_hash = "your-password-sha256-hex"
```

リバースプロキシ経由で `Authorization` ヘッダーが届く場合は自動認証し、ローカル実行時など
ヘッダーが無い場合は UI 上にログインフォームが表示されます。

---

## 依存の追加・更新

```bash
uv add "requests>=2"           # 例: 本番依存を追加
uv add --extra dev "ruff>=0.4" # 例: 開発用依存を追加
uv lock --upgrade
uv sync
```

---

## テスト / 静的検査

```bash
uv run pytest --maxfail=1
uv run ruff check app tests
uv run mypy app
```

## フォルダ構成メモ

- `app/streamlit_app.py` … Streamlit エントリーポイント
- `app/config_loader.py` … Secrets 読み込みユーティリティ
- `app/services/text_loader.py` … `txt/md/pdf/pptx` からのテキスト抽出
- `app/services/extractor.py` … Gemini 抽出 / 追加入力反映ロジックと正規表現フォールバック
- `app/services/plaintext_writer.py` … フォーム値をプレーンテキストに整形
- `app/services/basic_auth.py` … Basic 認証ハンドリング
- `app/models/schemas.py` … `ContractForm` の Pydantic モデル
- `app/mappings/csv_mapping.yaml` / `app/services/csv_writer.py` … CSV エクスポート用の既存実装
- `tests/` … 各サービスの単体テスト
- `outputs/` … 実行時に生成されるテキスト出力（git 管理外）

---

## 補足
- Gemini 利用時に安全フィルターでブロックされた場合は警告メッセージを表示し、結果は正規表現抽出に
  フォールバックします。
- PDF や PPTX の構造によっては文字抽出ができない場合があります。その際はエラーメッセージを表示して
  元テキスト欄は更新されません。
- 正規表現フォールバックでは必須項目が埋まらない場合があるため、追加入力で補完してください。
