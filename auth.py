#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import sys

sys.path.insert(0, "/opt/freelink")
import db
db.init_db()

def extract_ip(addr):
    """Extract IP from 'ip:port' format."""
    if ':' in addr:
        return addr.rsplit(':', 1)[0]
    return addr

class AuthHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        
        try:
            data = json.loads(body)
            addr = data.get('addr', '')
            auth = data.get('auth', '')
            client_ip = extract_ip(addr)
            
            # Новый формат "username:password"
            if ':' in auth:
                username, password = auth.split(':', 1)
                user, uid = db.get_user_by_credentials(username, password)
                if user:
                    # Check if user is active
                    if not user.get("active", True):
                        self.send_response(403)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({"ok": False, "msg": "account_disabled"}).encode())
                        print(f"Auth blocked (disabled): {username} from {client_ip}", file=sys.stderr)
                        return
                    # Check if subscription expired
                    from datetime import datetime
                    expire = user.get("expire_date", "")
                    if expire:
                        try:
                            # Try multiple formats
                            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                                try:
                                    expire_dt = datetime.strptime(expire, fmt)
                                    break
                                except ValueError:
                                    continue
                            else:
                                expire_dt = None
                            if expire_dt and expire_dt < datetime.now():
                                self.send_response(403)
                                self.send_header('Content-Type', 'application/json')
                                self.end_headers()
                                self.wfile.write(json.dumps({"ok": False, "msg": "subscription_expired"}).encode())
                                print(f"Auth blocked (expired): {username} from {client_ip}", file=sys.stderr)
                                return
                        except Exception:
                            pass
                    # Check device limit
                    if not db.check_device_limit(username, client_ip):
                        self.send_response(403)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({"ok": False, "msg": "device_limit_reached"}).encode())
                        print(f"Auth blocked (device limit): {username} from {client_ip}", file=sys.stderr)
                        return
                    db.log_connection(username, client_ip)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True, "id": username}).encode())
                    print(f"Auth success (new): {username} from {client_ip}", file=sys.stderr)
                    return

            # Старый формат — только пароль
            all_users = db.get_all_users()
            for uid, user in all_users.items():
                if user.get("password") == auth:
                    uname = user.get("name", uid)
                    # Check if user is active
                    if not user.get("active", True):
                        self.send_response(403)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({"ok": False, "msg": "account_disabled"}).encode())
                        print(f"Auth blocked (disabled): {uname} from {client_ip}", file=sys.stderr)
                        return
                    # Check if subscription expired
                    from datetime import datetime
                    expire = user.get("expire_date", "")
                    if expire:
                        try:
                            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                                try:
                                    expire_dt = datetime.strptime(expire, fmt)
                                    break
                                except ValueError:
                                    continue
                            else:
                                expire_dt = None
                            if expire_dt and expire_dt < datetime.now():
                                self.send_response(403)
                                self.send_header('Content-Type', 'application/json')
                                self.end_headers()
                                self.wfile.write(json.dumps({"ok": False, "msg": "subscription_expired"}).encode())
                                print(f"Auth blocked (expired): {uname} from {client_ip}", file=sys.stderr)
                                return
                        except Exception:
                            pass
                    # Check device limit
                    if not db.check_device_limit(uname, client_ip):
                        self.send_response(403)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({"ok": False, "msg": "device_limit_reached"}).encode())
                        print(f"Auth blocked (device limit): {uname} from {client_ip}", file=sys.stderr)
                        return
                    db.log_connection(uname, client_ip)
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True, "id": uname}).encode())
                    print(f"Auth success (old): {uname} from {client_ip}", file=sys.stderr)
                    return
            
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "msg": "invalid credentials"}).encode())
            print(f"Auth failed from {client_ip}", file=sys.stderr)
            
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            print(f"Error: {e}", file=sys.stderr)

if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1', 8001), AuthHandler)
    print("Auth server running on 127.0.0.1:8001")
    server.serve_forever()
