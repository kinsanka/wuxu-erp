import csv
import hashlib
import io
import json
import os
import re
import time
import traceback
from collections import deque
from decimal import Decimal
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlsplit

from db import POSTGRES, initialize, transaction
from erp import BusinessError, DEMO_CREDENTIALS, authenticate, demo_login_enabled, execute, login, require, sample_dataset, session_key
from exercise import apply as apply_exercise, view as view_exercise
from exercise_demo import build_demo
from industry import OPERATIONS as INDUSTRIAL_OPERATIONS, apply as apply_industry, view as view_industry
from practice import allowed as practice_allowed, latest as latest_practice, launch as launch_practice, view as view_practice
from read import EXPORTS, bom_detail, document, item_detail, state, trace, walkthrough_targets
from seed import bootstrap

WEB = Path(__file__).resolve().parent.parent / "web"
SECURE_COOKIE = os.getenv("ERP_SECURE_COOKIE","0") == "1"
STATIC = {"/": ("index.html","text/html; charset=utf-8"), "/style.css": ("style.css","text/css; charset=utf-8"),
          "/app.js": ("app.js","text/javascript; charset=utf-8"),
          "/exercise.js": ("exercise.js","text/javascript; charset=utf-8"),
          "/exercise_demo.js": ("exercise_demo.js","text/javascript; charset=utf-8"),
          "/walkthrough.js": ("walkthrough.js","text/javascript; charset=utf-8"),
          "/industry.js": ("industry.js","text/javascript; charset=utf-8")}
IDEMPOTENT_ACTIONS = {
    "master","purchase","sale","approve","receive","ship","bom","work",
    "start","report","finish","inspect","transfer","use","billing","exercise","practice", *INDUSTRIAL_OPERATIONS,
}
LOGIN_ATTEMPTS = {}
ATTEMPT_LOCK = Lock()


def login_attempt(ip):
    now = time.monotonic()
    with ATTEMPT_LOCK:
        for address, times in list(LOGIN_ATTEMPTS.items()):
            while times and times[0] < now - 60:
                times.popleft()
            if not times:
                del LOGIN_ATTEMPTS[address]
        attempts = LOGIN_ATTEMPTS.setdefault(ip, deque())
        require(len(attempts)<20, "登录请求过于频繁，请一分钟后重试", 429)
        attempts.append(now)


def safe_csv(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def csv_export(db,kind,account):
    require(kind in EXPORTS,"报表不存在",404)
    require(kind!="audit" or account["role"]=="admin","无审计导出权限",403)
    require(kind!="clinical" or account["role"] in {"admin","clinical"},"无临床导出权限",403)
    query, columns = EXPORTS[kind]
    output=io.StringIO()
    writer=csv.writer(output)
    writer.writerow([label for _,label in columns])
    for row in db.execute(query):
        writer.writerow([Decimal(row[field])/1000 if field=="quantity" else safe_csv(row[field]) for field,_ in columns])
    return output.getvalue().encode("utf-8-sig")


def perform(db,action,payload,account):
    if action=="exercise":
        return apply_exercise(db,payload,account)
    if action=="practice":
        return launch_practice(db,account)
    if action in INDUSTRIAL_OPERATIONS:
        return apply_industry(db,action,payload,account)
    return execute(db,action,payload,account)


def submit(db,action,payload,account,request_key):
    if not request_key or action not in IDEMPOTENT_ACTIONS:
        return perform(db,action,payload,account)
    require(re.fullmatch(r"[a-zA-Z0-9_-]{16,100}",request_key),"请求标识无效")
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    identity=(account["id"],action,request_key)
    saved=db.one("SELECT digest,response FROM idempotency WHERE user_id=%s AND action=%s AND request_key=%s",identity)
    if saved:
        require(saved["digest"]==digest,"本次请求标识已经用于不同的数据",409)
        return json.loads(saved["response"])
    response=perform(db,action,payload,account)
    current=int(time.time())
    db.execute("DELETE FROM idempotency WHERE created<%s",(current-7*86400,))
    db.execute("INSERT INTO idempotency VALUES (%s,%s,%s,%s,%s,%s)",(*identity,digest,json.dumps(response),current))
    return response


def cookie(token="",valid=True):
    return f"erp_session={token}; Path=/; Max-Age={43200 if valid else 0}; HttpOnly; SameSite=Strict"+("; Secure" if SECURE_COOKIE else "")


class Handler(BaseHTTPRequestHandler):
    server_version = "ERP"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def token(self):
        jar=SimpleCookie(self.headers.get("Cookie",""))
        return jar["erp_session"].value if "erp_session" in jar else ""

    def send_bytes(self,body,kind,code=200,headers=None):
        self.send_response(code)
        self.send_header("Content-Type",kind)
        self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Content-Security-Policy","default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        for name,value in (headers or {}).items():
            self.send_header(name,value)
        self.end_headers()
        self.wfile.write(body)

    def json_response(self,result,code=200,headers=None):
        self.send_bytes(json.dumps(result,ensure_ascii=False).encode(),"application/json; charset=utf-8",code,headers)

    def payload(self):
        origin=self.headers.get("Origin")
        if origin:
            parsed=urlsplit(origin)
            require(parsed.scheme in {"http","https"} and parsed.netloc.lower()==self.headers.get("Host","").lower(),"跨站请求被拒绝",403)
        require(self.headers.get_content_type()=="application/json","仅支持 JSON 请求",415)
        length=self.headers.get("Content-Length","")
        require(length.isdecimal() and 0<int(length)<=131072,"请求体超限或缺失",413)
        try:
            value=json.loads(self.rfile.read(int(length)))
        except (ValueError,UnicodeError):
            raise BusinessError("JSON 格式无效") from None
        require(isinstance(value,dict),"请求体必须是对象")
        return value

    def do_GET(self):
        self.handle_route(False)

    def do_POST(self):
        self.handle_route(True)

    def handle_route(self,write):
        parsed=urlsplit(self.path)
        path=parsed.path
        try:
            if not write and path in STATIC:
                name,kind=STATIC[path]
                self.send_bytes((WEB/name).read_bytes(),kind)
                return
            if not write and path=="/api/health":
                with transaction() as db:
                    db.one("SELECT value FROM settings WHERE key='demo'")
                self.json_response({"ok":True,"db":"postgresql" if POSTGRES else "sqlite"})
                return
            if not write and path=="/api/meta":
                with transaction() as db:
                    result={"demo":sample_dataset(db),"demo_login":demo_login_enabled(db)}
                    if result["demo_login"]:
                        result["demo_account"]=DEMO_CREDENTIALS
                self.json_response(result)
                return
            require(path.startswith("/api/"),"页面不存在",404)
            payload=self.payload() if write else {}
            if write and path=="/api/login":
                login_attempt(self.client_address[0])
                with transaction(write=True) as db:
                    token=login(db,payload)
                self.json_response({"ok":True},headers={"Set-Cookie":cookie(token)})
                return
            token=self.token()
            with transaction(write=write) as db:
                account=authenticate(db,token)
                require(account,"请先登录",401)
                response_headers={}
                if write:
                    if path=="/api/logout":
                        db.execute("DELETE FROM sessions WHERE token=%s",(session_key(token),))
                        result={"ok":True}
                        response_headers["Set-Cookie"]=cookie(valid=False)
                    else:
                        require(path.startswith("/api/action/"),"接口不存在",404)
                        action=path.removeprefix("/api/action/")
                        result=submit(db,action,payload,account,self.headers.get("Idempotency-Key",""))
                        if action=="password":
                            response_headers["Set-Cookie"]=cookie(valid=False)
                elif path=="/api/exercise/demo":
                    result=build_demo()
                elif path=="/api/exercise":
                    result=view_exercise(db,account)
                elif path=="/api/state":
                    result=state(db,account)
                elif path=="/api/walkthrough":
                    run=parse_qs(parsed.query).get("run",[""])[0]
                    result=view_practice(db,run,account) if run else dict(
                        walkthrough_targets(db),practice_allowed=practice_allowed(db,account),latest=latest_practice(db,account),
                    )
                elif path.startswith("/api/industry/"):
                    module,_,ident=path.removeprefix("/api/industry/").partition("/")
                    result=view_industry(db,module,account,ident)
                elif path.startswith("/api/document/"):
                    result=document(db,path.removeprefix("/api/document/"))
                elif path.startswith("/api/bom/"):
                    result=bom_detail(db,path.removeprefix("/api/bom/"))
                elif path.startswith("/api/item/"):
                    result=item_detail(db,path.removeprefix("/api/item/"))
                elif path=="/api/trace":
                    query=parse_qs(parsed.query)
                    result=trace(db,query.get("lot",[""])[0],query.get("code",[""])[0][:221],account)
                elif re.fullmatch(r"/api/export/[a-z]+",path):
                    report=path.rsplit("/",1)[-1]
                    result=csv_export(db,report,account)
                    response_headers["Content-Disposition"]=f'attachment; filename="erp-{report}.csv"'
                else:
                    raise BusinessError("接口不存在",404)
            if isinstance(result,bytes):
                self.send_bytes(result,"text/csv; charset=utf-8",headers=response_headers)
            else:
                self.json_response(result,headers=response_headers)
        except BusinessError as error:
            self.json_response({"error":str(error)},error.status)
        except (BrokenPipeError,ConnectionResetError):
            return
        except Exception:
            traceback.print_exc()
            try:
                self.json_response({"error":"服务处理失败，请查看服务日志"},HTTPStatus.INTERNAL_SERVER_ERROR)
            except (BrokenPipeError,ConnectionResetError):
                return

    def log_message(self,format,*args):
        # Query strings may contain scanned packaging identifiers.
        route=urlsplit(self.path).path
        print(f"{self.command} {route} {args[1] if len(args)>1 else ''}", flush=True)


if __name__=="__main__":
    with transaction(write=True) as connection:
        initialize(connection)
        bootstrap(connection)
    host=os.getenv("ERP_HOST","127.0.0.1")
    port=int(os.getenv("ERP_PORT","8080"))
    print(f"ERP listening on http://{host}:{port}",flush=True)
    ThreadingHTTPServer((host,port),Handler).serve_forever()
