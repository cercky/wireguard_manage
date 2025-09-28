#!/usr/bin/env python3
from datetime import datetime
from db.database import execute_db
from utils.helpers import debug, get_current_timestamp, validate_pubkey, validate_email
from constants import user_sessions
from wireguard_interface.wg_commands import add_wg_peer, remove_wg_peer, get_next_available_ip, generate_wg_config

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
    
    # 延迟导入close_session函数以避免循环导入
    from session_monitor.session_handler import close_session
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