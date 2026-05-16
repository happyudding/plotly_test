from flask import Flask

from server import bp


def create_app() -> Flask:
    flask_app = Flask(__name__)
    flask_app.register_blueprint(bp)
    return flask_app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False)
