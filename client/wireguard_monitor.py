import http.server
import socketserver
import os
import sys
import json
import datetime
import urllib.request
import urllib.error
import urllib.parse
import traceback

# 全局调试开关
debug_mode = False

def debug_print(message):
    """调试信息输出函数"""
    if debug_mode:
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        print(f"[{timestamp}] DEBUG: {message}")

# 简单的静态文件服务器处理器
class StaticFileHandler(http.server.SimpleHTTPRequestHandler):
    # 重写发送响应头的方法，添加CORS支持
    def send_response(self, code, message=None):
        super().send_response(code, message)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
    
    # 处理OPTIONS请求，用于CORS预检
    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()
    
    # 重写do_GET方法，添加代理功能
    def do_GET(self):
        # 处理代理请求
        if self.path.startswith('/proxy'):
            self.handle_proxy_request()
            return
        
        # 对于静态文件，使用父类的处理方法
        try:
            super().do_GET()
        except ConnectionAbortedError:
            # 处理连接中止错误，不中断服务器
            debug_print("连接已被客户端中止")
            pass
    
    # 重写do_POST方法，添加代理功能
    def do_POST(self):
        # 处理代理请求
        if self.path.startswith('/proxy'):
            self.handle_proxy_request()
            return
        
        # 对于其他POST请求，使用父类的处理方法
        try:
            super().do_POST()
        except ConnectionAbortedError:
            # 处理连接中止错误，不中断服务器
            debug_print("连接已被客户端中止")
            pass
    
    # 处理代理请求的方法
    def handle_proxy_request(self):
        try:
            debug_print(f"开始处理代理请求: {self.path}")
            
            # 解析查询参数
            parsed_url = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            
            # 获取目标URL和方法
            target_url = query_params.get('url', [''])[0]
            target_method = query_params.get('method', ['GET'])[0]
            
            if not target_url:
                raise ValueError("缺少目标URL参数")
            
            debug_print(f"目标URL: {target_url}, 方法: {target_method}")
            debug_print(f"请求头: {self.headers}")
            
            # 读取请求体（适用于POST请求）
            content_length = int(self.headers.get('Content-Length', 0))
            body_data = self.rfile.read(content_length) if content_length > 0 else b''
            
            debug_print(f"请求体大小: {content_length} 字节")
            
            # 解析请求体中的代理配置
            proxy_config = json.loads(body_data) if body_data else {}
            original_body = proxy_config.get('body', None)
            original_headers = proxy_config.get('headers', {})
            
            debug_print(f"代理配置: {proxy_config}")
            
            # 准备代理请求
            req_headers = {
                'User-Agent': 'WireGuard-Monitor-Proxy/1.0',
                **original_headers
            }
            
            # 构建请求数据
            data = json.dumps(original_body).encode('utf-8') if original_body else None
            
            # 创建请求对象
            req = urllib.request.Request(
                target_url,
                data=data,
                headers=req_headers,
                method=target_method
            )
            
            debug_print(f"发送代理请求到: {target_url}")
            
            # 发送请求到目标API
            with urllib.request.urlopen(req, timeout=10) as response:
                # 读取响应内容
                response_data = response.read()
                response_status = response.status
                
                debug_print(f"代理请求成功，状态码: {response_status}")
                debug_print(f"响应头: {response.getheaders()}")
                debug_print(f"响应体大小: {len(response_data)} 字节")
                
                # 发送响应回客户端
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                
                # 解析原始响应数据
                original_data = json.loads(response_data) if response_data else None
                
                # 特殊处理dashboard和status数据，转换为前端期望的格式
                if '/api/dashboard' in target_url and original_data and 'summary' in original_data and 'traffic' in original_data:
                    # 将嵌套的summary和traffic数据转换为扁平结构
                    transformed_data = {
                        'total_users': original_data['summary']['registered_users'],
                        'online_users': original_data['summary']['online_users'],
                        'active_sessions': original_data['summary']['active_sessions'],
                        'uptime_start': original_data['summary'].get('uptime_start', None),
                        'total_tx': original_data['traffic']['upload_raw'],
                        'total_rx': original_data['traffic']['download_raw'],
                        'today_tx': original_data['traffic']['today_upload_raw'],
                        'today_rx': original_data['traffic']['today_download_raw']
                    }
                    debug_print(f"已转换dashboard数据格式: {transformed_data}")
                elif '/api/status' in target_url and original_data and 'system' in original_data and 'users' in original_data:
                    # 将status数据转换为扁平结构
                    transformed_data = {
                        'interface': original_data['system']['interface'],
                        'max_handshake_age': original_data['system']['max_handshake_age'],
                        'total': original_data['users']['total'],
                        'online': original_data['users']['online'],
                        'active_sessions': original_data['users']['active_sessions']
                    }
                    debug_print(f"已转换status数据格式: {transformed_data}")
                elif '/api/users/management' in target_url and original_data:
                    # 提取users数据，确保返回的是一个数组
                    transformed_data = original_data.get('users', []) if isinstance(original_data, dict) else []
                    debug_print(f"已转换users数据格式: {transformed_data}")
                elif ('/api/events' in target_url or '/api/events/history' in target_url) and original_data:
                    # 提取events数据，确保返回的是一个数组
                    transformed_data = original_data.get('events', []) if isinstance(original_data, dict) else []
                    debug_print(f"已转换events数据格式: {transformed_data}")
                elif '/api/traffic/chart' in target_url and original_data:
                    # 提取traffic chart数据，确保返回的是一个数组
                    transformed_data = original_data.get('data', []) if isinstance(original_data, dict) else []
                    debug_print(f"已转换traffic chart数据格式: {transformed_data}")
                else:
                    transformed_data = original_data
                    debug_print(f"未转换的原始数据格式，路径: {target_url}")
                
                # 构造响应对象
                proxy_response = {
                    'status': response_status,
                    'data': transformed_data
                }
                
                self.wfile.write(json.dumps(proxy_response).encode('utf-8'))
                debug_print("代理响应已发送回客户端")
                
        except urllib.error.HTTPError as e:
            # 处理HTTP错误
            debug_print(f"HTTP错误: {e.code} - {e.reason}")
            debug_print(f"错误详情: {traceback.format_exc()}")
            
            self.send_response(200)  # 代理返回200，但在响应体中包含错误信息
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            error_response = {
                'status': e.code,
                'error': 'HTTP Error',
                'reason': str(e.reason)
            }
            
            self.wfile.write(json.dumps(error_response).encode('utf-8'))
        
        except urllib.error.URLError as e:
            # 处理URL错误（连接问题）
            debug_print(f"URL错误: {str(e.reason)}")
            debug_print(f"错误详情: {traceback.format_exc()}")
            
            self.send_response(200)  # 代理返回200，但在响应体中包含错误信息
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            error_response = {
                'status': 500,
                'error': 'Connection Error',
                'reason': f"无法连接到目标服务器: {str(e.reason)}"
            }
            
            self.wfile.write(json.dumps(error_response).encode('utf-8'))
        
        except json.JSONDecodeError as e:
            # 处理JSON解析错误
            debug_print(f"JSON解析错误: {str(e)}")
            debug_print(f"错误详情: {traceback.format_exc()}")
            
            self.send_response(200)  # 代理返回200，但在响应体中包含错误信息
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            error_response = {
                'status': 500,
                'error': 'JSON Parse Error',
                'reason': str(e)
            }
            
            self.wfile.write(json.dumps(error_response).encode('utf-8'))
        
        except Exception as e:
            # 处理其他所有异常
            debug_print(f"未预期的错误: {str(e)}")
            debug_print(f"错误详情: {traceback.format_exc()}")
            
            self.send_response(200)  # 代理返回200，但在响应体中包含错误信息
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            error_response = {
                'status': 500,
                'error': 'Unknown Error',
                'reason': str(e),
                'traceback': traceback.format_exc() if debug_mode else '启用调试模式查看详细错误堆栈'
            }
            
            self.wfile.write(json.dumps(error_response).encode('utf-8'))
        
        finally:
            # 确保请求被正确处理完毕
            debug_print(f"代理请求处理完成: {self.path}")
    
    # 重写log_message，根据debug_mode决定输出内容
    def log_message(self, format, *args):
        if debug_mode:
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            print(f"[{timestamp}] REQUEST: {self.client_address[0]} - {format % args}")

# 启动服务器
def run_server(port=8000):
    global debug_mode
    # 检查是否启用调试模式
    if '--debug' in sys.argv:
        debug_mode = True
        print("调试模式已启用，将输出详细日志信息")
        
    with socketserver.TCPServer(('', port), StaticFileHandler) as httpd:
        print(f'Server started on port {port}')
        if debug_mode:
            debug_print(f"服务器绑定地址: {httpd.server_address}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('Server stopped')

if __name__ == '__main__':
    # 检查是否指定了端口
    port = 8000
    if len(sys.argv) > 1 and sys.argv[1] != '--debug':
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"无效的端口号: {sys.argv[1]}，使用默认端口 8000")
    elif len(sys.argv) > 2:
        try:
            port = int(sys.argv[2])
        except ValueError:
            print(f"无效的端口号: {sys.argv[2]}，使用默认端口 8000")
    
    run_server(port)