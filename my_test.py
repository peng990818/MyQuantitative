import requests

def debug_proxy():
    proxy = "http://127.0.0.1:7897" # 确保端口和你软件里显示的一致
    proxies = {"http": proxy, "https": proxy}
    try:
        # 测试谷歌或 OKX API 节点
        resp = requests.get("https://www.okx.com/api/v5/public/time", proxies=proxies, timeout=5)
        print(f"✅ 代理测试成功! OKX 时间节点返回: {resp.json()['data'][0]['ts']}")
    except Exception as e:
        print(f"❌ 代理测试失败: {e}")

if __name__ == "__main__":
    debug_proxy()