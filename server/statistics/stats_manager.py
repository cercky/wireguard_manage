#!/usr/bin/env python3
from datetime import datetime
from db.database import execute_db
from utils.helpers import get_current_timestamp
from constants import user_sessions

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