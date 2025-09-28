#!/usr/bin/env python3
import sqlite3
from utils.helpers import debug, get_current_timestamp
from constants import DB_FILE

# ---------------- 数据库操作 ----------------
def init_db(db_file=None):
    """初始化数据库，接受可选的数据库文件路径参数"""
    # 使用传入的数据库文件路径，如果没有则使用默认值
    db_path = db_file if db_file else DB_FILE
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # 用户表 - 完善字段和约束
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        peer_pubkey TEXT UNIQUE NOT NULL,
        client_ip TEXT UNIQUE,              -- 客户端分配的内网IP
        nickname TEXT,
        mail TEXT,
        phone TEXT,
        login_ip TEXT,
        bandwidth_limit INTEGER DEFAULT 0,  -- KB/s，0表示无限制
        data_limit INTEGER DEFAULT 0,       -- MB，0表示无限制
        expiry_date TEXT,                   -- 到期时间 YYYY-MM-DD HH:MM:SS
        status INTEGER DEFAULT 0,           -- 0=离线 1=在线
        enabled INTEGER DEFAULT 1,          -- 0=禁用 1=启用
        total_rx INTEGER DEFAULT 0,         -- 总接收流量(字节)
        total_tx INTEGER DEFAULT 0,         -- 总发送流量(字节)
        last_login TEXT,                    -- 最后登录时间
        note TEXT,                          -- 备注
        wg_config TEXT,                     -- 生成的WireGuard配置
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        CHECK(bandwidth_limit >= 0),
        CHECK(data_limit >= 0),
        CHECK(status IN (0, 1)),
        CHECK(enabled IN (0, 1))
    )""")
    
    # 事件表 - 优化索引和字段
    c.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT,
        last_update TEXT NOT NULL,
        session_rx INTEGER DEFAULT 0,  -- 本次会话接收字节数
        session_tx INTEGER DEFAULT 0,  -- 本次会话发送字节数
        login_ip TEXT,                 -- 登录IP
        endpoint_info TEXT,            -- 端点信息
        status TEXT DEFAULT 'ONLINE',
        duration_seconds INTEGER DEFAULT 0,  -- 会话持续时间(秒)
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        CHECK(status IN ('ONLINE', 'OFFLINE'))
    )""")
    
    # 流量统计表 - 每日统计
    c.execute("""
    CREATE TABLE IF NOT EXISTS traffic_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        date TEXT NOT NULL,            -- YYYY-MM-DD格式
        daily_rx INTEGER DEFAULT 0,    -- 当日接收流量
        daily_tx INTEGER DEFAULT 0,    -- 当日发送流量
        session_count INTEGER DEFAULT 0, -- 当日会话数
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, date)
    )""")
    
    # 系统统计表 - 系统级别统计
    c.execute("""
    CREATE TABLE IF NOT EXISTS system_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT UNIQUE NOT NULL,     -- YYYY-MM-DD格式
        total_users INTEGER DEFAULT 0,
        active_users INTEGER DEFAULT 0,
        total_rx INTEGER DEFAULT 0,
        total_tx INTEGER DEFAULT 0,
        peak_concurrent INTEGER DEFAULT 0,
        avg_session_duration INTEGER DEFAULT 0, -- 平均会话时长(秒)
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    
    # 创建优化索引
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_events_user_id ON events(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_events_start_time ON events(start_time DESC)",
        "CREATE INDEX IF NOT EXISTS idx_events_status ON events(status)",
        "CREATE INDEX IF NOT EXISTS idx_users_pubkey ON users(peer_pubkey)",
        "CREATE INDEX IF NOT EXISTS idx_users_status ON users(status, enabled)",
        "CREATE INDEX IF NOT EXISTS idx_traffic_stats_date ON traffic_stats(date DESC)",
        "CREATE INDEX IF NOT EXISTS idx_traffic_stats_user_date ON traffic_stats(user_id, date)",
        "CREATE INDEX IF NOT EXISTS idx_system_stats_date ON system_stats(date DESC)"
    ]
    
    for index_sql in indexes:
        c.execute(index_sql)
    
    conn.commit()
    conn.close()

def execute_db(query, args=(), fetch=False, one=False):
    """统一的数据库执行函数"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    try:
        cur.execute(query, args)
        if fetch:
            rv = cur.fetchall()
            rv_dict = [dict(row) for row in rv]
            result = (rv_dict[0] if rv_dict else None) if one else rv_dict
        else:
            result = cur.lastrowid
        conn.commit()
        return result
    except Exception as e:
        debug(f"Database error: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

def update_user_status(user_id, status):
    """更新用户在线状态"""
    execute_db(
        "UPDATE users SET status = ?, updated_at = ? WHERE id = ?", 
        (status, get_current_timestamp(), user_id)
    )