import os

import uvicorn

if __name__ == "__main__":
    reload = os.getenv("UVICORN_RELOAD", "false").lower() == "true"
    print("Server running at http://localhost:8000")
    uvicorn.run("app.main:app", host="localhost", port=8000, reload=reload)
