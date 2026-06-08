from flask import Flask, send_from_directory, request, abort
from pathlib import Path

app = Flask(__name__)
DATA_ROOT = Path(__file__).resolve().parents[2] / "data" / "rss"

@app.route("/podcast.xml")
def feed():
    return send_from_directory(DATA_ROOT, "podcast.xml")

@app.route("/pic.png")
def pic():
    return send_from_directory(DATA_ROOT, "pic.png")

@app.route("/episodes/<path:filename>")
def episodes(filename):
    file_path = DATA_ROOT / "episodes" / filename
    if not file_path.exists():
        abort(404)
    # send_from_directory uses Werkzeug's conditional support and should honor Range
    return send_from_directory(DATA_ROOT / "episodes", filename, conditional=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001)
