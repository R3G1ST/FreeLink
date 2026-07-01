#!/usr/bin/env python3
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import yaml
import sys

class AuthHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        
        try:
            data = json.loads(body)
            addr = data.get('addr', '')
            auth = data.get('auth', '')
            
            # Загружаю базу пользователей
            with open('/opt/vpnbot/data.yaml', 'r') as f:
                db = yaml.safe_load(f)
            
            # Пробуем новый формат "username:password"
            if ':' in auth:
                username, password = auth.split(':', 1)
                
                # Ищу пользователя с таким логином и паролем
                for uid, user in db.get('users', {}).items():
                    if user.get('name') == username and user.get('password') == password:
                        # Успех - возвращаем id пользователя
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        response = {"ok": True, "id": username}
                        self.wfile.write(json.dumps(response).encode())
                        print(f"Auth success (new format): {username} from {addr}", file=sys.stderr)
                        return
            
            # Пробуем старый формат - только пароль
            for uid, user in db.get('users', {}).items():
                if user.get('password') == auth:
                    # Успех - возвращаем id пользователя
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = {"ok": True, "id": user.get('name', uid)}
                    self.wfile.write(json.dumps(response).encode())
                    print(f"Auth success (old format): {user.get('name')} from {addr}", file=sys.stderr)
                    return
            
            # Неверные credentials
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = {"ok": False, "msg": "invalid credentials"}
            self.wfile.write(json.dumps(response).encode())
            print(f"Auth failed from {addr}, auth: {auth}", file=sys.stderr)
            
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            print(f"Error: {e}", file=sys.stderr)

if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1', 8001), AuthHandler)
    print("Auth server running on 127.0.0.1:8001")
    server.serve_forever()
