import os

import uvicorn

if __name__ == "__main__":
    reload = os.getenv("UVICORN_RELOAD", "false").lower() == "true"
    print("Server running at http://localhost:8500")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8500, reload=reload)
