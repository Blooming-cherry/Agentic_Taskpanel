from __future__ import annotations
import os
import uvicorn
from dotenv import load_dotenv  # 可选,无则忽略
from taskpanel.core.config import load_config
from taskpanel.web.server import create_app

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    cfg = load_config()
    app = create_app(cfg)
    print(f"TaskPanel → http://{cfg.bind_host}:{cfg.bind_port}")
    uvicorn.run(app, host=cfg.bind_host, port=cfg.bind_port)
