#!/usr/bin/env python3
import sqlite3, subprocess, time, json
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading
import re

DB_FILE = "wireguard.db"
WG_INTERFACE = "wg0"
user_sessions = {}  # pubkey -> {event_id, start_rx, start_tx, last_handshake, user_id, nickname}
MAX_HANDSHAKE_AGE = 180  # 秒

# ---------------- 工具函数 ----------------
def readable_bytes(n):
    if n is None or n < 0:
        return "0B"
    step = 1024
    for unit in ['B', 'K', 'M', 'G', 'T']:
        if n < step: 
            return f"{n:.1f}{unit}"
        n /= step
    return f"{n:.1f}P"

def debug(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[DEBUG] {ts} {msg}")

def get_current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def validate_pubkey(pubkey):
    """验证WireGuard公钥格式"""
    if not pubkey or len(pubkey) != 44:
        return False
    try:
        import base64
        base64.b64decode(pubkey + '==')
        return True
    except:
        return False

def validate_email(email):
    """验证邮箱格式"""
    if not email:
        return True  # 可选字段
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

# ---------------- 数据库操作 ----------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
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

# ---------------- 用户管理 ----------------
def get_or_create_user(pubkey):
    """获取或创建用户，返回用户信息"""
    if not validate_pubkey(pubkey):
        raise ValueError("Invalid public key format")
    
    user = execute_db(
        "SELECT id, nickname, enabled, expiry_date FROM users WHERE peer_pubkey = ?", 
        (pubkey,), fetch=True, one=True
    )
    
    if user:
        # 检查是否过期
        if user["expiry_date"]:
            try:
                expiry = datetime.strptime(user["expiry_date"], "%Y-%m-%d %H:%M:%S")
                if datetime.now() > expiry:
                    debug(f"User {user['id']} expired, disabling")
                    execute_db(
                        "UPDATE users SET enabled = 0, updated_at = ? WHERE id = ?",
                        (get_current_timestamp(), user["id"])
                    )
                    return user["id"], user["nickname"] or f"User_{user['id']}", 0
            except ValueError:
                pass
        
        return user["id"], user["nickname"] or f"User_{user['id']}", user["enabled"]
    
    # 创建新用户
    user_id = execute_db(
        "INSERT INTO users(peer_pubkey, nickname, created_at, updated_at) VALUES(?, ?, ?, ?)", 
        (pubkey, None, get_current_timestamp(), get_current_timestamp())
    )
    
    return user_id, f"User_{user_id}", 1

def update_user_status(user_id, status):
    """更新用户在线状态"""
    execute_db(
        "UPDATE users SET status = ?, updated_at = ? WHERE id = ?", 
        (status, get_current_timestamp(), user_id)
    )

def create_user(pubkey, nickname=None, mail=None, phone=None, bandwidth_limit=0, 
                data_limit=0, expiry_date=None, note=None):
    """创建新用户 - 管理接口，包含WireGuard操作"""
    if not validate_pubkey(pubkey):
        raise ValueError("Invalid public key format")
    
    if mail and not validate_email(mail):
        raise ValueError("Invalid email format")
    
    # 检查公钥是否已存在
    existing = execute_db(
        "SELECT id FROM users WHERE peer_pubkey = ?", 
        (pubkey,), fetch=True, one=True
    )
    if existing:
        raise ValueError("Public key already exists")
    
    # 分配客户端IP
    try:
        client_ip = get_next_available_ip()
    except ValueError as e:
        raise ValueError(str(e))
    
    # 添加到WireGuard
    if not add_wg_peer(pubkey, client_ip):
        raise RuntimeError("Failed to add peer to WireGuard interface")
    
    try:
        # 生成客户端配置
        wg_config = generate_wg_config(None, pubkey, client_ip)
        
        # 创建数据库记录
        user_id = execute_db("""
            INSERT INTO users (peer_pubkey, client_ip, nickname, mail, phone, bandwidth_limit, 
                              data_limit, expiry_date, note, wg_config, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pubkey, client_ip, nickname, mail, phone, bandwidth_limit, data_limit, 
              expiry_date, note, wg_config, get_current_timestamp(), get_current_timestamp()))
        
        debug(f"Created user {user_id} with pubkey {pubkey[:16]}... and IP {client_ip}")
        return user_id, client_ip, wg_config
        
    except Exception as e:
        # 回滚WireGuard操作
        remove_wg_peer(pubkey)
        raise RuntimeError(f"Failed to create user in database: {e}")

def delete_user(user_id):
    """删除用户（真正删除，包含WireGuard操作）"""
    # 获取用户信息
    user = execute_db(
        "SELECT peer_pubkey, nickname FROM users WHERE id = ?",
        (user_id,), fetch=True, one=True
    )
    
    if not user:
        raise ValueError("User not found")
    
    pubkey = user["peer_pubkey"]
    nickname = user["nickname"]
    
    # 首先结束所有活跃会话
    active_sessions = execute_db(
        "SELECT id FROM events WHERE user_id = ? AND end_time IS NULL",
        (user_id,), fetch=True
    )
    
    for session in active_sessions:
        close_session(session["id"], 0, 0)
    
    # 从用户会话中移除
    for pubkey_session, session_data in list(user_sessions.items()):
        if session_data["user_id"] == user_id:
            del user_sessions[pubkey_session]
            break
    
    # 从WireGuard中移除
    if not remove_wg_peer(pubkey):
        debug(f"Warning: Failed to remove peer from WireGuard, but continuing with database deletion")
    
    # 从数据库中删除
    execute_db("DELETE FROM users WHERE id = ?", (user_id,))
    
    debug(f"Deleted user {user_id} ({nickname}) with pubkey {pubkey[:16]}...")
    return True

def update_user(user_id, **kwargs):
    """更新用户信息"""
    allowed_fields = ['nickname', 'mail', 'phone', 'bandwidth_limit', 
                     'data_limit', 'expiry_date', 'enabled', 'note']
    
    updates = []
    values = []
    
    for field, value in kwargs.items():
        if field in allowed_fields:
            updates.append(f"{field} = ?")
            values.append(value)
    
    if not updates:
        return
    
    # 验证邮箱
    if 'mail' in kwargs and kwargs['mail'] and not validate_email(kwargs['mail']):
        raise ValueError("Invalid email format")
    
    # 如果禁用用户，从WireGuard中临时移除
    if 'enabled' in kwargs and kwargs['enabled'] == 0:
        user = execute_db("SELECT peer_pubkey FROM users WHERE id = ?", 
                         (user_id,), fetch=True, one=True)
        if user:
            remove_wg_peer(user["peer_pubkey"])
    
    # 如果启用用户，重新添加到WireGuard
    elif 'enabled' in kwargs and kwargs['enabled'] == 1:
        user = execute_db("SELECT peer_pubkey, client_ip FROM users WHERE id = ?", 
                         (user_id,), fetch=True, one=True)
        if user and user["client_ip"]:
            add_wg_peer(user["peer_pubkey"], user["client_ip"])
    
    updates.append("updated_at = ?")
    values.append(get_current_timestamp())
    values.append(user_id)
    
    execute_db(
        f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
        values
    )
    
    debug(f"Updated user {user_id}")
    return True

# ---------------- 统计和管理功能 ----------------
def update_user_traffic_stats(user_id, session_rx, session_tx):
    """更新用户总流量统计"""
    execute_db("""
        UPDATE users 
        SET total_rx = total_rx + ?, total_tx = total_tx + ?, 
            last_login = ?, updated_at = ?
        WHERE id = ?
    """, (session_rx, session_tx, get_current_timestamp(), get_current_timestamp(), user_id))

def update_daily_traffic_stats(user_id, rx, tx, session_count=1):
    """更新用户每日流量统计"""
    today = datetime.now().strftime("%Y-%m-%d")
    
    execute_db("""
        INSERT OR REPLACE INTO traffic_stats 
        (user_id, date, daily_rx, daily_tx, session_count, created_at, updated_at)
        VALUES (?, ?, 
            COALESCE((SELECT daily_rx FROM traffic_stats WHERE user_id = ? AND date = ?), 0) + ?,
            COALESCE((SELECT daily_tx FROM traffic_stats WHERE user_id = ? AND date = ?), 0) + ?,
            COALESCE((SELECT session_count FROM traffic_stats WHERE user_id = ? AND date = ?), 0) + ?,
            COALESCE((SELECT created_at FROM traffic_stats WHERE user_id = ? AND date = ?), ?),
            ?)
    """, (user_id, today, user_id, today, rx, user_id, today, tx, 
          user_id, today, session_count, user_id, today, get_current_timestamp(), get_current_timestamp()))

def update_system_stats():
    """更新系统统计"""
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 获取统计数据
    stats = execute_db("""
        SELECT 
            COUNT(*) as total_users,
            SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) as active_users,
            SUM(total_rx) as total_rx,
            SUM(total_tx) as total_tx
        FROM users
        WHERE enabled = 1
    """, fetch=True, one=True)
    
    # 计算平均会话时长
    avg_duration = execute_db("""
        SELECT AVG(duration_seconds) as avg_duration
        FROM events 
        WHERE DATE(start_time) = ? AND duration_seconds > 0
    """, (today,), fetch=True, one=True)
    
    avg_duration_seconds = int(avg_duration['avg_duration'] or 0)
    current_online = len(user_sessions)
    
    execute_db("""
        INSERT OR REPLACE INTO system_stats 
        (date, total_users, active_users, total_rx, total_tx, peak_concurrent, 
         avg_session_duration, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 
            MAX(COALESCE((SELECT peak_concurrent FROM system_stats WHERE date = ?), 0), ?),
            ?, 
            COALESCE((SELECT created_at FROM system_stats WHERE date = ?), ?),
            ?)
    """, (today, stats['total_users'], stats['active_users'], 
          stats['total_rx'], stats['total_tx'], today, current_online, 
          avg_duration_seconds, today, get_current_timestamp(), get_current_timestamp()))

def get_user_management_info(page=1, per_page=50, search="", status_filter="all"):
    """获取用户管理信息 - 支持分页和搜索"""
    offset = (page - 1) * per_page
    
    # 构建WHERE条件
    where_conditions = []
    params = []
    
    if search:
        where_conditions.append("""
            (u.nickname LIKE ? OR u.mail LIKE ? OR u.peer_pubkey LIKE ?)
        """)
        search_term = f"%{search}%"
        params.extend([search_term, search_term, search_term])
    
    if status_filter == "online":
        where_conditions.append("u.status = 1")
    elif status_filter == "offline":
        where_conditions.append("u.status = 0")
    elif status_filter == "enabled":
        where_conditions.append("u.enabled = 1")
    elif status_filter == "disabled":
        where_conditions.append("u.enabled = 0")
    
    where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
    
    # 获取总数
    count_query = f"""
        SELECT COUNT(*) as total
        FROM users u
        {where_clause}
    """
    total_count = execute_db(count_query, params, fetch=True, one=True)["total"]
    
    # 获取用户列表
    users_query = f"""
        SELECT u.*, 
               CASE WHEN s.event_id IS NOT NULL THEN 1 ELSE 0 END as is_online,
               s.login_ip,
               s.session_start,
               s.session_rx,
               s.session_tx
        FROM users u
        LEFT JOIN (
            SELECT user_id, MAX(start_time) as session_start,
                   login_ip, id as event_id, session_rx, session_tx
            FROM events 
            WHERE end_time IS NULL 
            GROUP BY user_id
        ) s ON u.id = s.user_id
        {where_clause}
        ORDER BY u.status DESC, u.last_login DESC
        LIMIT ? OFFSET ?
    """
    
    params.extend([per_page, offset])
    users = execute_db(users_query, params, fetch=True)
    
    return {
        "users": users,
        "total": total_count,
        "page": page,
        "per_page": per_page,
        "total_pages": (total_count + per_page - 1) // per_page
    }

def get_events_history(page=1, per_page=50, user_id=None, status_filter="all"):
    """获取事件历史 - 支持分页"""
    offset = (page - 1) * per_page
    
    # 构建WHERE条件
    where_conditions = []
    params = []
    
    if user_id:
        where_conditions.append("e.user_id = ?")
        params.append(user_id)
    
    if status_filter == "online":
        where_conditions.append("e.status = 'ONLINE'")
    elif status_filter == "offline":
        where_conditions.append("e.status = 'OFFLINE'")
    
    where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
    
    # 获取总数
    count_query = f"""
        SELECT COUNT(*) as total
        FROM events e
        {where_clause}
    """
    total_count = execute_db(count_query, params, fetch=True, one=True)["total"]
    
    # 获取事件列表
    events_query = f"""
        SELECT e.*, u.nickname, u.peer_pubkey 
        FROM events e 
        LEFT JOIN users u ON e.user_id = u.id 
        {where_clause}
        ORDER BY e.id DESC 
        LIMIT ? OFFSET ?
    """
    
    params.extend([per_page, offset])
    events = execute_db(events_query, params, fetch=True)
    
    return {
        "events": events,
        "total": total_count,
        "page": page,
        "per_page": per_page,
        "total_pages": (total_count + per_page - 1) // per_page
    }

def get_traffic_chart_data(days=7):
    """获取流量图表数据"""
    return execute_db("""
        SELECT date,
               SUM(daily_rx) as total_rx,
               SUM(daily_tx) as total_tx,
               SUM(session_count) as total_sessions
        FROM traffic_stats 
        WHERE date >= date('now', '-{} days')
        GROUP BY date
        ORDER BY date
    """.format(days), fetch=True)

def get_dashboard_stats():
    """获取仪表盘统计数据"""
    # 基础统计
    basic_stats = execute_db("""
        SELECT 
            COUNT(*) as total_users,
            SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END) as online_users,
            SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END) as enabled_users,
            SUM(total_rx) as total_rx,
            SUM(total_tx) as total_tx
        FROM users
    """, fetch=True, one=True)
    
    # 今日统计
    today_stats = execute_db("""
        SELECT 
            SUM(daily_rx) as today_rx,
            SUM(daily_tx) as today_tx,
            SUM(session_count) as today_sessions
        FROM traffic_stats 
        WHERE date = date('now')
    """, fetch=True, one=True)
    
    # 运行时长
    uptime_stats = execute_db("""
        SELECT MIN(start_time) as first_event
        FROM events
    """, fetch=True, one=True)
    
    return {
        'total_users': basic_stats['total_users'] or 0,
        'enabled_users': basic_stats['enabled_users'] or 0,
        'online_users': basic_stats['online_users'] or 0,
        'active_sessions': len(user_sessions),
        'total_rx': basic_stats['total_rx'] or 0,
        'total_tx': basic_stats['total_tx'] or 0,
        'today_rx': today_stats['today_rx'] if today_stats else 0,
        'today_tx': today_stats['today_tx'] if today_stats else 0,
        'today_sessions': today_stats['today_sessions'] if today_stats else 0,
        'uptime_start': uptime_stats['first_event'] if uptime_stats else None
    }

def create_new_session(user_id, start_rx, start_tx, login_ip=None, endpoint_info=None):
    """创建新的用户会话"""
    now = get_current_timestamp()
    event_id = execute_db("""
        INSERT INTO events(user_id, start_time, last_update, session_rx, session_tx, 
                          login_ip, endpoint_info, status)
        VALUES(?, ?, ?, 0, 0, ?, ?, 'ONLINE')
    """, (user_id, now, now, login_ip, endpoint_info))
    
    return event_id

def update_session_traffic(event_id, session_rx, session_tx):
    """更新会话流量数据"""
    execute_db("""
        UPDATE events 
        SET last_update = ?, session_rx = ?, session_tx = ? 
        WHERE id = ?
    """, (get_current_timestamp(), session_rx, session_tx, event_id))

def close_session(event_id, final_rx, final_tx):
    """关闭用户会话"""
    # 获取会话信息以更新统计
    session_info = execute_db("""
        SELECT user_id, session_rx, session_tx, start_time
        FROM events WHERE id = ?
    """, (event_id,), fetch=True, one=True)
    
    if session_info:
        # 计算会话持续时间
        try:
            start_time = datetime.strptime(session_info['start_time'], "%Y-%m-%d %H:%M:%S")
            duration_seconds = int((datetime.now() - start_time).total_seconds())
        except:
            duration_seconds = 0
        
        # 更新用户总流量
        update_user_traffic_stats(session_info['user_id'], 
                                final_rx or session_info['session_rx'], 
                                final_tx or session_info['session_tx'])
        
        # 更新每日统计
        update_daily_traffic_stats(session_info['user_id'],
                                 final_rx or session_info['session_rx'],
                                 final_tx or session_info['session_tx'])
        
        # 关闭会话
        execute_db("""
            UPDATE events 
            SET end_time = ?, session_rx = ?, session_tx = ?, status = 'OFFLINE',
                duration_seconds = ?
            WHERE id = ?
        """, (get_current_timestamp(), final_rx or session_info['session_rx'], 
              final_tx or session_info['session_tx'], duration_seconds, event_id))

# ---------------- WireGuard接口 ----------------
def get_wg_peers(interface=WG_INTERFACE):
    """获取WireGuard对等体信息"""
    try:
        output = subprocess.check_output(
            ["wg", "show", interface, "dump"], 
            text=True, 
            timeout=10
        )
    except subprocess.TimeoutExpired:
        debug("WireGuard command timeout")
        return {}
    except subprocess.CalledProcessError as e:
        debug(f"WireGuard command failed: {e}")
        return {}
    except FileNotFoundError:
        debug("WireGuard command not found")
        return {}
    
    peers = {}
    lines = output.strip().splitlines()
    
    # 跳过第一行（接口信息）
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) < 7:
            continue
            
        pubkey = parts[0]
        endpoint = parts[2] if parts[2] != "(none)" else None
        latest_handshake = int(parts[4]) if parts[4] != '0' else 0
        rx_bytes = int(parts[5])
        tx_bytes = int(parts[6])
        
        peers[pubkey] = {
            "rx": rx_bytes,
            "tx": tx_bytes,
            "handshake": latest_handshake,
            "endpoint": endpoint
        }
    
    return peers

# ---------------- 会话监控逻辑 ----------------
def is_peer_online(handshake_time):
    """判断对等体是否在线"""
    if handshake_time == 0:
        return False
    
    current_time = time.time()
    return (current_time - handshake_time) <= MAX_HANDSHAKE_AGE

def handle_peer_online(pubkey, peer_info):
    """处理对等体上线"""
    try:
        user_id, nickname, enabled = get_or_create_user(pubkey)
    except ValueError as e:
        debug(f"Invalid pubkey {pubkey[:16]}...: {e}")
        return
    
    # 检查用户是否被禁用
    if enabled == 0:
        update_user_status(user_id, 0)
        return
    
    # 检查是否已有活跃会话
    if pubkey in user_sessions:
        session = user_sessions[pubkey]
        # 计算会话流量（处理流量计数器重置的情况）
        current_rx = peer_info["rx"]
        current_tx = peer_info["tx"]
        
        # 检测流量计数器重置（当前值小于起始值）
        if current_rx < session["start_rx"] or current_tx < session["start_tx"]:
            debug(f"Traffic counter reset detected for {nickname}")
            session["start_rx"] = current_rx
            session["start_tx"] = current_tx
            session_rx = 0
            session_tx = 0
        else:
            session_rx = current_rx - session["start_rx"]
            session_tx = current_tx - session["start_tx"]
        
        # 更新会话数据
        update_session_traffic(session["event_id"], session_rx, session_tx)
        session["last_handshake"] = peer_info["handshake"]
        
        debug(f"User {nickname} session update: rx={readable_bytes(session_rx)}, tx={readable_bytes(session_tx)}")
    else:
        # 创建新会话
        endpoint_info = peer_info.get("endpoint")
        event_id = create_new_session(user_id, peer_info["rx"], peer_info["tx"], 
                                    None, endpoint_info)
        user_sessions[pubkey] = {
            "event_id": event_id,
            "start_rx": peer_info["rx"],
            "start_tx": peer_info["tx"],
            "last_handshake": peer_info["handshake"],
            "user_id": user_id,
            "nickname": nickname
        }
        update_user_status(user_id, 1)
        debug(f"User {nickname} started new session {event_id}")

def handle_peer_offline(pubkey, reason="timeout"):
    """处理对等体离线"""
    if pubkey not in user_sessions:
        return
    
    session = user_sessions[pubkey]
    user_id = session["user_id"]
    nickname = session["nickname"]
    
    # 关闭会话
    close_session(session["event_id"], None, None)
    update_user_status(user_id, 0)
    
    debug(f"User {nickname} offline ({reason}), closed session {session['event_id']}")
    
    # 清理会话数据
    del user_sessions[pubkey]

def monitor_wireguard():
    """监控WireGuard连接状态"""
    current_peers = get_wg_peers()
    current_time = time.time()
    active_pubkeys = set()
    
    # 处理当前在线的对等体
    for pubkey, peer_info in current_peers.items():
        active_pubkeys.add(pubkey)
        
        if is_peer_online(peer_info["handshake"]):
            handle_peer_online(pubkey, peer_info)
        else:
            # 握手超时，视为离线
            if pubkey in user_sessions:
                handle_peer_offline(pubkey, "handshake_timeout")
    
    # 处理消失的对等体
    offline_pubkeys = set(user_sessions.keys()) - active_pubkeys
    for pubkey in offline_pubkeys:
        handle_peer_offline(pubkey, "disappeared")
    
    # 更新系统统计（每5分钟更新一次）
    if not hasattr(monitor_wireguard, 'last_stats_update'):
        monitor_wireguard.last_stats_update = 0
    
    if current_time - monitor_wireguard.last_stats_update > 300:  # 5分钟
        try:
            update_system_stats()
            monitor_wireguard.last_stats_update = current_time
        except Exception as e:
            debug(f"Failed to update system stats: {e}")

# ---------------- 监控循环 ----------------
def monitor_loop():
    """主监控循环"""
    init_db()
    debug("WireGuard monitor started")
    
    while True:
        try:
            monitor_wireguard()
        except Exception as e:
            debug(f"Monitor error: {e}")
        
        time.sleep(10)

# ---------------- REST API ----------------
class APIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 禁用默认的请求日志
        pass
    
    def do_OPTIONS(self):
        """处理OPTIONS请求 - CORS预检"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
    
    def do_GET(self):
        parsed = urlparse(self.path)
        query_params = parse_qs(parsed.query)
        
        try:
            if parsed.path == "/api/users":
                self.handle_users_api(query_params)
            elif parsed.path == "/api/users/management":
                self.handle_user_management_api(query_params)
            elif parsed.path == "/api/events":
                self.handle_events_api(query_params)
            elif parsed.path == "/api/events/history":
                self.handle_events_history_api(query_params)
            elif parsed.path == "/api/status":
                self.handle_status_api()
            elif parsed.path == "/api/dashboard":
                self.handle_dashboard_api()
            elif parsed.path == "/api/traffic/chart":
                self.handle_traffic_chart_api(query_params)
            elif parsed.path.startswith("/api/users/"):
                # 处理用户操作 /api/users/{id}/action
                self.handle_user_action_api(parsed.path)
            else:
                self.send_error(404, "API endpoint not found")
        except Exception as e:
            debug(f"API error: {e}")
            self.send_json_response({"error": str(e)}, 500)
    
    def do_POST(self):
        """处理POST请求 - 用于用户管理操作"""
        parsed = urlparse(self.path)
        
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
            else:
                data = {}
            
            if parsed.path == "/api/users":
                self.handle_create_user_api(data)
            elif parsed.path.startswith("/api/users/"):
                parts = parsed.path.strip('/').split('/')
                if len(parts) >= 4:
                    try:
                        user_id = int(parts[2])
                        action = parts[3]
                        if action == "update":
                            self.handle_update_user_api(user_id, data)
                        else:
                            self.send_json_response({"error": f"Unknown action: {action}"}, 400)
                    except ValueError:
                        self.send_json_response({"error": "Invalid user ID"}, 400)
            else:
                self.send_error(404, "API endpoint not found")
                
        except json.JSONDecodeError:
            self.send_json_response({"error": "Invalid JSON data"}, 400)
        except Exception as e:
            debug(f"POST API error: {e}")
            self.send_json_response({"error": str(e)}, 500)
    
    def do_PUT(self):
        """处理PUT请求 - 用于更新用户"""
        parsed = urlparse(self.path)
        
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
            else:
                data = {}
            
            if parsed.path.startswith("/api/users/"):
                parts = parsed.path.strip('/').split('/')
                if len(parts) == 3:
                    try:
                        user_id = int(parts[2])
                        self.handle_update_user_api(user_id, data)
                    except ValueError:
                        self.send_json_response({"error": "Invalid user ID"}, 400)
                else:
                    self.send_json_response({"error": "Invalid request path"}, 400)
            else:
                self.send_error(404, "API endpoint not found")
                
        except json.JSONDecodeError:
            self.send_json_response({"error": "Invalid JSON data"}, 400)
        except Exception as e:
            debug(f"PUT API error: {e}")
            self.send_json_response({"error": str(e)}, 500)
    
    def do_DELETE(self):
        """处理DELETE请求 - 用于删除用户"""
        parsed = urlparse(self.path)
        
        try:
            if parsed.path.startswith("/api/users/"):
                parts = parsed.path.strip('/').split('/')
                if len(parts) == 3:
                    try:
                        user_id = int(parts[2])
                        delete_user(user_id)
                        self.send_json_response({"status": "success", "message": "用户已删除"})
                    except ValueError:
                        self.send_json_response({"error": "Invalid user ID"}, 400)
                else:
                    self.send_json_response({"error": "Invalid request path"}, 400)
            else:
                self.send_error(404, "API endpoint not found")
                
        except Exception as e:
            debug(f"DELETE API error: {e}")
            self.send_json_response({"error": str(e)}, 500)
    
    def send_json_response(self, data, status=200):
        """发送JSON响应"""
        json_data = json.dumps(data, ensure_ascii=False, indent=2)
        
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Length", str(len(json_data.encode('utf-8'))))
        self.end_headers()
        self.wfile.write(json_data.encode('utf-8'))
    
    def get_param(self, query_params, key, default=None, type_func=str):
        """从查询参数中获取值"""
        if key in query_params and query_params[key]:
            try:
                return type_func(query_params[key][0])
            except (ValueError, IndexError):
                pass
        return default
    
    def handle_users_api(self, query_params):
        """获取用户列表 - 基础接口"""
        users = execute_db("SELECT * FROM users ORDER BY id", fetch=True)
        self.send_json_response({"users": users})
    
    def handle_user_management_api(self, query_params):
        """获取用户管理信息 - 支持分页和搜索"""
        page = self.get_param(query_params, 'page', 1, int)
        per_page = self.get_param(query_params, 'per_page', 50, int)
        search = self.get_param(query_params, 'search', '')
        status_filter = self.get_param(query_params, 'status', 'all')
        
        # 限制每页数量
        per_page = min(per_page, 100)
        
        result = get_user_management_info(page, per_page, search, status_filter)
        
        formatted_users = []
        for user in result["users"]:
            formatted_users.append({
                "id": user["id"],
                "peer_pubkey": user["peer_pubkey"],
                "peer_pubkey_short": user["peer_pubkey"][:16] + "..." if user["peer_pubkey"] else "",
                "nickname": user["nickname"] or f"User_{user['id']}",
                "mail": user["mail"] or "",
                "phone": user["phone"] or "",
                "login_ip": user["login_ip"] or "",
                "status": user["status"],
                "enabled": user["enabled"],
                "is_online": user["is_online"],
                "total_rx": user["total_rx"] or 0,
                "total_tx": user["total_tx"] or 0,
                "total_rx_readable": readable_bytes(user["total_rx"] or 0),
                "total_tx_readable": readable_bytes(user["total_tx"] or 0),
                "last_login": user["last_login"],
                "bandwidth_limit": user["bandwidth_limit"] or 0,
                "data_limit": user["data_limit"] or 0,
                "expiry_date": user["expiry_date"],
                "note": user["note"] or "",
                "created_at": user["created_at"],
                "updated_at": user["updated_at"],
                "session_start": user["session_start"],
                "session_rx": user.get("session_rx", 0),
                "session_tx": user.get("session_tx", 0),
                "session_rx_readable": readable_bytes(user.get("session_rx", 0) or 0),
                "session_tx_readable": readable_bytes(user.get("session_tx", 0) or 0),
            })
        
        response_data = {
            "users": formatted_users,
            "pagination": {
                "current_page": result["page"],
                "per_page": result["per_page"],
                "total": result["total"],
                "total_pages": result["total_pages"],
                "has_next": result["page"] < result["total_pages"],
                "has_prev": result["page"] > 1
            },
            "filters": {
                "search": search,
                "status": status_filter
            }
        }
        
        self.send_json_response(response_data)
    
    def handle_events_api(self, query_params):
        """获取事件列表 - 每个用户只显示最新的会话"""
        # 获取每个用户的最新事件ID
        latest_events = execute_db("""
            WITH latest_events AS (
                SELECT user_id, MAX(id) as latest_id
                FROM events 
                GROUP BY user_id
            )
            SELECT e.*, u.nickname, u.peer_pubkey 
            FROM events e 
            LEFT JOIN users u ON e.user_id = u.id 
            INNER JOIN latest_events le ON e.id = le.latest_id
            ORDER BY e.status DESC, e.last_update DESC
            LIMIT 100
        """, fetch=True)
        
        # 格式化输出
        formatted_events = []
        for event in latest_events:
            formatted_events.append({
                "id": event["id"],
                "user_id": event["user_id"],
                "nickname": event["nickname"] or f"User_{event['user_id']}",
                "peer_pubkey": event["peer_pubkey"][:16] + "..." if event["peer_pubkey"] else "Unknown",
                "start_time": event["start_time"],
                "end_time": event["end_time"],
                "last_update": event["last_update"],
                "session_rx": event["session_rx"],
                "session_tx": event["session_tx"],
                "session_rx_readable": readable_bytes(event["session_rx"]),
                "session_tx_readable": readable_bytes(event["session_tx"]),
                "duration_seconds": event.get("duration_seconds", 0),
                "login_ip": event["login_ip"],
                "endpoint_info": event.get("endpoint_info"),
                "status": event["status"]
            })
        
        self.send_json_response({"events": formatted_events})
    
    def handle_events_history_api(self, query_params):
        """获取完整事件历史记录 - 支持分页"""
        page = self.get_param(query_params, 'page', 1, int)
        per_page = self.get_param(query_params, 'per_page', 50, int)
        user_id = self.get_param(query_params, 'user_id', None, int)
        status_filter = self.get_param(query_params, 'status', 'all')
        
        # 限制每页数量
        per_page = min(per_page, 100)
        
        result = get_events_history(page, per_page, user_id, status_filter)
        
        # 格式化输出
        formatted_events = []
        for event in result["events"]:
            duration_readable = ""
            if event.get("duration_seconds"):
                hours = event["duration_seconds"] // 3600
                minutes = (event["duration_seconds"] % 3600) // 60
                seconds = event["duration_seconds"] % 60
                if hours > 0:
                    duration_readable = f"{hours}h {minutes}m {seconds}s"
                elif minutes > 0:
                    duration_readable = f"{minutes}m {seconds}s"
                else:
                    duration_readable = f"{seconds}s"
            
            formatted_events.append({
                "id": event["id"],
                "user_id": event["user_id"],
                "nickname": event["nickname"] or f"User_{event['user_id']}",
                "peer_pubkey": event["peer_pubkey"][:16] + "..." if event["peer_pubkey"] else "Unknown",
                "start_time": event["start_time"],
                "end_time": event["end_time"],
                "last_update": event["last_update"],
                "session_rx": event["session_rx"],
                "session_tx": event["session_tx"],
                "session_rx_readable": readable_bytes(event["session_rx"]),
                "session_tx_readable": readable_bytes(event["session_tx"]),
                "duration_seconds": event.get("duration_seconds", 0),
                "duration_readable": duration_readable,
                "login_ip": event["login_ip"],
                "endpoint_info": event.get("endpoint_info"),
                "status": event["status"]
            })
        
        response_data = {
            "events": formatted_events,
            "pagination": {
                "current_page": result["page"],
                "per_page": result["per_page"],
                "total": result["total"],
                "total_pages": result["total_pages"],
                "has_next": result["page"] < result["total_pages"],
                "has_prev": result["page"] > 1
            },
            "filters": {
                "user_id": user_id,
                "status": status_filter
            }
        }
        
        self.send_json_response(response_data)
    
    def handle_dashboard_api(self):
        """获取仪表盘数据"""
        stats = get_dashboard_stats()
        
        # 计算运行时长
        uptime_hours = 0
        uptime_readable = "0小时"
        if stats['uptime_start']:
            try:
                start_time = datetime.strptime(stats['uptime_start'], "%Y-%m-%d %H:%M:%S")
                uptime_seconds = (datetime.now() - start_time).total_seconds()
                uptime_hours = uptime_seconds / 3600
                
                days = int(uptime_seconds // 86400)
                hours = int((uptime_seconds % 86400) // 3600)
                minutes = int((uptime_seconds % 3600) // 60)
                
                if days > 0:
                    uptime_readable = f"{days}天 {hours}小时 {minutes}分钟"
                elif hours > 0:
                    uptime_readable = f"{hours}小时 {minutes}分钟"
                else:
                    uptime_readable = f"{minutes}分钟"
            except:
                pass
        
        dashboard_data = {
            "summary": {
                "registered_users": stats['total_users'],
                "enabled_users": stats['enabled_users'],
                "online_users": stats['online_users'], 
                "active_sessions": stats['active_sessions'],
                "uptime_hours": round(uptime_hours, 1),
                "uptime_readable": uptime_readable
            },
            "traffic": {
                "total_upload": readable_bytes(stats['total_tx']),
                "total_download": readable_bytes(stats['total_rx']),
                "today_upload": readable_bytes(stats['today_tx'] or 0),
                "today_download": readable_bytes(stats['today_rx'] or 0),
                "today_sessions": stats['today_sessions'] or 0,
                "upload_raw": stats['total_tx'],
                "download_raw": stats['total_rx'],
                "today_upload_raw": stats['today_tx'] or 0,
                "today_download_raw": stats['today_rx'] or 0
            }
        }
        
        self.send_json_response(dashboard_data)
    
    def handle_traffic_chart_api(self, query_params):
        """获取流量图表数据"""
        days = self.get_param(query_params, 'days', 7, int)
        
        # 限制天数范围
        days = min(max(days, 1), 365)
        
        chart_data = get_traffic_chart_data(days)
        
        # 格式化图表数据
        formatted_data = []
        for row in chart_data:
            formatted_data.append({
                "date": row["date"],
                "upload": row["total_tx"] or 0,
                "download": row["total_rx"] or 0,
                "sessions": row.get("total_sessions", 0) or 0,
                "upload_readable": readable_bytes(row["total_tx"] or 0),
                "download_readable": readable_bytes(row["total_rx"] or 0)
            })
        
        response_data = {
            "data": formatted_data,
            "period": {
                "days": days,
                "start_date": formatted_data[0]["date"] if formatted_data else None,
                "end_date": formatted_data[-1]["date"] if formatted_data else None
            }
        }
        
        self.send_json_response(response_data)
    
    def handle_user_action_api(self, path):
        """处理用户操作"""
        # 解析路径 /api/users/{id}/{action}
        parts = path.strip('/').split('/')
        if len(parts) != 4:
            self.send_json_response({"error": "Invalid user action path"}, 400)
            return
        
        try:
            user_id = int(parts[2])
            action = parts[3]
        except ValueError:
            self.send_json_response({"error": "Invalid user ID"}, 400)
            return
        
        try:
            if action == "enable":
                update_user(user_id, enabled=1)
                self.send_json_response({"status": "success", "message": "用户已启用"})
            elif action == "disable":
                update_user(user_id, enabled=0)
                self.send_json_response({"status": "success", "message": "用户已禁用"})
            elif action == "reset":
                # 重置用户流量统计
                execute_db("UPDATE users SET total_rx = 0, total_tx = 0, updated_at = ? WHERE id = ?", 
                          (get_current_timestamp(), user_id))
                self.send_json_response({"status": "success", "message": "用户流量已重置"})
            elif action == "kick":
                # 踢出用户（结束当前会话）
                user_pubkey = None
                for pubkey, session in user_sessions.items():
                    if session["user_id"] == user_id:
                        user_pubkey = pubkey
                        break
                
                if user_pubkey:
                    handle_peer_offline(user_pubkey, "kicked")
                    self.send_json_response({"status": "success", "message": "用户已踢出"})
                else:
                    self.send_json_response({"status": "info", "message": "用户当前不在线"})
            else:
                self.send_json_response({"error": f"Unknown action: {action}"}, 400)
        except Exception as e:
            self.send_json_response({"error": str(e)}, 500)
    
    def handle_create_user_api(self, data):
        """创建新用户"""
        required_fields = ['peer_pubkey']
        if not all(field in data for field in required_fields):
            self.send_json_response({"error": "Missing required fields: peer_pubkey"}, 400)
            return
        
        try:
            user_id, client_ip, wg_config = create_user(
                pubkey=data['peer_pubkey'],
                nickname=data.get('nickname'),
                mail=data.get('mail'),
                phone=data.get('phone'),
                bandwidth_limit=data.get('bandwidth_limit', 0),
                data_limit=data.get('data_limit', 0),
                expiry_date=data.get('expiry_date'),
                note=data.get('note')
            )
            
            self.send_json_response({
                "status": "success", 
                "message": "用户创建成功并已添加到WireGuard", 
                "user_id": user_id,
                "client_ip": client_ip,
                "config_download_url": f"/api/users/{user_id}/config"
            })
        except ValueError as e:
            self.send_json_response({"error": str(e)}, 400)
        except RuntimeError as e:
            self.send_json_response({"error": str(e)}, 500)
        except Exception as e:
            self.send_json_response({"error": f"Failed to create user: {e}"}, 500)
    
    def handle_update_user_api(self, user_id, data):
        """更新用户信息"""
        try:
            update_user(user_id, **data)
            self.send_json_response({"status": "success", "message": "用户信息已更新"})
        except ValueError as e:
            self.send_json_response({"error": str(e)}, 400)
        except Exception as e:
            self.send_json_response({"error": f"Failed to update user: {e}"}, 500)
    
    def handle_user_config_download(self, user_id):
        """下载用户WireGuard配置"""
        try:
            user = execute_db(
                "SELECT nickname, wg_config FROM users WHERE id = ?",
                (user_id,), fetch=True, one=True
            )
            
            if not user:
                self.send_error(404, "User not found")
                return
            
            if not user["wg_config"]:
                self.send_error(404, "No configuration available for this user")
                return
            
            # 发送配置文件
            config_content = user["wg_config"]
            filename = f"wg-{user['nickname'] or f'user-{user_id}'}.conf"
            
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(config_content.encode('utf-8'))))
            self.end_headers()
            self.wfile.write(config_content.encode('utf-8'))
            
        except Exception as e:
            debug(f"Config download error: {e}")
            self.send_error(500, "Failed to generate config")
    
    def handle_delete_user_api(self, user_id):
        """删除用户"""
        try:
            delete_user(user_id)
            self.send_json_response({
                "status": "success", 
                "message": "用户已删除并从WireGuard中移除"
            })
        except ValueError as e:
            self.send_json_response({"error": str(e)}, 404)
        except Exception as e:
            self.send_json_response({"error": f"Failed to delete user: {e}"}, 500)
    
    def handle_status_api(self):
        """获取系统状态"""
        online_users = len([s for s in user_sessions.values()])
        total_users = execute_db("SELECT COUNT(*) as count FROM users WHERE enabled = 1", fetch=True, one=True)["count"]
        
        # 获取WireGuard接口状态
        try:
            wg_output = subprocess.check_output(
                ["wg", "show", WG_INTERFACE], 
                text=True, 
                timeout=5
            )
            wg_status = "running"
        except:
            wg_status = "error"
        
        status = {
            "system": {
                "interface": WG_INTERFACE,
                "status": wg_status,
                "max_handshake_age": MAX_HANDSHAKE_AGE,
                "monitoring": True
            },
            "users": {
                "total": total_users,
                "online": online_users,
                "active_sessions": len(user_sessions)
            },
            "timestamp": get_current_timestamp()
        }
        self.send_json_response(status)

def run_api_server(port=8000):
    """运行API服务器"""
    try:
        server = HTTPServer(("0.0.0.0", port), APIHandler)
        debug(f"API server started on http://0.0.0.0:{port}")
        server.serve_forever()
    except Exception as e:
        debug(f"API server error: {e}")

# ---------------- 主程序入口 ----------------
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='WireGuard Monitor')
    parser.add_argument('--port', type=int, default=8000, help='API server port')
    parser.add_argument('--interface', type=str, default='wg0', help='WireGuard interface name')
    parser.add_argument('--handshake-timeout', type=int, default=180, help='Handshake timeout in seconds')
    args = parser.parse_args()
    
    # 设置全局配置
    WG_INTERFACE = args.interface
    MAX_HANDSHAKE_AGE = args.handshake_timeout
    
    try:
        # 启动监控线程
        monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        monitor_thread.start()
        
        # 启动API服务器
        run_api_server(args.port)
        
    except KeyboardInterrupt:
        debug("Shutting down...")
    except Exception as e:
        debug(f"Main error: {e}")