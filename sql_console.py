# sql_console.py – entrypoint for the Flask app
import os
from app import create_app

app = create_app()  # important: create at module level for gunicorn

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5001")),
        debug=False,
    )
