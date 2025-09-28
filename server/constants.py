#!/usr/bin/env python3

# 全局常量定义
DB_FILE = "wireguard.db"
WG_INTERFACE = "wg0"
MAX_HANDSHAKE_AGE = 180  # 秒

# 用户会话字典 (在运行时初始化)
# pubkey -> {event_id, start_rx, start_tx, last_handshake, user_id, nickname}
user_sessions = {}