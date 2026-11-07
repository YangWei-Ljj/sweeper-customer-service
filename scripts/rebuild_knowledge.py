"""知识库全量重建脚本。

用法：
    python scripts/rebuild_knowledge.py            # 增量加载 data/ 下新文件
    python scripts/rebuild_knowledge.py --full      # 清空集合与 md5 记录后全量重建
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag.vector_store import VectorStoreService  # noqa: E402
from utils.config_handler import chroma_conf  # noqa: E402
from utils.path_tool import get_abs_path  # noqa: E402


def full_rebuild() -> None:
    import chromadb

    persist_dir = get_abs_path(chroma_conf["persist_directory"])
    client = chromadb.PersistentClient(path=persist_dir)
    try:
        client.delete_collection(chroma_conf["collection_name"])
        print(f"已删除集合 {chroma_conf['collection_name']}")
    except Exception as e:  # noqa: BLE001
        print(f"集合不存在，跳过删除：{e}")
    md5_path = get_abs_path(chroma_conf["md5_hex_store"])
    if Path(md5_path).exists():
        Path(md5_path).write_text("", encoding="utf-8")
        print("已清空 md5.text")


def main() -> None:
    parser = argparse.ArgumentParser(description="知识库重建")
    parser.add_argument("--full", action="store_true", help="清空后全量重建")
    args = parser.parse_args()

    if args.full:
        full_rebuild()

    service = VectorStoreService()
    result = service.load_document()
    print(f"加载完成：{len(result)} 个文件，{sum(result.values())} 个块")
    for name, n in result.items():
        print(f"  - {name}: {n} 块")


if __name__ == "__main__":
    main()
