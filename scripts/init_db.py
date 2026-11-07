"""初始化 SQLite 表结构（会话/消息/月报）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store import init_db  # noqa: E402

if __name__ == "__main__":
    init_db()
    print("SQLite 表初始化完成：data/agent.db")
