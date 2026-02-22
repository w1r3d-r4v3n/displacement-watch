from __future__ import annotations
import shutil, sys
src = sys.argv[1] if len(sys.argv) > 1 else "data/latest/query_pack.proposed.json"
dst = "config/query_pack.json"
shutil.copyfile(src, dst)
print(f"Promoted {src} -> {dst}")
