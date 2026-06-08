from __future__ import annotations

from flask import Flask, Response, render_template_string, request
from flask.typing import ResponseReturnValue
from werkzeug.exceptions import RequestEntityTooLarge

from .config import ProjectPaths
from .pipeline import pipeline
from .services.article_selector import ArticleFilter, ArticleSelector
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
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
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
    <title>Knigovishte Podcast Builder</title>
    <style>
      body { font-family: Arial, sans-serif; margin: 2rem auto; max-width: 52rem; line-height: 1.5; }
      form { display: grid; gap: 0.75rem; padding: 1rem; border: 1px solid #d0d7de; border-radius: 0.5rem; background: #f6f8fa; }
      label { font-weight: 600; }
      input[type="text"], input[type="number"], select { width: 100%; padding: 0.6rem; }
      button { width: fit-content; padding: 0.65rem 1rem; }
      .panel { margin-top: 1rem; padding: 1rem; border-radius: 0.5rem; }
      .success { background: #e6ffed; border: 1px solid #b7ebc6; }
      .error { background: #ffebe9; border: 1px solid #ffb3ad; }
      .filters { display: grid; gap: 0.75rem; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); }
      .status { margin-top: 1rem; font-weight: 600; }
      .status[hidden] { display: none; }
    </style>
  </head>
  <body>
    <h1>Knigovishte Podcast Builder</h1>
    <p>Run the existing article → translation → script → audio pipeline locally from your browser.</p>
    <form id="podcast-form" method="post">
      <div>
        <label for="url">Article URL (optional)</label>
        <input id="url" name="url" type="text" value="{{ form.url }}" maxlength="2048" placeholder="Leave blank to use the latest Knigovishte article">
      </div>
      <div class="filters">
        <div>
          <label for="min_length">Minimum length (sentences)</label>
          <input id="min_length" name="min_length" type="number" min="1" value="{{ form.min_length }}" placeholder="Any length">
        </div>
        <div>
          <label for="max_length">Maximum length (sentences)</label>
          <input id="max_length" name="max_length" type="number" min="1" value="{{ form.max_length }}" placeholder="Any length">
        </div>
      </div>
      <div>
        <label for="category">Category</label>
        <select id="category" name="category">
          <option value="">Any category</option>
          {% for slug, label in categories %}
            <option value="{{ slug }}" {% if form.category == slug %}selected{% endif %}>{{ label }}</option>
          {% endfor %}
        </select>
      </div>
      <label>
        <input name="refresh" type="checkbox" {% if form.refresh %}checked{% endif %}>
        Ignore cached HTML and fetch the article again
      </label>
      <button id="submit-button" type="submit">Generate podcast artifacts</button>
    </form>
    <p id="working-message" class="status" hidden>Working...</p>

    {% if result %}
      <section class="panel success">
        <p><strong>Your episode is ready.</strong></p>
      </section>
    {% endif %}

    {% if error %}
      <section class="panel error">
        <h2>Pipeline failed</h2>
        <p>{{ error }}</p>
      </section>
    {% endif %}
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
            },
            error="Request body is too large for this recruiter-facing showcase page.",
            status_code=413,
        )

    @app.route("/", methods=["GET", "POST"])
    def index() -> ResponseReturnValue:
        url_value = request.form.get("url", "")
        min_length_value = request.form.get("min_length", "")
        max_length_value = request.form.get("max_length", "")
        category_value = request.form.get("category", "")
        refresh_requested = request.form.get("refresh") == "on"
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
                pipeline(
                    paths=project_paths,
                    use_cached_html=not refresh_requested,
                ).run(article_url)
                result = {"ready": True}
            except DuplicateArticleError:
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

        return _render_page(
            project_paths,
            form={
                "url": url_value,
                "min_length": min_length_value,
                "max_length": max_length_value,
                "category": category_value,
                "refresh": refresh_requested,
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
