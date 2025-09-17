# Repository Guidelines

## Project Structure & Module Organization
- `app/streamlit_app.py`: Streamlit entrypoint orchestrating extraction, validation, and Excel writing.
- Services in `app/services/` handle parsing (extractor), normalization, validation, audit logging, and template export.
- Schema definitions live in `app/models/schemas.py`; update when form fields change and mirror `app/mappings/excel_mapping.yaml`.
- Static assets: `app/templates/request_form_template.xlsx`, `app/policies/vocab.yaml`, `app/sample_data/example_input.txt`. Runtime exports go to `outputs/` (created at run time).
- Tests belong in `tests/`; mirror module layout so new services gain `tests/test_<module>.py` coverage.

## Build, Test, and Development Commands
- `uv sync --python 3.12 --extra dev` installs dependencies and dev tooling into `.venv`.
- `uv run streamlit run app/streamlit_app.py` launches the local UI for manual verification.
- `uv run pytest` executes the suite; append `-k` or `-vv` for focused runs.
- `uv run ruff check app tests` enforces the configured style; add `uv run ruff format` if formatting becomes part of the workflow.
- `uv run pre-commit install` sets up git hooks.
- `uv run pre-commit run --all-files` runs the checks before big pushes.
- `uv run mypy app` validates type hints; update stub packages when adding third-party APIs.

## Coding Style & Naming Conventions
Use Python 3.12 features with four-space indentation and descriptive snake_case names for modules, functions, and variables. Keep classes in PascalCase and Pydantic models centralized in `schemas.py`. Maintain focused, side-effect-light functions and push integration logic into services. Respect Ruff's 100-character line limit. Document intent in YAML or template updates when structure changes are not self-evident.

## Testing Guidelines
Pytest is the primary framework. Grow coverage beyond the placeholder by exercising critical services (Excel writer, validator edge cases, extractor fallbacks). Name files `test_<module>.py` and group assertions around user scenarios. Introduce shared fixtures in `tests/conftest.py` as reuse appears. Capture regression cases before modifying mappings or templates. Run `uv run pytest --maxfail=1` before submitting.

## Commit & Pull Request Guidelines
With no established history, adopt imperative, present-tense commit subjects scoped to the area touched (e.g., `Add audit trail persistence`). Keep feature work separate from formatting-only changes. For pull requests, provide a concise summary, risk notes, and the key commands executed. Link any related issues, and attach Streamlit screenshots or GIFs when UI behavior changes to aid reviewers.
