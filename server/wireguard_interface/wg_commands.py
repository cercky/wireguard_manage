#!/usr/bin/env python3
import subprocess
from utils.helpers import debug
from constants import WG_INTERFACE
from db.database import execute_db

# ---------------- WireGuard接口 ----------------
def get_wg_peers(interface=WG_INTERFACE):
    """获取WireGuard对等体信息"""
    try:
        output = subprocess.check_output(
            ["wg", "show", interface, "dump"], 
            universal_newlines=True, 
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

def add_wg_peer(pubkey, client_ip):
    """添加WireGuard对等体"""
    try:
        # 这里需要实现实际的添加对等体代码
        # 注意：实际环境中需要根据系统配置执行相应的WireGuard命令
        debug(f"Adding peer {pubkey[:16]}... with IP {client_ip}")
        return True
    except Exception as e:
        debug(f"Failed to add peer: {e}")
        return False

def remove_wg_peer(pubkey):
    """移除WireGuard对等体"""
    try:
        # 这里需要实现实际的移除对等体代码
        # 注意：实际环境中需要根据系统配置执行相应的WireGuard命令
        debug(f"Removing peer {pubkey[:16]}...")
        return True
    except Exception as e:
        debug(f"Failed to remove peer: {e}")
        return False

def get_next_available_ip():
    """获取下一个可用的客户端IP"""
    # 这里需要实现实际的IP分配逻辑
    # 简单示例：从已分配IP中找出最大的，然后加1
    try:
        result = execute_db("SELECT client_ip FROM users WHERE client_ip IS NOT NULL", fetch=True)
        if not result:
            return "10.0.0.2"  # 默认起始IP
            
        # 提取IP并排序
        ip_list = [row["client_ip"] for row in result]
        ip_list.sort()
        
        # 获取最后一个IP并递增
        last_ip = ip_list[-1]
        parts = last_ip.split(".")
        last_octet = int(parts[3])
        next_octet = last_octet + 1
        
        # 检查是否超过子网范围
        if next_octet > 254:
            raise ValueError("No available IP addresses")
            
        return f"{parts[0]}.{parts[1]}.{parts[2]}.{next_octet}"
    except Exception as e:
        debug(f"Failed to get next available IP: {e}")
        raise

def generate_wg_config(server_public_key, client_public_key, client_ip):
    """生成WireGuard客户端配置"""
    # 这里需要实现实际的配置生成逻辑
    # 这是一个示例配置
    config = f"""
[Interface]
PrivateKey = <CLIENT_PRIVATE_KEY>
Address = {client_ip}/32
DNS = 8.8.8.8, 8.8.4.4

[Peer]
PublicKey = {server_public_key or "SERVER_PUBLIC_KEY"}
Endpoint = server.example.com:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""
    return config