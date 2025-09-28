#!/usr/bin/env python3
from datetime import datetime
import time
from db.database import execute_db, update_user_status
from utils.helpers import debug, get_current_timestamp, readable_bytes
from statistics.stats_manager import update_user_traffic_stats, update_daily_traffic_stats
from constants import MAX_HANDSHAKE_AGE, user_sessions
from wireguard_interface.wg_commands import get_wg_peers

# ---------------- 会话监控逻辑 ----------------
def is_peer_online(handshake_time, max_handshake_age=None):
    """判断对等体是否在线"""
    # 如果没有提供max_handshake_age，则使用默认值
    if max_handshake_age is None:
        max_handshake_age = MAX_HANDSHAKE_AGE
    
    if handshake_time == 0:
        return False
    
    current_time = time.time()
    return (current_time - handshake_time) <= max_handshake_age

def handle_peer_online(pubkey, peer_info):
    """处理对等体上线"""
    try:
        from user_management.user_manager import get_or_create_user
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

def monitor_wireguard(max_handshake_age=None):
    """监控WireGuard连接状态"""
    # 如果没有提供max_handshake_age，则使用默认值
    if max_handshake_age is None:
        max_handshake_age = MAX_HANDSHAKE_AGE
    
    current_peers = get_wg_peers()
    current_time = time.time()
    active_pubkeys = set()
    
    # 处理当前在线的对等体
    for pubkey, peer_info in current_peers.items():
        active_pubkeys.add(pubkey)
        
        if is_peer_online(peer_info["handshake"], max_handshake_age):
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
            from statistics.stats_manager import update_system_stats
            update_system_stats()
            monitor_wireguard.last_stats_update = current_time
        except Exception as e:
            debug(f"Failed to update system stats: {e}")

def monitor_loop(interval=10, max_handshake_age=None):
    """主监控循环"""
    from db.database import init_db
    from utils.helpers import readable_bytes
    import time
    
    # 如果没有提供max_handshake_age，则使用默认值
    if max_handshake_age is None:
        max_handshake_age = MAX_HANDSHAKE_AGE
    
    init_db()
    debug(f"WireGuard monitor started with interval {interval}s and max handshake age {max_handshake_age}s")
    
    while True:
        try:
            monitor_wireguard(max_handshake_age)
        except Exception as e:
            debug(f"Monitor error: {e}")
        
        time.sleep(interval)

# ---------------- 会话管理 ----------------
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