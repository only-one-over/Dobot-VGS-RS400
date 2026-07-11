#!/usr/bin/env python3
"""Dobot 运动控制 GUI 启动入口。

用法:
    python run.py                  # 启动 GUI
    python run.py --check-config   # 部署预检（验证配置完整性）
    # 等同于: python -m dobot_move
"""
import sys


def main():
    # 部署预检：python run.py --check-config
    if "--check-config" in sys.argv:
        from dobot_move.config.config_manager import check_config
        ok = check_config(verbose=True)
        sys.exit(0 if ok else 1)
    from dobot_move.ui.gui_app import main as gui_main
    gui_main()


if __name__ == "__main__":
    main()
