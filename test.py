from contextlib import contextmanager


@contextmanager
def connect(url : str):
    print(f"获取连接:{url}")
    yield f"http://{url}"
    print(f"断开连接:{url}")
    
with connect("http://127.0.0.1:8000/") as conn:
    print(f"基于获取的连接{conn}完成业务操作")