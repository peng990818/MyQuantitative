import os
import requests
import json
import time  # 👈 新增 time 模块
from dotenv import load_dotenv

# 加载环境配置
load_dotenv(override=True)


class NewsFetcher:
    def __init__(self):
        # 1. 自动去除 API Key 前后的空格
        raw_key = os.getenv("CRYPTOPANIC_API_KEY", "")
        self.api_key = raw_key.strip()

        # 🔥 [修改] 切换回开发者 v2 接口
        self.base_url = "https://cryptopanic.com/api/developer/v2/posts/"

        # 2. 智能代理配置 (Smart Proxy)
        self.proxies = None
        proxy_port = os.getenv("PROXY_PORT", "")

        if proxy_port:
            port = proxy_port.strip()
            proxy_url = f"http://127.0.0.1:{port}"
            self.proxies = {
                "http": proxy_url,
                "https": proxy_url
            }
            print(f"🌍 [新闻模块] 使用代理连接: {proxy_url}")
        else:
            print("🚀 [新闻模块] 使用直连模式 (Direct Connection)")

    def test_connection(self):
        """测试网络连通性 (基于当前代理设置)"""
        try:
            target_url = "https://www.google.com" if self.proxies else "https://www.baidu.com"
            print(f"📡 测试网络连通性 ({target_url})...")

            resp = requests.get(target_url, proxies=self.proxies, timeout=5)

            if resp.status_code == 200:
                print("✅ 网络通畅！")
                return True
            else:
                print(f"⚠️ 网络异常，状态码: {resp.status_code}")
                return False
        except Exception as e:
            print(f"❌ 网络连接失败: {e}")
            if self.proxies:
                print("💡 提示: 请检查代理软件是否开启，或端口是否正确。")
            return False

    def get_latest_news(self, symbol="BTC", limit=5):
        """
        策略：优先抓取重大新闻，如果没有，则抓取普通新闻。
        """
        if not self.api_key:
            return "No news API key configured."

        # 处理交易对符号，例如 BTC/USDT -> BTC
        currency = symbol.split('/')[0]

        # === 第一步：尝试获取“重要”新闻 ===
        # print("🔍 正在搜索重大新闻...")
        news_text = self._fetch_internal(currency, filter_mode="important", limit=limit)

        # === 第二步：如果没抓到，降级获取“所有”新闻 ===
        if not news_text:
            # print("⚠️ 暂无重大新闻，降级获取最新资讯...")
            # 🔥 [关键] 两次请求之间强制休息 1 秒，防止瞬间 429
            time.sleep(1)
            news_text = self._fetch_internal(currency, filter_mode=None, limit=limit)

        # 如果还是没有
        if not news_text:
            return "No news found currently."

        return news_text

    def _fetch_internal(self, currency, filter_mode, limit):
        """内部请求逻辑 (带 429 重试机制)"""
        params = {
            "auth_token": self.api_key,
            "currencies": currency,
            "kind": "news",
            "public": "true"
        }
        # 只有当指定了 filter 时才传参
        if filter_mode:
            params["filter"] = filter_mode

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
        }

        # 🔥 [新增] 最多重试 3 次
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.get(
                    self.base_url,
                    params=params,
                    headers=headers,
                    proxies=self.proxies,
                    timeout=10
                )

                if response.status_code == 200:
                    # 成功获取，跳出重试循环，处理数据
                    data = response.json()
                    results = data.get('results', [])

                    if not results:
                        return None

                    news_summary = []
                    for item in results[:limit]:
                        title = item.get('title', 'Unknown')
                        published_at = item.get('published_at', '').replace('T', ' ')[:16]
                        source = item.get('source', {}).get('title', 'Web')
                        icon = "🔥" if filter_mode == "important" else "📢"
                        news_summary.append(f"- {icon} [{published_at}] ({source}) {title}")

                    return "\n".join(news_summary)

                # 🔥 处理 429 错误
                elif response.status_code == 429:
                    wait_time = 2 * (attempt + 1)  # 第一次等2秒，第二次等4秒...
                    print(f"⏳ 触发限流 (429)，正在冷却 {wait_time} 秒后重试...")
                    time.sleep(wait_time)
                    continue  # 继续下一次循环

                elif response.status_code == 403:
                    print(f"❌ 权限错误 (403): 请检查 API Key 是否正确。当前使用的是开发者 v2 接口。")
                    return None
                else:
                    print(f"❌ 请求失败: 状态码 {response.status_code}")
                    return None

            except Exception as e:
                print(f"⚠️ 新闻抓取异常: {e}")
                return None

        # 如果重试次数用完还是不行
        print("❌ 多次重试失败，放弃本次抓取。")
        return None


if __name__ == "__main__":
    fetcher = NewsFetcher()
    if fetcher.test_connection():
        print("\n📰 测试智能抓取 (BTC):")
        # 🔥 为了测试重试逻辑，这里可以故意连续调两次
        news = fetcher.get_latest_news("BTC/USDT")
        print(news)
    else:
        print("❌ 网络未通，无法测试")