#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import sys

sys.path.insert(0, "/opt/freelink")
import db
db.init_db()

class AuthHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        
        try:
            data = json.loads(body)
            addr = data.get('addr', '')
            auth = data.get('auth', '')
            
            # Новый формат "username:password"
            if ':' in auth:
                username, password = auth.split(':', 1)
                user, uid = db.get_user_by_credentials(username, password)
                if user:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True, "id": username}).encode())
                    print(f"Auth success (new): {username} from {addr}", file=sys.stderr)
                    return
            
            # Старый формат — только пароль
            # Ищем пользователя с таким паролем
            all_users = db.get_all_users()
            for uid, user in all_users.items():
                if user.get("password") == auth:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True, "id": user.get("name", uid)}).encode())
                    print(f"Auth success (old): {user.get('name')} from {addr}", file=sys.stderr)
                    return
            
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "msg": "invalid credentials"}).encode())
            print(f"Auth failed from {addr}", file=sys.stderr)
            
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            print(f"Error: {e}", file=sys.stderr)

if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1', 8001), AuthHandler)
    print("Auth server running on 127.0.0.1:8001")
    server.serve_forever()
