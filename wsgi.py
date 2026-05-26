import os
import time


def _log(msg):
    print(f"[wsgi] {msg}", flush=True)


_t0 = time.perf_counter()
_log("importing Flask ...")
from flask import Flask

_log(f"importing blueprints ... ({time.perf_counter() - _t0:.2f}s)")
from report.report_extension import report_bp
from server.server import bp

_log(f"creating app ... ({time.perf_counter() - _t0:.2f}s)")
app = Flask(__name__)
app.register_blueprint(bp)
app.register_blueprint(report_bp)

_log(f"registering Dash ... ({time.perf_counter() - _t0:.2f}s)")
try:
    from server.dash_dashboard import register_dash

    register_dash(app)
except RuntimeError as exc:
    app.config["DASH_REGISTER_ERROR"] = str(exc)
    _log(f"Dash registration skipped: {exc}")

_log(f"app ready in {time.perf_counter() - _t0:.2f}s")

if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    _log(f"starting server on http://{host}:{port} (debug={debug})")
    app.run(host=host, port=port, debug=debug, use_reloader=False, threaded=True)
