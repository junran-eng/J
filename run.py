# ============================================================
# run.py — 兼容入口，重定向到 main.py
# ============================================================
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    from main import main
    main()
