#!/usr/bin/env python3
import argparse
import threading
import time
import signal
import sys
from datetime import datetime

from db.database import init_db
from session_monitor.session_handler import monitor_wireguard, monitor_loop
from api.api_server import run_api_server
from constants import DB_FILE, MAX_HANDSHAKE_AGE
from utils.helpers import debug

# 全局变量用于控制程序退出
running = True


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='WireGuard Server Manager')
    parser.add_argument('--port', type=int, default=8000, help='API server port')
    parser.add_argument('--interval', type=int, default=10, help='Monitoring interval in seconds')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    parser.add_argument('--max-handshake-age', type=int, default=MAX_HANDSHAKE_AGE, 
                        help='Maximum allowed handshake age in seconds')
    return parser.parse_args()


def signal_handler(sig, frame):
    """处理中断信号"""
    global running
    debug(f"Received signal {sig}, shutting down...")
    running = False


def main():
    """主函数"""
    global running
    
    # 解析命令行参数
    args = parse_args()
    
    # 设置调试模式
    if not args.debug:
        # 如果未启用调试模式，重定向debug函数使其不输出
        def silent_debug(*args, **kwargs):
            pass
        import utils.helpers
        utils.helpers.debug = silent_debug
    
    # 初始化数据库
    debug("Initializing database...")
    try:
        init_db(DB_FILE)
        debug(f"Database initialized successfully: {DB_FILE}")
    except Exception as e:
        debug(f"Failed to initialize database: {e}")
        sys.exit(1)
    
    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 启动监控线程
    debug(f"Starting WireGuard monitoring thread with interval {args.interval}s")
    monitor_thread = threading.Thread(
        target=monitor_loop,
        args=(args.interval, args.max_handshake_age),
        daemon=True
    )
    monitor_thread.start()
    
    # 启动API服务器
    debug(f"Starting API server on port {args.port}")
    api_thread = threading.Thread(
        target=run_api_server,
        args=(args.port,),
        daemon=True
    )
    api_thread.start()
    
    # 主循环
    try:
        while running:
            time.sleep(1)
    except KeyboardInterrupt:
        debug("Keyboard interrupt detected")
    finally:
        debug("Shutting down...")
        running = False
        
        # 等待线程结束
        if monitor_thread.is_alive():
            monitor_thread.join(timeout=2.0)
        if api_thread.is_alive():
            api_thread.join(timeout=2.0)
        
        debug("Server shutdown complete")


if __name__ == "__main__":
    main()