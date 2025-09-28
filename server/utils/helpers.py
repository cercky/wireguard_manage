#!/usr/bin/env python3
from datetime import datetime
import re
import base64

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