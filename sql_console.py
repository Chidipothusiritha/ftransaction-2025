# sql_console.py – entrypoint for the Flask app

import os
from app import create_app

if __name__ == "__main__":
    app = create_app()
    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5001")),
        debug=True,
    )
