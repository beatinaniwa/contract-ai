# Repository Guidelines

## Project Structure & Module Organization
- `app/streamlit_app.py`: Streamlit entrypoint orchestrating extraction, validation, and Excel writing.
- Services in `app/services/` handle parsing (extractor), normalization, validation, audit logging, and template export.
- Schema definitions live in `app/models/schemas.py`; update when form fields change and mirror `app/mappings/excel_mapping.yaml`.
- Static assets: `app/templates/request_form_template.xlsx`, `app/policies/vocab.yaml`, `app/sample_data/example_input.txt`. Runtime exports go to `outputs/` (created at run time).
- Tests belong in `tests/`; mirror module layout so new services gain `tests/test_<module>.py` coverage.

## Build, Test, and Development Commands
- `uv sync --python 3.13 --extra dev` installs dependencies and dev tooling into `.venv`.
- `uv run streamlit run app/streamlit_app.py` launches the local UI for manual verification.
- `uv run pytest` executes the suite; append `-k` or `-vv` for focused runs.
- `uv run ruff check app tests` enforces the configured style; add `uv run ruff format` if formatting becomes part of the workflow.
- `uv run pre-commit install` sets up git hooks.
- `uv run pre-commit run --all-files` runs the checks before big pushes.
- `uv run mypy app` validates type hints; update stub packages when adding third-party APIs.

## Coding Style & Naming Conventions
Use Python 3.13 features with four-space indentation and descriptive snake_case names for modules, functions, and variables. Keep classes in PascalCase and Pydantic models centralized in `schemas.py`. Maintain focused, side-effect-light functions and push integration logic into services. Respect Ruff's 100-character line limit. Document intent in YAML or template updates when structure changes are not self-evident.

## Testing Guidelines
Pytest is the primary framework. Grow coverage beyond the placeholder by exercising critical services (Excel writer, validator edge cases, extractor fallbacks). Name files `test_<module>.py` and group assertions around user scenarios. Introduce shared fixtures in `tests/conftest.py` as reuse appears. Capture regression cases before modifying mappings or templates. Run `uv run pytest --maxfail=1` before submitting.

## Continuous Integration (CircleCI)
- GitHub 上の CircleCI でテストが自動実行されます。
- 実行環境: `cimg/python:3.13`。依存関係は `uv sync --python 3.13 --extra dev` で解決します。
- CI 実行コマンド（config に準拠）:
  - テスト: `uv run pytest -q --maxfail=1`
  - Lint: `uv run ruff check app tests`
  - 型チェック: `uv run mypy app`
- キャッシュ: `.venv` と `.uv-cache` を `uv.lock` のチェックサムでキャッシュします。
- 秘密情報は不要（Gemini はテスト時にスタブ/フォールバック）。必要なら CircleCI 上の Project 設定で環境変数を追加してください。

## Commit & Pull Request Guidelines
With no established history, adopt imperative, present-tense commit subjects scoped to the area touched (e.g., `Add audit trail persistence`). Keep feature work separate from formatting-only changes. For pull requests, provide a concise summary, risk notes, and the key commands executed. Link any related issues, and attach Streamlit screenshots or GIFs when UI behavior changes to aid reviewers.

### Pull Request 作成ポリシー（gh CLI）
- PR のタイトル・説明は、専門用語に偏りすぎない「わかりやすい日本語」で書く。
- 変更目的 → 主な変更点 → 影響/互換性 → 動作確認手順 → リスク/フォローアップの順で簡潔に整理する。
- 可能な限り GitHub CLI（`gh`）を用いて PR を作成する。
  - 例（ドラフト PR）:
    - `gh pr create -B main -H <feature-branch> -t "機能名の追加（概要）" -F PR_BODY.md -d`
  - 例（通常 PR）:
    - `gh pr create -B main -H <feature-branch> -t "出力項目名の統一と選択式UIの実装" -F PR_BODY.md`
- PR 本文ファイルはリポジトリ直下の `PR_BODY.md` を毎回利用する。個人編集用のため `.gitignore` に追加済み（コミットしない）。
- 画面変更がある場合はスクリーンショット/簡易GIFを添付し、レビュアーが確認しやすい状態にする。
- テスト・lint コマンド（例: `uv run pytest -q`, `uv run ruff check app tests`）を記載し、確認痕跡を残す。

#### PR_BODY.md テンプレートの使い方
- ルートの `PR_BODY.md` はテンプレートです。`<>` のプレースホルダーを置き換え、不要セクションは削除してください。
- 主なセクション: 概要 / 目的 / 変更内容 / スコープ外 / 影響・互換性 / 動作確認手順 / スクショ / 関連Issue / チェックリスト / リスク・ロールバック / 補足
- 作成コマンド例: `gh pr create -B main -H <feature-branch> -t "<変更タイトル>" -F PR_BODY.md`

## GitHub CLI（gh）の使い方
チーム全体で gh を活用し、同一手順での運用を徹底します。タイトルや本文は「わかりやすい日本語」を心がけてください。

- 初期設定/便利設定
  - `gh auth login`（GitHub 認証）
  - `gh config set prompt disabled true`（非対話を好む場合）
  - 便利エイリアス例: `gh alias set prc 'pr create -B main -t "$(git log -1 --pretty=%s)" -F PR_BODY.md'`

- PR 作成/編集/レビュー
  - 作成: `gh pr create -B main -H <branch> -t "<タイトル>" -F PR_BODY.md`
  - 編集: `gh pr edit <番号> -t "<新タイトル>" -F PR_BODY.md`
  - レビュリクエスト: `gh pr edit <番号> -r user1,user2` / `-a @me` でアサイン
  - 差分表示: `gh pr diff <番号>` / `gh pr view <番号> -w`（Web）
  - ステータス/チェック: `gh pr status` / `gh pr checks <番号>`
  - コメント: `gh pr comment <番号> -b "<コメント>"`
  - 承認/変更要求: `gh pr review <番号> --approve` / `--request-changes -b "<理由>"`
  - マージ: `gh pr merge <番号> --squash --delete-branch`（規約に合わせて `--merge`/`--rebase`）
  - チェックアウト: `gh pr checkout <番号>`（ローカルでレビュー）

- Issue 運用
  - 作成: `gh issue create -t "<タイトル>" -b "<本文>" -l bug,needs-triage -a @me`
  - 一覧/検索: `gh issue list -s open -l bug --assignee @me`
  - 詳細/コメント: `gh issue view <番号>` / `gh issue comment <番号> -b "<コメント>"`
  - クローズ: `gh issue close <番号> -c "<クローズ理由>"`

- リポジトリ/ナビゲーション
  - リポ表示/ブラウザ: `gh repo view` / `gh browse`
  - ファイル/行へ: `gh browse app/streamlit_app.py:42`（GitHub 上の該当行を開く）

- ラベル/メンテナンス
  - ラベル追加: `gh label create "enhancement" -c "#3FB950" -d "機能追加"`
  - ラベル付与: `gh issue edit <番号> -l enhancement` / `gh pr edit <番号> -l enhancement`

- リリース（必要時）
  - 作成: `gh release create v0.1.0 --notes "初回リリース"`
  - アセット添付: `gh release upload v0.1.0 outputs/*.csv`

- API 高度操作（最終手段）
  - `gh api repos/:owner/:repo/pulls/<番号>`（REST API で直接参照/更新）

注意
- 本リポジトリの CI は CircleCI を使用。`gh pr checks` で PR の外部チェック結果を確認可能。GitHub Actions 用の `gh run` は原則未使用。
- PR 本文は常に `PR_BODY.md` から供給し、わかりやすい日本語で記載。
