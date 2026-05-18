from flask import Flask

from server import bp

app = Flask(__name__)
app.register_blueprint(bp)

try:
    from dash_dashboard import register_dash

    register_dash(app)
except RuntimeError as exc:
    app.config["DASH_REGISTER_ERROR"] = str(exc)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False)
