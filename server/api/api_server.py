#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json
from datetime import datetime
import subprocess

from utils.helpers import debug, get_current_timestamp, readable_bytes
from db.database import execute_db
from user_management.user_manager import create_user, update_user, delete_user
from statistics.stats_manager import get_user_management_info, get_events_history, get_traffic_chart_data, get_dashboard_stats
from session_monitor.session_handler import handle_peer_offline
from constants import WG_INTERFACE, MAX_HANDSHAKE_AGE, user_sessions

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