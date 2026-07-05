from __future__ import annotations

import os
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, Response, render_template_string, request
from flask.typing import ResponseReturnValue
from werkzeug.exceptions import RequestEntityTooLarge

from .config import ProjectPaths
from .pipeline import pipeline
from .services.article_selector import ArticleFilter, ArticleSelector
from .services.tts import build_default_audio_generator
from .services.dedup import DuplicateArticleError
from .services.fetcher import _normalize_knigovishte_url
from .services.translator import LangblyTimeoutError

WEB_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("obshtestvo", "Society"),
    ("sviat", "World"),
    ("nauka", "Science"),
    ("kultura", "Culture"),
    ("sport-i-zdrave", "Sports and Health"),
    ("pishat-ni", "Letters"),
)
WEB_CATEGORY_SLUGS = {slug for slug, _label in WEB_CATEGORIES}
MAX_FORM_BODY_BYTES = 4_096
MAX_URL_LENGTH = 2_048
MAX_FILTER_VALUE_LENGTH = 32
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "script-src 'self' 'unsafe-inline'; "
        "base-uri 'none'; "
        "form-action 'self'"
    ),
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
UNEXPECTED_ERROR_MESSAGE = (
    "Something unexpected went wrong while building the episode. "
    "Please retry later or use the CLI locally for full diagnostics."
)

PAGE_TEMPLATE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="robots" content="noindex, nofollow">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Knigovishte Podcast Builder</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
      :root {
        --bg-gradient: linear-gradient(135deg, #0b0f19 0%, #111827 100%);
        --card-bg: rgba(30, 41, 59, 0.7);
        --card-border: rgba(255, 255, 255, 0.08);
        --text-primary: #f3f4f6;
        --text-secondary: #9ca3af;
        --accent-primary: #3b82f6;
        --accent-secondary: #8b5cf6;
        --accent-gradient: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
        --input-bg: rgba(17, 24, 39, 0.6);
        --input-border: rgba(255, 255, 255, 0.1);
        --input-focus-border: #3b82f6;
        --success-bg: rgba(16, 185, 129, 0.15);
        --success-border: rgba(16, 185, 129, 0.3);
        --success-text: #34d399;
        --error-bg: rgba(239, 68, 68, 0.15);
        --error-border: rgba(239, 68, 68, 0.3);
        --error-text: #f87171;
      }

      * { box-sizing: border-box; margin: 0; padding: 0; }

      body {
        font-family: 'Inter', -apple-system, sans-serif;
        background: var(--bg-gradient);
        color: var(--text-primary);
        min-height: 100vh;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        padding: 2rem 1rem;
        line-height: 1.6;
      }

      .container {
        width: 100%;
        max-width: 32rem;
        display: flex;
        flex-direction: column;
        gap: 2rem;
      }

      header {
        text-align: center;
      }

      h1 {
        font-size: 2.25rem;
        font-weight: 700;
        letter-spacing: -0.025em;
        margin-bottom: 0.5rem;
        background: var(--accent-gradient);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
      }

      .subtitle {
        color: var(--text-secondary);
        font-size: 0.95rem;
      }

      form {
        display: flex;
        flex-direction: column;
        gap: 1.25rem;
        padding: 2rem;
        border: 1px solid var(--card-border);
        border-radius: 1rem;
        background: var(--card-bg);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.3);
      }

      .form-group {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
      }

      label {
        font-weight: 500;
        font-size: 0.875rem;
        color: var(--text-primary);
      }

      input[type="text"], input[type="number"], select {
        width: 100%;
        padding: 0.75rem 1rem;
        background: var(--input-bg);
        border: 1px solid var(--input-border);
        border-radius: 0.5rem;
        color: var(--text-primary);
        font-family: inherit;
        font-size: 0.95rem;
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
      }

      input[type="text"]::placeholder, input[type="number"]::placeholder {
        color: rgba(156, 163, 175, 0.5);
      }

      input[type="text"]:focus, input[type="number"]:focus, select:focus {
        outline: none;
        border-color: var(--input-focus-border);
        box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25);
      }

      select {
        appearance: none;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%239ca3af'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M19 9l-7 7-7-7'/%3E%3C/svg%3E");
        background-repeat: no-repeat;
        background-position: right 1rem center;
        background-size: 1.25rem;
        padding-right: 2.5rem;
      }

      .filters {
        display: grid;
        gap: 1rem;
        grid-template-columns: 1fr 1fr;
      }

      .checkbox-group {
        flex-direction: row;
        align-items: center;
        gap: 0.75rem;
        cursor: pointer;
        padding: 0.25rem 0;
      }

      .checkbox-group input {
        width: 1.15rem;
        height: 1.15rem;
        accent-color: var(--accent-primary);
        cursor: pointer;
      }

      .checkbox-label {
        font-size: 0.875rem;
        color: var(--text-secondary);
        user-select: none;
        cursor: pointer;
      }

      button {
        width: 100%;
        padding: 0.85rem;
        background: var(--accent-gradient);
        border: none;
        border-radius: 0.5rem;
        color: #ffffff;
        font-family: inherit;
        font-weight: 600;
        font-size: 1rem;
        cursor: pointer;
        transition: all 0.2s;
        box-shadow: 0 4px 14px 0 rgba(59, 130, 246, 0.4);
      }

      button:hover:not(:disabled) {
        transform: translateY(-1px);
        box-shadow: 0 6px 20px 0 rgba(59, 130, 246, 0.5);
      }

      button:active:not(:disabled) {
        transform: translateY(1px);
      }

      button:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }

      .panel {
        padding: 1.25rem;
        border-radius: 0.75rem;
        display: flex;
        align-items: flex-start;
        gap: 0.75rem;
        animation: fadeIn 0.3s ease-out;
      }

      .success {
        background: var(--success-bg);
        border: 1px solid var(--success-border);
        color: var(--success-text);
      }

      .error {
        background: var(--error-bg);
        border: 1px solid var(--error-border);
        color: var(--error-text);
        flex-direction: column;
        gap: 0.5rem;
      }

      .error h2 {
        font-size: 1.1rem;
        font-weight: 600;
      }

      .error p {
        font-size: 0.9rem;
        opacity: 0.9;
      }

      .status {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.75rem;
        margin-top: 0.5rem;
        color: var(--accent-primary);
        font-weight: 500;
        font-size: 0.95rem;
        animation: pulse 1.5s infinite ease-in-out;
      }

      .status[hidden] { display: none; }

      .spinner {
        width: 1.25rem;
        height: 1.25rem;
        border: 2px solid rgba(59, 130, 246, 0.2);
        border-top-color: var(--accent-primary);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
      }

      @keyframes spin {
        to { transform: rotate(360deg); }
      }

      @keyframes pulse {
        0%, 100% { opacity: 0.6; }
        50% { opacity: 1; }
      }

      @keyframes fadeIn {
        from { opacity: 0; transform: translateY(8px); }
        to { opacity: 1; transform: translateY(0); }
      }
    </style>
  </head>
  <body>
    <div class="container">
      <header>
        <h1>Podcast Builder</h1>
        <p class="subtitle">Convert Bulgarian articles to bilingual audio feed episodes</p>
      </header>

      <form id="podcast-form" method="post">
        <div class="form-group">
          <label for="url">Article URL (optional)</label>
          <input id="url" name="url" type="text" value="{{ form.url }}" maxlength="2048" placeholder="Latest Knigovishte article">
        </div>
        
        <div class="filters">
          <div class="form-group">
            <label for="min_length">Minimum length (sentences)</label>
            <input id="min_length" name="min_length" type="number" min="1" value="{{ form.min_length }}" placeholder="Any">
          </div>
          <div class="form-group">
            <label for="max_length">Maximum length (sentences)</label>
            <input id="max_length" name="max_length" type="number" min="1" value="{{ form.max_length }}" placeholder="Any">
          </div>
        </div>

        <div class="form-group">
          <label for="category">Category</label>
          <select id="category" name="category">
            <option value="">Any category</option>
            {% for slug, label in categories %}
              <option value="{{ slug }}" {% if form.category == slug %}selected{% endif %}>{{ label }}</option>
            {% endfor %}
          </select>
        </div>

        <div class="form-group">
          <label for="bg_speed">Bulgarian Voice Speed</label>
          <select id="bg_speed" name="bg_speed">
            <option value="0.8" {% if form.bg_speed == "0.8" %}selected{% endif %}>0.8x (Slower, recommended for learning)</option>
            <option value="0.9" {% if form.bg_speed == "0.9" %}selected{% endif %}>0.9x</option>
            <option value="1.0" {% if not form.bg_speed or form.bg_speed == "1.0" %}selected{% endif %}>1.0x (Normal)</option>
            <option value="1.1" {% if form.bg_speed == "1.1" %}selected{% endif %}>1.1x</option>
            <option value="1.2" {% if form.bg_speed == "1.2" %}selected{% endif %}>1.2x</option>
          </select>
        </div>

        <div class="form-group checkbox-group">
          <input id="refresh" name="refresh" type="checkbox" {% if form.refresh %}checked{% endif %}>
          <label for="refresh" class="checkbox-label">Ignore cached HTML and fetch the article again</label>
        </div>

        <button id="submit-button" type="submit">Generate Podcast Episode</button>
      </form>

      <div id="working-message" class="status" hidden>
        <div class="spinner"></div>
        <span>Working...</span>
      </div>

      {% if result %}
        <section class="panel success">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M10 0C4.48 0 0 4.48 0 10C0 15.52 4.48 20 10 20C15.52 20 20 15.52 20 10C20 4.48 15.52 0 10 0ZM8 15L3 10L4.41 8.59L8 12.17L15.59 4.58L17 6L8 15Z" fill="currentColor"/>
          </svg>
          <p><strong>Your episode is ready.</strong> The podcast RSS feed was updated and pushed successfully.</p>
        </section>
      {% endif %}

      {% if error %}
        <section class="panel error">
          <h2>Pipeline failed</h2>
          <p>{{ error }}</p>
        </section>
      {% endif %}
    </div>

    <script>
      const form = document.getElementById("podcast-form");
      const workingMessage = document.getElementById("working-message");
      const submitButton = document.getElementById("submit-button");

      if (form && workingMessage && submitButton) {
        form.addEventListener("submit", () => {
          workingMessage.hidden = false;
          submitButton.disabled = true;
          submitButton.textContent = "Working...";
        });
      }
    </script>
  </body>
</html>
""".strip()


def create_app(paths: ProjectPaths | None = None) -> Flask:
    app = Flask(__name__)
    project_paths = paths or ProjectPaths.from_root()
    project_paths.ensure()
    app.config["PROJECT_PATHS"] = project_paths
    app.config["MAX_CONTENT_LENGTH"] = MAX_FORM_BODY_BYTES

    # Load env file to ensure WEB_USERNAME and WEB_PASSWORD are loaded
    env_file = project_paths.root / ".env"
    if env_file.is_file():
        load_dotenv(env_file, override=True)

    def check_auth(username, password):
        expected_username = os.environ.get("WEB_USERNAME")
        expected_password = os.environ.get("WEB_PASSWORD")
        return username == expected_username and password == expected_password

    def authenticate():
        return Response(
            "Could not verify your access level for this URL.\n"
            "You have to login with proper credentials", 401,
            {"WWW-Authenticate": 'Basic realm="Login Required"'}
        )

    def requires_auth(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            auth = request.authorization
            expected_username = os.environ.get("WEB_USERNAME")
            expected_password = os.environ.get("WEB_PASSWORD")
            if expected_username and expected_password:
                if not auth or not check_auth(auth.username, auth.password):
                    return authenticate()
            return f(*args, **kwargs)
        return decorated

    def _rebuild_rss_and_push(project_paths: ProjectPaths) -> None:
        import subprocess
        from .services.rss import LocalRSSService
        # 1. Rebuild RSS feed
        rss_service = LocalRSSService(project_paths)
        public_base_url = rss_service.build_public_base_url(
            bind_host="0.0.0.0",
            port=8000,
        )
        rss_service.rebuild_feed(public_base_url)

        # 2. Git add, commit, and push
        root_str = str(project_paths.root)
        try:
            subprocess.run(["git", "add", "data/rss/"], check=True, cwd=root_str)
            subprocess.run(["git", "commit", "-m", "Add new podcast episode"], check=False, cwd=root_str)
            subprocess.run(["git", "push"], check=True, cwd=root_str)
        except Exception as git_exc:
            app.logger.warning(f"Git operations failed: {git_exc}")

    @app.after_request
    def add_security_headers(response: Response) -> Response:
        for header_name, header_value in SECURITY_HEADERS.items():
            response.headers[header_name] = header_value
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_too_large(_exc: RequestEntityTooLarge) -> ResponseReturnValue:
        return _render_page(
            project_paths,
            form={
                "url": "",
                "min_length": "",
                "max_length": "",
                "category": "",
                "refresh": False,
                "bg_speed": "1.0",
            },
            error="Request body is too large for this recruiter-facing showcase page.",
            status_code=413,
        )

    @app.route("/", methods=["GET", "POST"])
    @requires_auth
    def index() -> ResponseReturnValue:
        url_value = request.form.get("url", "")
        min_length_value = request.form.get("min_length", "")
        max_length_value = request.form.get("max_length", "")
        category_value = request.form.get("category", "")
        refresh_requested = request.form.get("refresh") == "on"
        bg_speed_value = request.form.get("bg_speed", "1.0")
        result: dict[str, object] | None = None
        error: str | None = None

        if request.method == "POST":
            try:
                url_value = _clean_form_value(
                    url_value,
                    field_name="Article URL",
                    max_length=MAX_URL_LENGTH,
                )
                min_length_value = _clean_form_value(
                    min_length_value,
                    field_name="Minimum length",
                    max_length=MAX_FILTER_VALUE_LENGTH,
                )
                max_length_value = _clean_form_value(
                    max_length_value,
                    field_name="Maximum length",
                    max_length=MAX_FILTER_VALUE_LENGTH,
                )
                category_value = _clean_form_value(
                    category_value,
                    field_name="Category",
                    max_length=MAX_FILTER_VALUE_LENGTH,
                )
                article_url = _resolve_article_url(
                    url_value,
                    min_length=min_length_value,
                    max_length=max_length_value,
                    category=category_value,
                )
                bg_speed_value = _clean_form_value(
                    bg_speed_value,
                    field_name="Bulgarian voice speed",
                    max_length=MAX_FILTER_VALUE_LENGTH,
                )
                try:
                    bg_speed_float = float(bg_speed_value)
                except ValueError:
                    bg_speed_float = 1.0

                pipeline(
                    paths=project_paths,
                    use_cached_html=not refresh_requested,
                    audio_generator=build_default_audio_generator(
                        bg_speaking_rate=bg_speed_float
                    ),
                ).run(article_url)
                _rebuild_rss_and_push(project_paths)
                result = {"ready": True}
            except DuplicateArticleError:
                _rebuild_rss_and_push(project_paths)
                result = {"ready": True}
            except Exception as exc:
                if not isinstance(exc, (LangblyTimeoutError, ValueError)):
                    app.logger.exception("Unexpected recruiter showcase failure")
                error = _format_error(exc)
        else:
            url_value = url_value.strip()
            min_length_value = min_length_value.strip()
            max_length_value = max_length_value.strip()
            category_value = category_value.strip()
            bg_speed_value = bg_speed_value.strip()

        return _render_page(
            project_paths,
            form={
                "url": url_value,
                "min_length": min_length_value,
                "max_length": max_length_value,
                "category": category_value,
                "refresh": refresh_requested,
                "bg_speed": bg_speed_value,
            },
            result=result,
            error=error,
        )

    return app


def _render_page(
    project_paths: ProjectPaths,
    *,
    form: dict[str, object],
    result: dict[str, object] | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> tuple[str, int]:
    return (
        render_template_string(
            PAGE_TEMPLATE,
            form=form,
            result=result,
            error=error,
            categories=WEB_CATEGORIES,
        ),
        status_code,
    )


def _resolve_article_url(
    raw_url: str,
    *,
    min_length: str = "",
    max_length: str = "",
    category: str = "",
) -> str:
    if raw_url:
        return _normalize_showcase_url(raw_url)

    article_filter = _build_article_filter(
        min_length=min_length,
        max_length=max_length,
        category=category,
    )
    selector = ArticleSelector()
    if article_filter is None:
        article = selector.select_article()
    else:
        article = selector.select_article(article_filter=article_filter)
    return article.source_url


def _build_article_filter(
    *,
    min_length: str,
    max_length: str,
    category: str,
) -> ArticleFilter | None:
    normalized_category = category.strip() or None
    normalized_min = _parse_length("Minimum length", min_length)
    normalized_max = _parse_length("Maximum length", max_length)

    if (
        normalized_min is not None
        and normalized_max is not None
        and normalized_min > normalized_max
    ):
        raise ValueError("Minimum length cannot be greater than maximum length.")

    if normalized_category is not None and normalized_category not in WEB_CATEGORY_SLUGS:
        raise ValueError(f"Unsupported category: {category}")

    if normalized_min is None and normalized_max is None and normalized_category is None:
        return None

    return ArticleFilter(
        min_length=normalized_min,
        max_length=normalized_max,
        category=normalized_category,
    )


def _clean_form_value(raw_value: str, *, field_name: str, max_length: int) -> str:
    normalized_value = raw_value.strip()
    if len(normalized_value) > max_length:
        raise ValueError(f"{field_name} is too long.")
    if any(ord(character) < 32 for character in normalized_value):
        raise ValueError(f"{field_name} contains unsupported control characters.")
    return normalized_value


def _normalize_showcase_url(raw_url: str) -> str:
    normalized_url = _normalize_knigovishte_url(raw_url)
    if normalized_url.startswith("http://"):
        normalized_url = f"https://{normalized_url.removeprefix('http://')}"
    return normalized_url


def _parse_length(label: str, raw_value: str) -> int | None:
    if not raw_value:
        return None

    try:
        parsed = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a whole number.") from exc

    if parsed < 1:
        raise ValueError(f"{label} must be at least 1.")

    return parsed

def _format_error(exc: Exception) -> str:
    if isinstance(exc, LangblyTimeoutError):
        return f"{exc} The episode was not generated; please try again in a few minutes."
    if isinstance(exc, ValueError):
        return str(exc)
    return UNEXPECTED_ERROR_MESSAGE
